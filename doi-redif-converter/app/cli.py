"""Command-line interface for batch DOI → ReDIF conversion."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from .extractor import dois_from_xlsx_bytes, extract_many, parse_doi_list
from .redif import DEFAULT_REPEC_HANDLE_PREFIX, build_filename, to_redif
from .report import build_summary, failed_entries, format_failed_csv, format_report_text


def _load_dois(args: argparse.Namespace) -> list[str]:
    dois: list[str] = []
    if args.input:
        path = Path(args.input)
        raw = path.read_bytes()
        if path.suffix.lower() in {".xlsx", ".xlsm"}:
            dois.extend(dois_from_xlsx_bytes(raw))
        else:
            dois.extend(parse_doi_list(raw.decode("utf-8", errors="ignore")))
    if args.dois:
        dois.extend(args.dois)
    if not sys.stdin.isatty():
        dois.extend(parse_doi_list(sys.stdin.read()))

    seen: set[str] = set()
    unique: list[str] = []
    for doi in dois:
        key = doi.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(doi)
    return unique


async def _run(args: argparse.Namespace) -> int:
    dois = _load_dois(args)
    if not dois:
        print("No DOIs provided.", file=sys.stderr)
        return 1

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Converting {len(dois)} DOI(s)…")
    done = 0

    def on_progress(event: dict) -> None:
        nonlocal done
        if event.get("phase") != "done":
            return
        done += 1
        meta = event["meta"]
        left = len(dois) - done
        status = "OK" if meta.ok else "FAIL"
        print(f"[{done}/{len(dois)} | {left} left] {status} {meta.doi}")

    metas = await extract_many(dois, concurrency=args.concurrency, progress_cb=on_progress)

    ok = 0
    used: dict[str, int] = {}
    for meta in metas:
        if not meta.ok:
            continue
        name = build_filename(meta)
        count = used.get(name, 0)
        used[name] = count + 1
        if count:
            stem = name[:-6] if name.endswith(".redif") else name
            name = f"{stem}_{count + 1}.redif"
        path = out_dir / name
        path.write_bytes(to_redif(meta, handle_prefix=args.handle_prefix).encode("utf-8"))
        ok += 1

    failed = failed_entries(metas)
    summary = build_summary(
        total=len(metas),
        succeeded=ok,
        failed=len(failed),
        failed_dois=failed,
    )
    report_text = format_report_text(summary)
    (out_dir / "_conversion_report.txt").write_text(report_text, encoding="utf-8")
    (out_dir / "_failed.csv").write_text(format_failed_csv(failed), encoding="utf-8")

    print()
    print(report_text)
    print(f"Files written to: {out_dir}")
    return 0 if ok else 2


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Convert DOIs to ReDIF-Article files")
    parser.add_argument("-i", "--input", help="Input .xlsx/.txt/.csv with DOIs")
    parser.add_argument("-o", "--output", default="redif_out", help="Output directory")
    parser.add_argument("--dois", nargs="*", help="DOIs passed directly")
    parser.add_argument(
        "--handle-prefix",
        default=DEFAULT_REPEC_HANDLE_PREFIX,
        help="RePEc handle prefix",
    )
    parser.add_argument("-c", "--concurrency", type=int, default=5)
    args = parser.parse_args(argv)
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
