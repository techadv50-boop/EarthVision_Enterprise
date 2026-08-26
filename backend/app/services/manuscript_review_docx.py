"""Build a Word review file the operator can Accept/Reject in Microsoft Word.

The original DOCX is annotated in place when possible. Each suggestion is a
tracked endnote citation plus a comment with the reason. The endnote *is* the
matching reference. The same archive article is one shared endnote, even if
several paragraphs cite it.
"""

from __future__ import annotations

import io
import re
import zipfile
from datetime import datetime, timezone
from typing import Any, Iterable, Optional
from xml.sax.saxutils import escape

from lxml import etree

from app.services.manuscript_text import paragraph_text

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

AUTHOR = "Citation Assistant"
INITIALS = "CA"


def w(tag: str) -> str:
    return f"{{{W}}}{tag}"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def suggestions_for_review(paragraphs: Iterable[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    """At most one non-rejected suggestion per paragraph; top 10 by score, paragraph order."""
    best: dict[int, dict[str, Any]] = {}
    for para in paragraphs:
        index = int(para.get("index") or 0)
        candidates = [
            dict(s)
            for s in (para.get("suggestions") or [])
            if (s.get("status") or "pending") != "rejected"
        ]
        if not candidates:
            continue
        candidates.sort(key=lambda s: float(s.get("score") or 0), reverse=True)
        best[index] = candidates[0]
    ranked = sorted(best.items(), key=lambda item: (-float(item[1].get("score") or 0), item[0]))
    top = ranked[:10]
    top.sort(key=lambda item: item[0])
    return {index: [sug] for index, sug in top}


def assign_shared_numbers(by_index: dict[int, list[dict[str, Any]]]) -> dict[int, int]:
    """Map article_id → shared reference number in reading order."""
    numbers: dict[int, int] = {}
    for index in sorted(by_index):
        for sug in by_index[index]:
            article_id = int(sug.get("article_id") or 0)
            if article_id and article_id not in numbers:
                numbers[article_id] = len(numbers) + 1
            if article_id:
                sug["citation_number"] = numbers[article_id]
    return numbers


def build_review_docx(
    *,
    title: str,
    paragraphs: list[dict[str, Any]],
    original_docx: Optional[bytes] = None,
) -> bytes:
    stored_texts = [(para.get("text") or "").strip() for para in paragraphs]
    if original_docx and original_docx[:2] == b"PK":
        try:
            return annotate_docx(original_docx, paragraphs)
        except Exception:
            pass
    return annotate_docx(_docx_from_paragraphs(title, stored_texts), paragraphs)


def _map_stored_to_word(doc: etree._Element, stored_texts: list[str]) -> dict[int, etree._Element]:
    targets = [p for p in doc.findall(f".//{w('p')}") if paragraph_text(p)]
    mapping: dict[int, etree._Element] = {}
    if len(targets) == len(stored_texts) and stored_texts:
        return {i: targets[i] for i in range(len(targets))}
    used: set[int] = set()
    for i, text in enumerate(stored_texts):
        key = _norm(text)
        if not key:
            continue
        for j, para in enumerate(targets):
            if j in used:
                continue
            if _norm(paragraph_text(para)) == key:
                mapping[i] = para
                used.add(j)
                break
    return mapping


def annotate_docx(data: bytes, paragraphs: list[dict[str, Any]]) -> bytes:
    files = _read_zip(data)
    if "word/document.xml" not in files:
        raise ValueError("Not a Word document")
    files = _ensure_package(files)

    doc = etree.fromstring(files["word/document.xml"])
    comments_root = _parse_or_create(files.get("word/comments.xml"), "comments")
    endnotes_root = _parse_or_create_endnotes(files.get("word/endnotes.xml"))
    settings_root = _parse_or_create(files.get("word/settings.xml"), "settings")
    _enable_track_revisions(settings_root)

    by_index = suggestions_for_review(paragraphs)
    assign_shared_numbers(by_index)
    stored_texts = [(para.get("text") or "").strip() for para in paragraphs]
    mapping = _map_stored_to_word(doc, stored_texts)
    if by_index and not mapping:
        raise ValueError("Could not map manuscript paragraphs onto the Word file")

    comment_id = _max_id(comments_root, "comment") + 1
    next_endnote_id = max(1, _max_id(endnotes_root, "endnote") + 1)
    rev_id = _max_revision_id(doc) + 1
    stamp = _now()
    article_endnotes: dict[int, int] = {}

    for index in sorted(by_index):
        para = mapping.get(index)
        if para is None:
            continue
        marks: list[tuple[int, int, int]] = []
        for sug in by_index[index]:
            article_id = int(sug.get("article_id") or 0)
            if article_id not in article_endnotes:
                eid = next_endnote_id
                next_endnote_id += 1
                article_endnotes[article_id] = eid
                _append_endnote(
                    endnotes_root,
                    eid,
                    citation=(sug.get("house_citation") or "").strip(),
                    number=int(sug.get("citation_number") or len(article_endnotes)),
                )
            eid = article_endnotes[article_id]
            _append_comment(comments_root, comment_id, stamp, sug=sug)
            marks.append((comment_id, eid, rev_id))
            comment_id += 1
            rev_id += 2
        _mark_paragraph(para, marks=marks, stamp=stamp)

    files["word/document.xml"] = _dumps(doc)
    files["word/comments.xml"] = _dumps(comments_root)
    files["word/endnotes.xml"] = _dumps(endnotes_root)
    files["word/settings.xml"] = _dumps(settings_root)
    files["word/_rels/document.xml.rels"] = _ensure_doc_rels(
        files.get("word/_rels/document.xml.rels", _EMPTY_RELS)
    )
    files["[Content_Types].xml"] = _ensure_content_types(files["[Content_Types].xml"])
    if "word/styles.xml" in files:
        files["word/styles.xml"] = _ensure_styles(files["word/styles.xml"])
    else:
        files["word/styles.xml"] = _STYLES
        files["word/_rels/document.xml.rels"] = _ensure_doc_rels(
            files["word/_rels/document.xml.rels"], extra_styles=True
        )
        files["[Content_Types].xml"] = _ensure_content_types(
            files["[Content_Types].xml"], extra_styles=True
        )
    return _write_zip(files)


def _mark_paragraph(
    para: etree._Element,
    *,
    marks: list[tuple[int, int, int]],
    stamp: str,
) -> None:
    if not marks:
        return
    insert_at = 0
    ppr = para.find(w("pPr"))
    if ppr is not None:
        insert_at = list(para).index(ppr) + 1
    for comment_id, _endnote_id, _rev_id in marks:
        start = etree.Element(w("commentRangeStart"))
        start.set(w("id"), str(comment_id))
        para.insert(insert_at, start)
        insert_at += 1
    for comment_id, endnote_id, rev_id in reversed(marks):
        end = etree.SubElement(para, w("commentRangeEnd"))
        end.set(w("id"), str(comment_id))
        ins = etree.SubElement(para, w("ins"))
        ins.set(w("id"), str(rev_id))
        ins.set(w("author"), AUTHOR)
        ins.set(w("date"), stamp)
        run = etree.SubElement(ins, w("r"))
        rpr = etree.SubElement(run, w("rPr"))
        style = etree.SubElement(rpr, w("rStyle"))
        style.set(w("val"), "EndnoteReference")
        ref = etree.SubElement(run, w("endnoteReference"))
        ref.set(w("id"), str(endnote_id))
        mark = etree.SubElement(para, w("r"))
        mpr = etree.SubElement(mark, w("rPr"))
        mstyle = etree.SubElement(mpr, w("rStyle"))
        mstyle.set(w("val"), "CommentReference")
        cref = etree.SubElement(mark, w("commentReference"))
        cref.set(w("id"), str(comment_id))


def _article_fields(sug: dict[str, Any]) -> dict[str, Any]:
    article = sug.get("article") if isinstance(sug.get("article"), dict) else {}
    authors = sug.get("authors")
    if authors is None:
        authors = article.get("authors") or []
    if isinstance(authors, list):
        names = []
        for item in authors:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict):
                names.append(str(item.get("name") or item))
        author_text = ", ".join(names)
    else:
        author_text = str(authors or "")
    pages = sug.get("page_start") or article.get("page_start")
    page_end = sug.get("page_end") or article.get("page_end")
    page_text = str(pages) if pages is not None else ""
    if page_end:
        page_text = f"{pages}-{page_end}"
    return {
        "title": (sug.get("article_title") or article.get("title") or "").strip(),
        "authors": author_text,
        "journal": (sug.get("journal") or "").strip(),
        "volume": sug.get("volume") if sug.get("volume") is not None else article.get("volume"),
        "issue": sug.get("issue_number") if sug.get("issue_number") is not None else article.get("issue_number"),
        "pages": page_text,
        "doi": (sug.get("doi") or article.get("doi") or "") or "",
    }


def _append_comment(root: etree._Element, cid: int, stamp: str, *, sug: dict[str, Any]) -> None:
    comment = etree.SubElement(root, w("comment"))
    comment.set(w("id"), str(cid))
    comment.set(w("author"), AUTHOR)
    comment.set(w("date"), stamp)
    comment.set(w("initials"), INITIALS)
    fields = _article_fields(sug)
    sid = sug.get("id")
    number = sug.get("citation_number") or ""
    heading = f"Suggestion S-{sid}" if sid is not None else "Suggested citation"
    if fields["title"]:
        heading += f": {fields['title']}"
    reason = (sug.get("reason") or "").strip() or (
        "This paragraph matches an article already stored in the Citation Assistant archive."
    )
    citation = (sug.get("house_citation") or "").strip()
    _add_text_paragraph(comment, heading, bold=True)
    _add_text_paragraph(comment, f"Why this was suggested: {reason}")
    meta = []
    if fields["authors"]:
        meta.append(f"Authors: {fields['authors']}")
    loc_bits = [fields["journal"]] if fields["journal"] else []
    if fields["volume"] is not None:
        loc_bits.append(f"Vol. {fields['volume']}")
    if fields["issue"] is not None:
        loc_bits.append(f"Issue {fields['issue']}")
    if fields["pages"]:
        loc_bits.append(f"pp {fields['pages']}")
    if loc_bits:
        meta.append(" · ".join(str(b) for b in loc_bits if b))
    if fields["doi"]:
        meta.append(f"DOI: {fields['doi']}")
    if meta:
        _add_text_paragraph(comment, " | ".join(meta))
    _add_text_paragraph(comment, f"Reference [{number}]: {citation}".strip())
    _add_text_paragraph(
        comment,
        "In Word open the Review tab. Accept keeps this in-text citation and Reference "
        f"[{number}]. Reject removes this citation. If you reject every citation numbered "
        f"[{number}], also reject that endnote so the reference is not left behind. "
        "The same archive article is never listed twice.",
    )


def _append_endnote(root: etree._Element, eid: int, *, citation: str, number: int) -> None:
    note = etree.SubElement(root, w("endnote"))
    note.set(w("id"), str(eid))
    p = etree.SubElement(note, w("p"))
    ppr = etree.SubElement(p, w("pPr"))
    style = etree.SubElement(ppr, w("pStyle"))
    style.set(w("val"), "EndnoteText")
    marker = etree.SubElement(p, w("r"))
    mpr = etree.SubElement(marker, w("rPr"))
    mstyle = etree.SubElement(mpr, w("rStyle"))
    mstyle.set(w("val"), "EndnoteReference")
    etree.SubElement(marker, w("endnoteRef"))
    _run_text(
        p,
        f" [{number}] {citation}  "
        f"(Shared archive reference. Accept keeps this reference with every matching "
        f"in-text citation [{number}]; reject those citations and this endnote together "
        f"so the reference is not orphaned.)",
    )


def _add_text_paragraph(parent: etree._Element, text: str, *, bold: bool = False) -> None:
    p = etree.SubElement(parent, w("p"))
    run = etree.SubElement(p, w("r"))
    if bold:
        rpr = etree.SubElement(run, w("rPr"))
        etree.SubElement(rpr, w("b"))
    node = etree.SubElement(run, w("t"))
    node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    node.text = text


def _run_text(parent: etree._Element, text: str) -> None:
    run = etree.SubElement(parent, w("r"))
    node = etree.SubElement(run, w("t"))
    node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    node.text = text


def _enable_track_revisions(settings: etree._Element) -> None:
    if settings.find(w("trackRevisions")) is None:
        etree.SubElement(settings, w("trackRevisions"))
    view = settings.find(w("revisionView"))
    if view is None:
        view = etree.SubElement(settings, w("revisionView"))
    view.set(w("markup"), "true")
    view.set(w("comments"), "true")
    view.set(w("insDel"), "true")


def _attr_id(node: etree._Element) -> int:
    raw = node.get(w("id")) or node.get("id") or "0"
    try:
        return int(raw)
    except ValueError:
        return 0


def _max_id(root: etree._Element, local: str) -> int:
    found = 0
    for node in root.findall(w(local)):
        found = max(found, _attr_id(node))
    return found


def _max_revision_id(root: etree._Element) -> int:
    found = 0
    for node in root.iter():
        tag = etree.QName(node).localname
        if tag in {"ins", "del", "comment"}:
            found = max(found, _attr_id(node))
    return found


def _parse_or_create(xml: Optional[bytes], local: str) -> etree._Element:
    if xml:
        try:
            return etree.fromstring(xml)
        except Exception:
            pass
    return etree.fromstring(
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:{local} xmlns:w="{W}"/>'.encode()
    )


def _parse_or_create_endnotes(xml: Optional[bytes]) -> etree._Element:
    if xml:
        try:
            root = etree.fromstring(xml)
            if root.find(w("endnote")) is not None:
                return root
        except Exception:
            pass
    return etree.fromstring(_ENDNOTES_SEED.encode())


def _ensure_package(files: dict[str, bytes]) -> dict[str, bytes]:
    out = dict(files)
    if "[Content_Types].xml" not in out:
        out["[Content_Types].xml"] = _CONTENT_TYPES.encode()
    if "_rels/.rels" not in out:
        out["_rels/.rels"] = _RELS.encode()
    return out


def _ensure_doc_rels(xml: bytes, extra_styles: bool = False) -> bytes:
    try:
        root = etree.fromstring(xml)
    except Exception:
        root = etree.fromstring(_EMPTY_RELS)
    existing = {
        (node.get("Type"), node.get("Target"))
        for node in root.findall(f"{{{REL}}}Relationship")
    }
    wanted = [
        (f"{OFFICE_REL}/comments", "comments.xml"),
        (f"{OFFICE_REL}/endnotes", "endnotes.xml"),
        (f"{OFFICE_REL}/settings", "settings.xml"),
    ]
    if extra_styles:
        wanted.append((f"{OFFICE_REL}/styles", "styles.xml"))
    used = {node.get("Id") for node in root.findall(f"{{{REL}}}Relationship")}
    n = 80
    for typ, target in wanted:
        if (typ, target) in existing:
            continue
        while f"rId{n}" in used:
            n += 1
        rel = etree.SubElement(root, f"{{{REL}}}Relationship")
        rel.set("Id", f"rId{n}")
        rel.set("Type", typ)
        rel.set("Target", target)
        used.add(f"rId{n}")
        n += 1
    return _dumps(root)


def _ensure_content_types(xml: bytes, extra_styles: bool = False) -> bytes:
    try:
        root = etree.fromstring(xml)
    except Exception:
        root = etree.fromstring(_CONTENT_TYPES.encode())
    parts = {
        node.get("PartName")
        for node in root.findall(f"{{{CT}}}Override")
    }
    needed = {
        "/word/comments.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml",
        "/word/endnotes.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.endnotes+xml",
        "/word/settings.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml",
    }
    if extra_styles:
        needed["/word/styles.xml"] = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"
        )
    for part, ctype in needed.items():
        if part in parts:
            continue
        node = etree.SubElement(root, f"{{{CT}}}Override")
        node.set("PartName", part)
        node.set("ContentType", ctype)
    return _dumps(root)


def _ensure_styles(xml: bytes) -> bytes:
    try:
        root = etree.fromstring(xml)
    except Exception:
        return _STYLES.encode()
    ids = {
        node.get(w("styleId"))
        for node in root.findall(w("style"))
    }
    extras = [
        ("commentreference", "character", "CommentReference"),
        ("endnotereference", "character", "EndnoteReference"),
        ("endnotetext", "paragraph", "EndnoteText"),
        ("commenttext", "paragraph", "CommentText"),
    ]
    for sid, kind, name in extras:
        if sid in ids:
            continue
        style = etree.SubElement(root, w("style"))
        style.set(w("type"), kind)
        style.set(w("styleId"), sid)
        nm = etree.SubElement(style, w("name"))
        nm.set(w("val"), name)
    return _dumps(root)


def _docx_from_paragraphs(title: str, paragraphs: list[str]) -> bytes:
    del title  # kept in the API; body paragraphs must stay 1:1 with stored indices
    body = [_p_xml(text or "") for text in paragraphs] or [_p_xml("(Empty manuscript)")]
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}"><w:body>'
        + "".join(body)
        + "</w:body></w:document>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _RELS)
        archive.writestr("word/document.xml", document)
        archive.writestr("word/_rels/document.xml.rels", _EMPTY_RELS.decode())
        archive.writestr("word/styles.xml", _STYLES)
        archive.writestr("word/settings.xml", _SETTINGS)
    return buf.getvalue()


def _p_xml(text: str, *, bold: bool = False, size: int = 24) -> str:
    rpr = f'<w:rPr><w:sz w:val="{size}"/><w:szCs w:val="{size}"/>'
    if bold:
        rpr += "<w:b/>"
    rpr += (
        '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:cs="Times New Roman"/>'
        "</w:rPr>"
    )
    return (
        f"<w:p><w:r>{rpr}"
        f'<w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'
    )


def _read_zip(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _write_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, blob in files.items():
            archive.writestr(name, blob)
    return buf.getvalue()


def _dumps(root: etree._Element) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


_CONTENT_TYPES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="{CT}">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>
</Types>
"""

_RELS = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{REL}">
  <Relationship Id="rId1" Type="{OFFICE_REL}/officeDocument" Target="word/document.xml"/>
</Relationships>
"""

_EMPTY_RELS = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{REL}">
  <Relationship Id="rId1" Type="{OFFICE_REL}/styles" Target="styles.xml"/>
  <Relationship Id="rId2" Type="{OFFICE_REL}/settings" Target="settings.xml"/>
</Relationships>
""".encode()

_SETTINGS = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:settings xmlns:w="{W}">
  <w:trackRevisions/>
  <w:revisionView w:markup="true" w:comments="true" w:insDel="true"/>
</w:settings>
"""

_STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{W}">
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal">
    <w:name w:val="Normal"/>
  </w:style>
  <w:style w:type="character" w:styleId="CommentReference">
    <w:name w:val="Comment Reference"/>
  </w:style>
  <w:style w:type="paragraph" w:styleId="CommentText">
    <w:name w:val="Comment Text"/>
  </w:style>
  <w:style w:type="character" w:styleId="EndnoteReference">
    <w:name w:val="Endnote Reference"/>
  </w:style>
  <w:style w:type="paragraph" w:styleId="EndnoteText">
    <w:name w:val="Endnote Text"/>
  </w:style>
</w:styles>
"""

_ENDNOTES_SEED = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:endnotes xmlns:w="{W}">
  <w:endnote w:type="separator" w:id="-1">
    <w:p><w:r><w:separator/></w:r></w:p>
  </w:endnote>
  <w:endnote w:type="continuationSeparator" w:id="0">
    <w:p><w:r><w:continuationSeparator/></w:r></w:p>
  </w:endnote>
</w:endnotes>
"""
