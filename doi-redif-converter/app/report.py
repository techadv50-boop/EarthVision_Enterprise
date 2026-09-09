"""Final conversion report helpers."""

from __future__ import annotations

from typing import Iterable

from .models import ArticleMeta


def failed_entries(metas: Iterable[ArticleMeta]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for meta in metas:
        if meta.ok:
            continue
        out.append(
            {
                "doi": meta.doi,
                "error": meta.error or "Unknown error",
            }
        )
    return out


def build_summary(
    *,
    total: int,
    succeeded: int,
    failed: int,
    failed_dois: list[dict[str, str]] | None = None,
    elapsed_sec: float | None = None,
) -> dict:
    left_incomplete = max(0, total - succeeded - failed)
    return {
        "total": total,
        "processed": succeeded + failed,
        "succeeded": succeeded,
        "failed": failed,
        "left": left_incomplete,
        "elapsed_sec": elapsed_sec,
        "failed_dois": failed_dois or [],
    }


def format_report_text(summary: dict) -> str:
    lines = [
        "DOI → ReDIF Conversion Report",
        "=============================",
        f"Total DOIs in list : {summary.get('total', 0)}",
        f"Processed          : {summary.get('processed', 0)}",
        f"Succeeded (done)   : {summary.get('succeeded', 0)}",
        f"Failed (not done)  : {summary.get('failed', 0)}",
        f"Left incomplete    : {summary.get('left', 0)}",
    ]
    if summary.get("elapsed_sec") is not None:
        lines.append(f"Elapsed (sec)      : {summary['elapsed_sec']}")
    lines.append("")
    failed = summary.get("failed_dois") or []
    if not failed:
        lines.append("All accessible DOIs were converted successfully.")
    else:
        lines.append("DOIs that could not be converted:")
        lines.append("---------------------------------")
        for item in failed:
            lines.append(f"- {item.get('doi')}")
            lines.append(f"  Reason: {item.get('error')}")
    lines.append("")
    return "\n".join(lines)


def format_failed_csv(failed_dois: list[dict[str, str]]) -> str:
    lines = ["doi,error"]
    for item in failed_dois:
        doi = (item.get("doi") or "").replace('"', "'")
        err = (item.get("error") or "").replace('"', "'")
        lines.append(f'"{doi}","{err}"')
    return "\n".join(lines) + "\n"
