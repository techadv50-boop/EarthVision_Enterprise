"""Build a Word file the operator can Accept/Reject in Microsoft Word.

Each suggested citation is a tracked insertion of an endnote. The endnote *is*
the matching reference, so Rejecting the citation also drops that reference.
A comment on the same paragraph explains why it was suggested.
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone
from typing import Any, Iterable, Optional
from xml.sax.saxutils import escape

from lxml import etree

from app.services.manuscript_text import extract_docx_paragraphs, paragraph_text

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


def best_suggestion_by_index(paragraphs: Iterable[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """One surviving suggestion per paragraph (highest score, not rejected)."""
    picked: dict[int, dict[str, Any]] = {}
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
        picked[index] = candidates[0]
    return picked


def build_review_docx(
    *,
    title: str,
    paragraphs: list[dict[str, Any]],
    original_docx: Optional[bytes] = None,
) -> bytes:
    picks = best_suggestion_by_index(paragraphs)
    stored_texts = [(para.get("text") or "").strip() for para in paragraphs]
    if original_docx and original_docx[:2] == b"PK":
        try:
            live = extract_docx_paragraphs(original_docx)
            if live and len(live) == len(stored_texts):
                return annotate_docx(original_docx, picks)
        except Exception:
            pass
    return annotate_docx(_docx_from_paragraphs(title, stored_texts), picks)


def annotate_docx(data: bytes, suggestions_by_index: dict[int, dict[str, Any]]) -> bytes:
    files = _read_zip(data)
    if "word/document.xml" not in files:
        raise ValueError("Not a Word document")
    files = _ensure_package(files)

    doc = etree.fromstring(files["word/document.xml"])
    comments_root = _parse_or_create(files.get("word/comments.xml"), "comments")
    endnotes_root = _parse_or_create_endnotes(files.get("word/endnotes.xml"))
    settings_root = _parse_or_create(files.get("word/settings.xml"), "settings")
    _enable_track_revisions(settings_root)

    comment_id = _max_id(comments_root, "comment") + 1
    endnote_id = max(1, _max_id(endnotes_root, "endnote") + 1)
    rev_id = _max_revision_id(doc) + 1
    stamp = _now()

    targets = [p for p in doc.findall(f".//{w('p')}") if paragraph_text(p)]
    for index, para in enumerate(targets):
        sug = suggestions_by_index.get(index)
        if not sug:
            continue
        reason = (sug.get("reason") or "").strip() or "This paragraph matches an article in the journal archive."
        citation = (sug.get("house_citation") or "").strip() or (sug.get("reason") or "").strip()
        title = ""
        article = sug.get("article") or {}
        if isinstance(article, dict):
            title = (article.get("title") or "").strip()

        _append_comment(comments_root, comment_id, stamp, title=title, reason=reason, citation=citation)
        _append_endnote(endnotes_root, endnote_id, stamp, reason=reason, citation=citation)
        _mark_paragraph(para, comment_id=comment_id, endnote_id=endnote_id, rev_id=rev_id, stamp=stamp)
        comment_id += 1
        endnote_id += 1
        rev_id += 2

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


def _mark_paragraph(para: etree._Element, *, comment_id: int, endnote_id: int, rev_id: int, stamp: str) -> None:
    start = etree.Element(w("commentRangeStart"))
    start.set(w("id"), str(comment_id))
    insert_at = 0
    ppr = para.find(w("pPr"))
    if ppr is not None:
        insert_at = list(para).index(ppr) + 1
    para.insert(insert_at, start)

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


def _append_comment(root: etree._Element, cid: int, stamp: str, *, title: str, reason: str, citation: str) -> None:
    comment = etree.SubElement(root, w("comment"))
    comment.set(w("id"), str(cid))
    comment.set(w("author"), AUTHOR)
    comment.set(w("date"), stamp)
    comment.set(w("initials"), INITIALS)
    heading = f"Suggested citation: {title}" if title else "Suggested citation"
    _add_text_paragraph(comment, heading, bold=True)
    _add_text_paragraph(comment, f"Why this was suggested: {reason}")
    _add_text_paragraph(comment, f"Reference (endnote): {citation}")
    _add_text_paragraph(
        comment,
        "In Word open the Review tab. Accept keeps this citation and its matching reference. "
        "Reject removes both.",
    )


def _append_endnote(root: etree._Element, eid: int, stamp: str, *, reason: str, citation: str) -> None:
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
    _run_text(p, f" {citation}  Why this was suggested: {reason}  "
             f"(Accept keeps this reference with the in-text citation; Reject drops both.)")


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
