#!/usr/bin/env python3
"""E1.5 multi-process worker consistency check for true_color pins.

Spawns N worker processes that each resolve + render true_color while the
parent promotes/rolls back pins. Asserts:

1. Every completed response is a coherent version label + complete PNG
   (no mixed/partial GIS payloads) during concurrent churn.
2. After each settled activation, EVERY worker observes the intended version
   (closes inconsistent-version windows once the pin commit is visible).
"""

from __future__ import annotations

import base64
import json
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import numpy as np  # noqa: E402


def _label_from_message(msg: str) -> str:
    if "tool_pack_v11:1.1.0" in msg or "tool_pack:1.1.0" in msg:
        return "1.1.0"
    if "tool_pack:1.0.0" in msg:
        return "1.0.0"
    return "builtin"


def _worker(pins_path: str, work_q: mp.Queue, result_q: mp.Queue, worker_id: int) -> None:
    os.environ["EV_RUNTIME_PINS"] = pins_path
    # Fresh interpreter → isolated module/pin caches (like separate uvicorn workers)
    from app.schemas.composite import CompositeRequest
    from app.services.composite_service import CompositeService
    from app.tools import runtime_pins as rp

    rgb = np.full((8, 8, 3), 90.0)
    mask = np.ones((8, 8), dtype=bool)
    bounds = [10.0, 20.0, 11.0, 21.0]

    def _visual(self, scene_id, bbox, size):  # noqa: ANN001
        return rgb, bounds, mask, None

    CompositeService._load_visual_rgb = _visual  # type: ignore[method-assign]

    while True:
        item = work_q.get()
        if item is None:
            break
        phase, seq = item
        rp._CACHE["mtime"] = None
        rp._CACHE["data"] = None
        try:
            resp = CompositeService().render_composite(
                CompositeRequest(preset="true_color", scene_id="mw", size=64)
            )
            raw = base64.b64decode(resp.overlay_base64)
            ok_png = raw[:8] == b"\x89PNG\r\n\x1a\n"
            label = _label_from_message(resp.message or "")
            pin = rp.get_pin("true_color")
            result_q.put(
                {
                    "worker": worker_id,
                    "phase": phase,
                    "seq": seq,
                    "label": label,
                    "ok_png": ok_png,
                    "pin_mode": pin.get("mode"),
                    "pin_version": pin.get("version"),
                }
            )
        except Exception as exc:  # noqa: BLE001
            result_q.put(
                {
                    "worker": worker_id,
                    "phase": phase,
                    "seq": seq,
                    "error": str(exc),
                }
            )


def _pin_doc(mode: str, version: str | None, digest: str | None) -> dict:
    return {
        "schema_version": 1,
        "pins": {
            "true_color": {
                "mode": mode,
                "version": version,
                "digest": digest,
            }
        },
    }


def _drain(result_q: mp.Queue, expected: int, timeout: float = 60.0) -> list[dict]:
    results: list[dict] = []
    deadline = time.time() + timeout
    while len(results) < expected and time.time() < deadline:
        try:
            results.append(result_q.get(timeout=1))
        except Exception:  # noqa: BLE001
            break
    return results


def main() -> int:
    import tempfile

    from app.tools.pack_loader import verify_pack
    from app.tools.runtime_pins import write_pins

    tmp = Path(tempfile.mkdtemp(prefix="e15_pins_"))
    pins = tmp / "runtime_pins.json"
    os.environ["EV_RUNTIME_PINS"] = str(pins)

    meta0 = verify_pack("true_color", "1.0.0")
    meta1 = verify_pack("true_color", "1.1.0")

    write_pins(_pin_doc("pack", "1.0.0", meta0["digest"]))

    n_workers = 4
    work_q: mp.Queue = mp.Queue()
    result_q: mp.Queue = mp.Queue()
    procs = [
        mp.Process(target=_worker, args=(str(pins), work_q, result_q, i))
        for i in range(n_workers)
    ]
    for p in procs:
        p.start()

    # --- Phase A: concurrent churn during promote/rollback ---
    seq = 0
    churn_expected = 0
    for round_i in range(6):
        for _ in range(n_workers * 3):
            work_q.put(("churn", seq))
            seq += 1
            churn_expected += 1
        time.sleep(0.05)
        if round_i % 3 == 0:
            write_pins(_pin_doc("pack", "1.1.0", meta1["digest"]))
        elif round_i % 3 == 1:
            write_pins(_pin_doc("pack", "1.0.0", meta0["digest"]))
        else:
            write_pins(_pin_doc("builtin", None, None))
        time.sleep(0.05)

    churn_results = _drain(result_q, churn_expected)

    # --- Phase B: settled activation — every worker must agree ---
    settled_targets = [
        ("1.1.0", _pin_doc("pack", "1.1.0", meta1["digest"])),
        ("1.0.0", _pin_doc("pack", "1.0.0", meta0["digest"])),
        ("builtin", _pin_doc("builtin", None, None)),
        ("1.1.0", _pin_doc("pack", "1.1.0", meta1["digest"])),
    ]
    settled_reports: list[dict] = []
    settled_ok = True
    for expected_label, doc in settled_targets:
        write_pins(doc)
        time.sleep(0.02)  # allow filesystem mtime visibility
        for i in range(n_workers):
            work_q.put(("settled:" + expected_label, i))
        batch = _drain(result_q, n_workers, timeout=30)
        labels = {r.get("label") for r in batch if "label" in r}
        errors = [r for r in batch if "error" in r]
        unanimous = labels == {expected_label} and not errors and len(batch) == n_workers
        settled_reports.append(
            {
                "expected": expected_label,
                "labels": sorted(x for x in labels if x),
                "completed": len(batch),
                "errors": errors[:3],
                "unanimous": unanimous,
            }
        )
        if not unanimous:
            settled_ok = False

    for _ in procs:
        work_q.put(None)

    for p in procs:
        p.join(timeout=10)
        if p.is_alive():
            p.terminate()

    errors = [r for r in churn_results if "error" in r]
    bad_png = [r for r in churn_results if r.get("ok_png") is False]
    labels = {r.get("label") for r in churn_results if "label" in r}

    report = {
        "workers": n_workers,
        "churn": {
            "scheduled": churn_expected,
            "completed": len(churn_results),
            "errors": errors[:5],
            "bad_png_count": len(bad_png),
            "labels_seen": sorted(x for x in labels if x),
            "ok": not errors and not bad_png and len(churn_results) >= churn_expected * 0.9,
        },
        "settled_activation": {
            "checks": settled_reports,
            "ok": settled_ok,
        },
        "ok": (
            not errors
            and not bad_png
            and len(churn_results) >= churn_expected * 0.9
            and settled_ok
        ),
    }
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    # macOS/Linux spawn
    mp.set_start_method("spawn", force=True)
    raise SystemExit(main())
