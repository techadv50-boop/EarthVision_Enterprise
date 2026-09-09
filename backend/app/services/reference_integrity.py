"""Compare References sections of two Word manuscripts.

Reports removed, added, amended, style-only, and place/order changes, plus an
overall summary. Word auto-numbering, Shift+Enter line breaks, and tracked
insertions are read so a real bibliography is not collapsed into one item.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Optional

from app.services.citation_counts import normalize_doi
from app.services.manuscript_text import extract_manuscript_text, extract_review_paragraphs

DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
URL_RE = re.compile(r"https?://[^\s\]>)]+", re.I)
NUMBER_RE = re.compile(
    r"^(?:\[(\d+)\]|\((\d+)\)|(\d{1,3})\s*[\.\)])\s*(.*)$",
    re.S,
)
INLINE_NUM_SPLIT_RE = re.compile(r"(?=\[\d+\])")
NUMBERED_PREFIX_RE = re.compile(
    r"^(?:\d+(?:\.\d+)*|[IVXLCM]+)[\.\)]\s+",
    re.I,
)
AUTHOR_START_RE = re.compile(
    r"^[A-Z][A-Za-z'`.\-]+,\s+[A-Z]",
)
CONTINUATION_START_RE = re.compile(
    r"^(doi\s*:|https?://|www\.|pp\.|vol\.|issue|available|retrieved|in press)",
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
SAME_RATIO = 0.93
STYLE_RATIO = 0.97
CHANGED_RATIO = 0.58


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


def _style_norm(text: str) -> str:
    value = (text or "").lower()
    value = value.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    value = value.replace("&amp;", "&").replace("&", " and ")
    value = URL_RE.sub(" ", value)
    value = re.sub(r"\bdoi:\s*", " ", value)
    value = DOI_RE.sub(" ", value)
    value = re.sub(r"[\[\]\(\)]", " ", value)
    value = re.sub(r"\s+", " ", value).strip().strip(".,;:")
    return value


def _content_norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _style_norm(text)).strip()


def _normalize_body(text: str) -> str:
    return _content_norm(text)


def _fingerprint(body: str, doi: Optional[str]) -> str:
    if doi:
        return f"doi:{doi.lower()}"
    urls = URL_RE.findall(body or "")
    if urls:
        return "url:" + urls[0].rstrip(".,;").lower()
    return "t:" + _content_norm(body)[:280]


def _extract_doi(text: str) -> Optional[str]:
    match = DOI_RE.search(text or "")
    if not match:
        return None
    return normalize_doi(match.group(0))


def paragraphs_from_upload(data: bytes, filename: str = "") -> list[str]:
    name = (filename or "").lower()
    if name.endswith(".docx") or (data[:2] == b"PK" and data[:4] != b"%PDF"):
        paragraphs = extract_review_paragraphs(data)
        if paragraphs:
            return paragraphs
    text = extract_manuscript_text(data, filename)
    return [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def extract_reference_lines(paragraphs: list[str]) -> tuple[list[str], Optional[str], bool]:
    """Return (lines after the References heading, heading text, heading_found)."""
    start = None
    heading = None
    extra: list[str] = []
    for i, para in enumerate(paragraphs):
        first = (para or "").split("\n", 1)[0]
        if is_references_heading(first) or is_references_heading(para):
            start = i + 1
            heading = _compact(first)
            rest = para.split("\n", 1)[1] if "\n" in para and is_references_heading(first) else ""
            if rest.strip():
                extra.append(rest)
            break
    else:
        numbered = [p for p in paragraphs if NUMBER_RE.match(_compact(p.split("\n", 1)[0]))]
        if len(numbered) >= 2:
            return paragraphs, None, False
        return [], None, False

    lines: list[str] = extra
    for para in paragraphs[start:]:
        probe = para.split("\n", 1)[0]
        if _is_stop_heading(probe) and not NUMBER_RE.match(_compact(probe)):
            break
        if para.strip():
            lines.append(para)
    return lines, heading, True


def _looks_like_new_entry(line: str) -> bool:
    compact = line.strip()
    if not compact:
        return False
    if NUMBER_RE.match(compact):
        return True
    if AUTHOR_START_RE.match(compact):
        return True
    if re.match(r"^[A-Z][A-Za-z'`.\-]+(?:\s+[A-Z]\.){0,3},\s+\d{4}", compact):
        return True
    return False


def _looks_like_continuation(line: str) -> bool:
    compact = line.strip()
    if not compact:
        return True
    if CONTINUATION_START_RE.match(compact):
        return True
    if compact[0].islower():
        return True
    if compact.startswith((".", ",", ";", ":")):
        return True
    return False


def _explode_line(line: str) -> list[str]:
    pieces: list[str] = []
    for block in (line or "").split("\n"):
        block = block.strip()
        if not block:
            continue
        if block.count("[") >= 2 and INLINE_NUM_SPLIT_RE.search(block):
            for part in INLINE_NUM_SPLIT_RE.split(block):
                part = part.strip()
                if part:
                    pieces.append(part)
        else:
            pieces.append(block)
    return pieces


def _make_item(number: Optional[int], raw: str, index: int) -> ReferenceItem:
    compact = _compact(raw)
    match = NUMBER_RE.match(compact)
    if match:
        number = int(next(g for g in match.group(1, 2, 3) if g))
        body = (match.group(4) or "").strip()
    else:
        body = compact
    doi = _extract_doi(compact)
    return ReferenceItem(
        number=number,
        body=body,
        raw=compact,
        doi=doi,
        fingerprint=_fingerprint(body, doi),
        index=index,
    )


def parse_reference_items(lines: list[str]) -> list[ReferenceItem]:
    exploded: list[str] = []
    for line in lines:
        exploded.extend(_explode_line(line))

    grouped: list[dict[str, Any]] = []
    current: Optional[dict[str, Any]] = None

    def flush() -> None:
        nonlocal current
        if current:
            grouped.append(current)
            current = None

    for piece in exploded:
        compact = piece.strip()
        if not compact:
            continue
        match = NUMBER_RE.match(_compact(compact))
        new_entry = False
        if match:
            new_entry = True
        elif current is None:
            new_entry = True
        elif _looks_like_new_entry(compact) and not _looks_like_continuation(compact):
            new_entry = True
        elif not _looks_like_continuation(compact) and AUTHOR_START_RE.match(compact):
            new_entry = True

        if new_entry:
            flush()
            number = None
            if match:
                number = int(next(g for g in match.group(1, 2, 3) if g))
            current = {"number": number, "parts": [compact]}
        else:
            if current is None:
                current = {"number": None, "parts": [compact]}
            else:
                current["parts"].append(compact)
    flush()

    items = [
        _make_item(row["number"], " ".join(row["parts"]), i) for i, row in enumerate(grouped)
    ]
    if items and all(item.number is None for item in items):
        for i, item in enumerate(items, start=1):
            item.number = i
            item.raw = f"[{i}] {item.body}".strip()
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


def _similarity(left: ReferenceItem, right: ReferenceItem) -> float:
    if left.doi and right.doi and left.doi.lower() == right.doi.lower():
        return 1.0
    a = _content_norm(left.body)
    b = _content_norm(right.body)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _same_work(left: ReferenceItem, right: ReferenceItem) -> bool:
    return _similarity(left, right) >= SAME_RATIO


def _style_only(left: ReferenceItem, right: ReferenceItem) -> bool:
    if _content_norm(left.body) == _content_norm(right.body):
        return _style_norm(left.body) != _style_norm(right.body)
    ratio = _similarity(left, right)
    if ratio < STYLE_RATIO:
        return False
    return _style_norm(left.body) != _style_norm(right.body)


def _payload(item: Optional[ReferenceItem]) -> Optional[dict[str, Any]]:
    return item.as_dict() if item else None


def _row(
    *,
    original: Optional[ReferenceItem],
    returned: Optional[ReferenceItem],
    detail: str,
    similarity: Optional[float] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "original": _payload(original),
        "returned": _payload(returned),
        "detail": detail,
    }
    if similarity is not None:
        payload["similarity"] = round(similarity, 3)
    return payload


def compare_reference_items(
    original: list[ReferenceItem],
    returned: list[ReferenceItem],
) -> dict[str, Any]:
    used_ret: set[int] = set()
    pairs: list[tuple[ReferenceItem, ReferenceItem, float]] = []
    unmatched_orig: list[ReferenceItem] = []

    for orig_item in original:
        best_j = -1
        best_ratio = 0.0
        for j, ret_item in enumerate(returned):
            if j in used_ret:
                continue
            ratio = _similarity(orig_item, ret_item)
            score = ratio
            if orig_item.doi and ret_item.doi and orig_item.doi.lower() == ret_item.doi.lower():
                score = 1.0
                ratio = 1.0
            if orig_item.number is not None and orig_item.number == ret_item.number:
                score += 0.04
            if score > best_ratio:
                best_ratio = score
                best_j = j
        raw_ratio = _similarity(orig_item, returned[best_j]) if best_j >= 0 else 0.0
        if best_j >= 0 and raw_ratio >= CHANGED_RATIO:
            used_ret.add(best_j)
            pairs.append((orig_item, returned[best_j], raw_ratio))
        else:
            unmatched_orig.append(orig_item)

    unmatched_ret = [item for j, item in enumerate(returned) if j not in used_ret]

    still_orig: list[ReferenceItem] = []
    consumed_ret: set[int] = set()
    for orig_item in unmatched_orig:
        partner = None
        for ret_item in unmatched_ret:
            if id(ret_item) in consumed_ret:
                continue
            if orig_item.number is not None and orig_item.number == ret_item.number:
                partner = ret_item
                break
        if partner is not None:
            consumed_ret.add(id(partner))
            ratio = _similarity(orig_item, partner)
            pairs.append((orig_item, partner, ratio))
        else:
            still_orig.append(orig_item)
    unmatched_orig = still_orig
    unmatched_ret = [item for item in unmatched_ret if id(item) not in consumed_ret]

    removed = [
        _row(
            original=item,
            returned=None,
            detail=f"[{item.number}] is missing from the returned References."
            if item.number is not None
            else "This reference is missing from the returned file.",
        )
        for item in unmatched_orig
    ]
    added = [
        _row(
            original=None,
            returned=item,
            detail=f"[{item.number}] was not in the original References."
            if item.number is not None
            else "This reference was not in the original file.",
        )
        for item in unmatched_ret
    ]
    amended: list[dict[str, Any]] = []
    style_changed: list[dict[str, Any]] = []
    place_changed: list[dict[str, Any]] = []
    unchanged_count = 0

    for orig_item, ret_item, ratio in pairs:
        same_place = orig_item.index == ret_item.index
        same_number = orig_item.number == ret_item.number
        place = (not same_place) or (not same_number)
        if _same_work(orig_item, ret_item):
            if _style_only(orig_item, ret_item):
                style_changed.append(
                    _row(
                        original=orig_item,
                        returned=ret_item,
                        detail=(
                            f"[{orig_item.number}] is the same work; only style / punctuation / "
                            f"spacing differs."
                        ),
                        similarity=ratio,
                    )
                )
            else:
                unchanged_count += 1
            if place:
                bits = []
                if not same_number:
                    bits.append(f"number [{orig_item.number}] → [{ret_item.number}]")
                if not same_place:
                    bits.append(f"list place {orig_item.index + 1} → {ret_item.index + 1}")
                place_changed.append(
                    _row(
                        original=orig_item,
                        returned=ret_item,
                        detail="Same reference, " + ", ".join(bits) + ".",
                        similarity=ratio,
                    )
                )
            continue
        kind = "amended" if ratio >= CHANGED_RATIO else "replaced"
        amended.append(
            _row(
                original=orig_item,
                returned=ret_item,
                detail=(
                    f"[{orig_item.number}] was {kind} (similarity {ratio:.0%}). "
                    "Bibliographic content no longer matches the original."
                ),
                similarity=ratio,
            )
        )
        if place:
            place_changed.append(
                _row(
                    original=orig_item,
                    returned=ret_item,
                    detail="This amended reference also moved in the list.",
                    similarity=ratio,
                )
            )

    orig_order = [item.number for item in original]
    ret_order = [item.number for item in returned]
    if removed or added or amended:
        status = "fail"
    elif style_changed or place_changed:
        status = "warn"
    else:
        status = "pass"

    return {
        "status": status,
        "order_changed": bool(place_changed),
        "original_count": len(original),
        "returned_count": len(returned),
        "unchanged_count": unchanged_count,
        "removed": removed,
        "added": added,
        "changed": amended,
        "amended": amended,
        "style_changed": style_changed,
        "place_changed": place_changed,
        "renumbered": [
            row
            for row in place_changed
            if (row.get("original") or {}).get("number") != (row.get("returned") or {}).get("number")
        ],
        "duplicate_numbers_original": _duplicates(original),
        "duplicate_numbers_returned": _duplicates(returned),
        "original_numbers": orig_order,
        "returned_numbers": ret_order,
    }


def _duplicates(items: list[ReferenceItem]) -> list[int]:
    seen: set[int] = set()
    dups: list[int] = []
    for item in items:
        if item.number is None:
            continue
        if item.number in seen:
            dups.append(item.number)
        seen.add(item.number)
    return sorted(set(dups))


def _overall(comparison: dict[str, Any]) -> dict[str, Any]:
    counts = {
        "original": comparison["original_count"],
        "returned": comparison["returned_count"],
        "unchanged": comparison["unchanged_count"],
        "removed": len(comparison["removed"]),
        "added": len(comparison["added"]),
        "amended": len(comparison["amended"]),
        "style_changed": len(comparison["style_changed"]),
        "place_changed": len(comparison["place_changed"]),
    }
    lines: list[str] = [
        f"Original list: {counts['original']} references. Returned list: {counts['returned']}.",
        f"Unchanged: {counts['unchanged']}.",
        f"Removed: {counts['removed']}. Newly added: {counts['added']}.",
        f"Amended (content): {counts['amended']}. Style only: {counts['style_changed']}.",
        f"Place / order / number moved: {counts['place_changed']}.",
    ]
    if comparison["status"] == "pass":
        verdict = "Overall: the References section matches the original file."
    elif comparison["status"] == "warn":
        verdict = (
            "Overall: every original work is still present, but style and/or place changed. "
            "Review the sections below before accepting the file."
        )
    else:
        verdict = (
            "Overall: the returned References section does not match the original. "
            "See removed, added, and amended items below."
        )
    return {**counts, "verdict": verdict, "lines": lines}


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
    if orig["heading_found"] and len(orig["items"]) <= 1 and orig["paragraph_count"] > 8:
        warnings.append(
            "Only one original reference was parsed. If the Word file uses an unusual layout, "
            "the bibliography may not have been split correctly."
        )
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

    overall = _overall(comparison)
    return {
        "status": comparison["status"],
        "summary": overall["verdict"],
        "overall": overall,
        "order_changed": comparison["order_changed"],
        "original_count": comparison["original_count"],
        "returned_count": comparison["returned_count"],
        "unchanged_count": comparison["unchanged_count"],
        "removed": comparison["removed"],
        "added": comparison["added"],
        "changed": comparison["changed"],
        "amended": comparison["amended"],
        "style_changed": comparison["style_changed"],
        "place_changed": comparison["place_changed"],
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
