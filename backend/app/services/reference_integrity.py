"""Compare References sections of two Word manuscripts.

Staff may shuffle the list; that is acceptable only when each reference keeps
the same number and the same bibliographic identity as the original file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Optional

from app.services.citation_counts import normalize_doi
from app.services.manuscript_text import extract_docx_paragraphs, extract_manuscript_text

DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
URL_RE = re.compile(r"https?://[^\s\]>)]+", re.I)
NUMBER_RE = re.compile(
    r"^(?:\[(\d+)\]|(\d+)\s*[\.\)])\s*(.*)$",
    re.S,
)
NUMBERED_PREFIX_RE = re.compile(
    r"^(?:\d+(?:\.\d+)*|[IVXLCM]+)[\.\)]\s+",
    re.I,
)
_REF_HEADINGS = {
    "references",
    "reference",
    "bibliography",
    "works cited",
    "literature cited",
    "list of references",
    "references cited",
    "cited references",
}
_STOP_HEADINGS = {
    "acknowledgement",
    "acknowledgements",
    "acknowledgment",
    "acknowledgments",
    "appendix",
    "appendices",
    "author contribution",
    "author contributions",
    "conflict of interest",
    "conflicts of interest",
    "competing interest",
    "competing interests",
    "funding",
    "data availability",
    "supplementary",
    "supplementary material",
    "supplementary materials",
    "biography",
    "author biography",
}
SAME_RATIO = 0.94
CHANGED_RATIO = 0.55


@dataclass
class ReferenceItem:
    number: Optional[int]
    body: str
    raw: str
    doi: Optional[str] = None
    fingerprint: str = ""
    index: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "text": self.raw,
            "body": self.body,
            "doi": self.doi,
            "fingerprint": self.fingerprint,
            "index": self.index,
        }


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _heading_label(text: str) -> str:
    compact = _compact(text)
    compact = NUMBERED_PREFIX_RE.sub("", compact)
    compact = compact.rstrip(":.").strip()
    return re.sub(r"[^a-z]+", " ", compact.lower()).strip()


def is_references_heading(text: str) -> bool:
    label = _heading_label(text)
    return label in _REF_HEADINGS


def _is_stop_heading(text: str) -> bool:
    label = _heading_label(text)
    if not label:
        return False
    if label in _STOP_HEADINGS:
        return True
    first = label.split()[0]
    if first in _STOP_HEADINGS and len(label.split()) <= 8:
        return True
    if first == "appendix" and len(label.split()) <= 8:
        return True
    return False


def _normalize_body(text: str) -> str:
    value = (text or "").lower()
    value = value.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    value = URL_RE.sub(" ", value)
    value = re.sub(r"\bdoi:\s*", " ", value)
    value = DOI_RE.sub(" ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _fingerprint(body: str, doi: Optional[str]) -> str:
    if doi:
        return f"doi:{doi.lower()}"
    urls = URL_RE.findall(body or "")
    if urls:
        return "url:" + urls[0].rstrip(".,;").lower()
    return "t:" + _normalize_body(body)[:280]


def _extract_doi(text: str) -> Optional[str]:
    match = DOI_RE.search(text or "")
    if not match:
        return None
    return normalize_doi(match.group(0))


def paragraphs_from_upload(data: bytes, filename: str = "") -> list[str]:
    name = (filename or "").lower()
    if name.endswith(".docx") or (data[:2] == b"PK" and data[:4] != b"%PDF"):
        paragraphs = extract_docx_paragraphs(data)
        if paragraphs:
            return paragraphs
    text = extract_manuscript_text(data, filename)
    return [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def extract_reference_lines(paragraphs: list[str]) -> tuple[list[str], Optional[str], bool]:
    """Return (lines after the References heading, heading text, heading_found)."""
    start = None
    heading = None
    for i, para in enumerate(paragraphs):
        if is_references_heading(para):
            start = i + 1
            heading = _compact(para)
            break
    if start is None:
        numbered = [p for p in paragraphs if NUMBER_RE.match(_compact(p))]
        if len(numbered) >= 2 and len(numbered) >= max(2, int(len(paragraphs) * 0.4)):
            return paragraphs, None, False
        return [], None, False
    lines: list[str] = []
    for para in paragraphs[start:]:
        if _is_stop_heading(para) and not NUMBER_RE.match(_compact(para)):
            break
        if para.strip():
            lines.append(para)
    return lines, heading, True


def parse_reference_items(lines: list[str]) -> list[ReferenceItem]:
    items: list[ReferenceItem] = []
    current: Optional[dict[str, Any]] = None

    def flush() -> None:
        nonlocal current
        if not current:
            return
        body = _compact(" ".join(current["parts"]))
        raw = _compact(current["raw"])
        doi = _extract_doi(raw)
        items.append(
            ReferenceItem(
                number=current["number"],
                body=body,
                raw=raw,
                doi=doi,
                fingerprint=_fingerprint(body, doi),
                index=len(items),
            )
        )
        current = None

    for line in lines:
        compact = _compact(line)
        if not compact:
            continue
        match = NUMBER_RE.match(compact)
        if match:
            flush()
            number = int(match.group(1) or match.group(2))
            rest = (match.group(3) or "").strip()
            current = {"number": number, "parts": [rest] if rest else [], "raw": compact}
            continue
        if current is None:
            current = {"number": None, "parts": [compact], "raw": compact}
        else:
            current["parts"].append(compact)
            current["raw"] = current["raw"] + " " + compact
    flush()
    return items


def extract_references(data: bytes, filename: str = "") -> dict[str, Any]:
    paragraphs = paragraphs_from_upload(data, filename)
    lines, heading, heading_found = extract_reference_lines(paragraphs)
    items = parse_reference_items(lines)
    return {
        "filename": filename,
        "heading": heading,
        "heading_found": heading_found,
        "paragraph_count": len(paragraphs),
        "items": items,
    }


def _same_item(left: ReferenceItem, right: ReferenceItem) -> bool:
    if left.doi and right.doi and left.doi.lower() == right.doi.lower():
        return True
    if left.fingerprint.startswith("url:") and left.fingerprint == right.fingerprint:
        return True
    a = _normalize_body(left.body)
    b = _normalize_body(right.body)
    if a and a == b:
        return True
    if not a or not b:
        return False
    return SequenceMatcher(None, a, b).ratio() >= SAME_RATIO


def _similarity(left: ReferenceItem, right: ReferenceItem) -> float:
    if left.doi and right.doi and left.doi.lower() == right.doi.lower():
        return 1.0
    a = _normalize_body(left.body)
    b = _normalize_body(right.body)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _payload(item: Optional[ReferenceItem]) -> Optional[dict[str, Any]]:
    return item.as_dict() if item else None


def compare_reference_items(
    original: list[ReferenceItem],
    returned: list[ReferenceItem],
) -> dict[str, Any]:
    orig_by_num: dict[int, ReferenceItem] = {}
    dup_original: list[int] = []
    for item in original:
        if item.number is None:
            continue
        if item.number in orig_by_num:
            dup_original.append(item.number)
        orig_by_num[item.number] = item

    ret_by_num: dict[int, ReferenceItem] = {}
    dup_returned: list[int] = []
    for item in returned:
        if item.number is None:
            continue
        if item.number in ret_by_num:
            dup_returned.append(item.number)
        ret_by_num[item.number] = item

    numbered_original = [item for item in original if item.number is not None]
    numbered_returned = [item for item in returned if item.number is not None]
    use_numbers = bool(numbered_original) and bool(numbered_returned)

    removed: list[dict[str, Any]] = []
    added: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    renumbered: list[dict[str, Any]] = []
    unchanged_count = 0

    if use_numbers:
        matched_ret_nums: set[int] = set()

        for number, orig_item in sorted(orig_by_num.items()):
            ret_item = ret_by_num.get(number)
            if ret_item is None:
                # Same work may still exist under a different number.
                alt = None
                for candidate in numbered_returned:
                    if candidate.number in matched_ret_nums:
                        continue
                    if _same_item(orig_item, candidate):
                        alt = candidate
                        break
                if alt is not None:
                    matched_ret_nums.add(int(alt.number or -1))
                    renumbered.append(
                        {
                            "original": _payload(orig_item),
                            "returned": _payload(alt),
                            "detail": (
                                f"Original [{orig_item.number}] is still present but numbered "
                                f"[{alt.number}] in the returned file."
                            ),
                        }
                    )
                else:
                    removed.append(
                        {
                            "original": _payload(orig_item),
                            "returned": None,
                            "detail": f"[{orig_item.number}] is missing from the returned References.",
                        }
                    )
                continue
            matched_ret_nums.add(number)
            if _same_item(orig_item, ret_item):
                unchanged_count += 1
                continue
            ratio = _similarity(orig_item, ret_item)
            kind = "edited" if ratio >= CHANGED_RATIO else "replaced"
            changed.append(
                {
                    "original": _payload(orig_item),
                    "returned": _payload(ret_item),
                    "detail": (
                        f"[{number}] no longer matches the original reference "
                        f"({kind}, similarity {ratio:.0%})."
                    ),
                    "similarity": round(ratio, 3),
                }
            )

        for number, ret_item in sorted(ret_by_num.items()):
            if number in orig_by_num or number in matched_ret_nums:
                continue
            # Extra number: maybe it is a renamed original already recorded.
            already = any(
                row.get("returned", {}).get("number") == number for row in renumbered if row.get("returned")
            )
            if already:
                continue
            added.append(
                {
                    "original": None,
                    "returned": _payload(ret_item),
                    "detail": f"[{number}] was not in the original References.",
                }
            )

        # Unnumbered leftovers on either side.
        orig_loose = [item for item in original if item.number is None]
        ret_loose = [item for item in returned if item.number is None]
        _match_loose(orig_loose, ret_loose, removed, added, changed, unchanged_count_holder := [])
        unchanged_count += len(unchanged_count_holder)
    else:
        _match_loose(original, returned, removed, added, changed, unchanged_holder := [])
        unchanged_count = len(unchanged_holder)

    orig_order = [item.number for item in numbered_original]
    ret_order = [item.number for item in numbered_returned]
    status = "pass" if not (removed or added or changed or renumbered) else "fail"
    return {
        "status": status,
        "order_changed": bool(orig_order and orig_order != ret_order and status == "pass"),
        "original_count": len(original),
        "returned_count": len(returned),
        "unchanged_count": unchanged_count,
        "removed": removed,
        "added": added,
        "changed": changed,
        "renumbered": renumbered,
        "duplicate_numbers_original": sorted(set(dup_original)),
        "duplicate_numbers_returned": sorted(set(dup_returned)),
        "original_numbers": orig_order,
        "returned_numbers": ret_order,
    }


def _match_loose(
    original: list[ReferenceItem],
    returned: list[ReferenceItem],
    removed: list[dict[str, Any]],
    added: list[dict[str, Any]],
    changed: list[dict[str, Any]],
    unchanged_holder: list[int],
) -> None:
    used: set[int] = set()
    for orig_item in original:
        best_j = -1
        best_ratio = 0.0
        for j, ret_item in enumerate(returned):
            if j in used:
                continue
            ratio = _similarity(orig_item, ret_item)
            if ratio > best_ratio:
                best_ratio = ratio
                best_j = j
        if best_j >= 0 and best_ratio >= SAME_RATIO:
            used.add(best_j)
            unchanged_holder.append(1)
            continue
        if best_j >= 0 and best_ratio >= CHANGED_RATIO:
            used.add(best_j)
            ret_item = returned[best_j]
            changed.append(
                {
                    "original": _payload(orig_item),
                    "returned": _payload(ret_item),
                    "detail": (
                        f"Reference text was edited (similarity {best_ratio:.0%})."
                    ),
                    "similarity": round(best_ratio, 3),
                }
            )
            continue
        removed.append(
            {
                "original": _payload(orig_item),
                "returned": None,
                "detail": "This reference is missing from the returned file.",
            }
        )
    for j, ret_item in enumerate(returned):
        if j in used:
            continue
        added.append(
            {
                "original": None,
                "returned": _payload(ret_item),
                "detail": "This reference was not in the original file.",
            }
        )


def compare_manuscripts(
    original_bytes: bytes,
    returned_bytes: bytes,
    *,
    original_name: str = "original.docx",
    returned_name: str = "returned.docx",
) -> dict[str, Any]:
    orig = extract_references(original_bytes, original_name)
    ret = extract_references(returned_bytes, returned_name)
    comparison = compare_reference_items(orig["items"], ret["items"])
    warnings: list[str] = []
    if not orig["heading_found"]:
        warnings.append(
            "No References heading was found in the original file. "
            "Numbered bibliography lines were used when possible."
        )
    if not ret["heading_found"]:
        warnings.append(
            "No References heading was found in the returned file. "
            "Numbered bibliography lines were used when possible."
        )
    if orig["heading_found"] and not orig["items"]:
        warnings.append("The original References section is empty.")
    if ret["heading_found"] and not ret["items"]:
        warnings.append("The returned References section is empty.")
    if comparison["duplicate_numbers_original"]:
        warnings.append(
            "Original file has duplicate reference numbers: "
            + ", ".join(f"[{n}]" for n in comparison["duplicate_numbers_original"])
        )
    if comparison["duplicate_numbers_returned"]:
        warnings.append(
            "Returned file has duplicate reference numbers: "
            + ", ".join(f"[{n}]" for n in comparison["duplicate_numbers_returned"])
        )

    summary_parts: list[str] = []
    if comparison["status"] == "pass":
        if comparison["order_changed"]:
            summary_parts.append(
                "References match the original. The list order changed, but each number "
                "still points to the same work."
            )
        else:
            summary_parts.append("References match the original file.")
    else:
        if comparison["removed"]:
            summary_parts.append(f"{len(comparison['removed'])} removed")
        if comparison["added"]:
            summary_parts.append(f"{len(comparison['added'])} added")
        if comparison["changed"]:
            summary_parts.append(f"{len(comparison['changed'])} changed")
        if comparison["renumbered"]:
            summary_parts.append(f"{len(comparison['renumbered'])} renumbered")

    return {
        "status": comparison["status"],
        "summary": (
            "; ".join(summary_parts)
            if comparison["status"] == "fail"
            else (summary_parts[0] if summary_parts else "Compared.")
        ),
        "order_changed": comparison["order_changed"],
        "original_count": comparison["original_count"],
        "returned_count": comparison["returned_count"],
        "unchanged_count": comparison["unchanged_count"],
        "removed": comparison["removed"],
        "added": comparison["added"],
        "changed": comparison["changed"],
        "renumbered": comparison["renumbered"],
        "warnings": warnings,
        "original": {
            "filename": original_name,
            "heading": orig["heading"],
            "heading_found": orig["heading_found"],
            "count": len(orig["items"]),
            "items": [item.as_dict() for item in orig["items"]],
        },
        "returned": {
            "filename": returned_name,
            "heading": ret["heading"],
            "heading_found": ret["heading_found"],
            "count": len(ret["items"]),
            "items": [item.as_dict() for item in ret["items"]],
        },
    }
