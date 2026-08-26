"""Manuscript suggestion policy: max 10 per manuscript, one per paragraph."""

from __future__ import annotations

import io
from xml.sax.saxutils import escape
import zipfile

import pytest
from httpx import AsyncClient

from app.services.matcher import (
    RankedCandidate,
    is_substantive_paragraph,
    one_per_paragraph,
    passes_relevance_gate,
    select_manuscript_matches,
)
from app.services.manuscript_review_docx import suggestions_for_review
from tests.test_citation_parser import GALLEY_WATER


def _cand(paragraph_id: int, index: int, score: float, article_id: int = 1) -> RankedCandidate:
    return RankedCandidate(
        paragraph_index=index,
        paragraph_id=paragraph_id,
        article_id=article_id,
        score=score,
        chunk_text="",
        article=None,
        chunk=None,
    )


def test_is_substantive_skips_title_heading_authors_and_bibliography():
    body = (
        "This manuscript reviews drinking water contamination and Water Quality Index "
        "modelling for groundwater in rural Sindh and Khairpur."
    )
    assert is_substantive_paragraph(body, index=2) is True
    assert is_substantive_paragraph("Introduction") is False
    assert is_substantive_paragraph("1. Materials and Methods") is False
    assert is_substantive_paragraph("References") is False
    assert is_substantive_paragraph("[1] Ali, A. (2026). Water quality. IJIST.") is False
    assert (
        is_substantive_paragraph(
            "Integrated Source Tracking of Drinking Water Contamination",
            index=0,
        )
        is False
    )
    assert is_substantive_paragraph("*Correspondence: asimali@bbsutsd.edu.pk") is False
    assert is_substantive_paragraph("1 Department of Civil Engineering, University of Sindh") is False
    assert is_substantive_paragraph("Short note.") is False
    assert is_substantive_paragraph(body, index=4, in_references=True) is False
    truncated_first = (
        "This manuscript reviews drinking water contamination, Water Quality Index (WQI) and SPI modell"
    )
    assert is_substantive_paragraph(truncated_first, index=0) is True


def test_weak_matches_are_excluded_by_relevance_gate():
    assert passes_relevance_gate(0.10, ["water"]) is False
    assert passes_relevance_gate(0.20, []) is False
    assert passes_relevance_gate(0.20, ["water", "contamination"]) is True
    assert passes_relevance_gate(0.30, []) is True


def test_duplicate_suggestions_for_same_paragraph_keep_highest_score():
    matches = [
        _cand(1, 0, 0.40, article_id=11),
        _cand(1, 0, 0.72, article_id=12),
        _cand(1, 0, 0.55, article_id=13),
        _cand(2, 1, 0.60, article_id=14),
    ]
    unique = one_per_paragraph(matches)
    by_para = {item.paragraph_id: item for item in unique}
    assert len(unique) == 2
    assert by_para[1].article_id == 12
    assert by_para[1].score == 0.72
    assert by_para[2].article_id == 14


def test_select_manuscript_matches_keeps_top_10_by_score_in_paragraph_order():
    matches = [_cand(i, i, 0.20 + (i * 0.01), article_id=100 + i) for i in range(20)]
    selected = select_manuscript_matches(matches, limit=10)
    assert len(selected) == 10
    assert [item.paragraph_index for item in selected] == list(range(10, 20))
    assert [item.score for item in selected] == [0.20 + (i * 0.01) for i in range(10, 20)]
    assert all(item.score >= 0.30 for item in selected)


def test_suggestions_for_review_one_per_paragraph_and_top_10():
    paragraphs = []
    for i in range(15):
        paragraphs.append(
            {
                "index": i,
                "text": f"Paragraph {i} body.",
                "suggestions": [
                    {"id": i * 10 + 1, "score": 0.20 + i * 0.01, "status": "pending", "article_id": i},
                    {"id": i * 10 + 2, "score": 0.10, "status": "pending", "article_id": 999},
                ],
            }
        )
    picked = suggestions_for_review(paragraphs)
    assert len(picked) == 10
    assert all(len(items) == 1 for items in picked.values())
    assert list(picked) == sorted(picked)
    assert list(picked) == list(range(5, 15))
    assert picked[14][0]["article_id"] == 14
    assert picked[14][0]["id"] == 141


async def _auth(client: AsyncClient) -> dict[str, str]:
    response = await client.post("/api/v1/auth/login", json={"username": "demo", "password": "Demo@123456"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _docx_from_paragraphs(*texts: str) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p>" for text in texts)
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("word/document.xml", document)
    return buf.getvalue()


def _topic_galley(n: int) -> str:
    word = f"Xenon{n}ology"
    title = f"Advances in {word} Measurement Techniques for Field Sensors"
    page = 4000 + n
    abstract = (
        f"This paper presents a calibrated {word} survey of groundwater sensors, "
        f"including {word} drift correction and {word} mapping in arid basins. " * 4
    )
    return f"""International Journal of Innovations in Science & Technology
August 2026|Vol 8 | Issue 5 \tPage |{page}
{title}
Pat Researcher1
*Correspondence: pat{n}@example.com
Citation| Researcher. P, “{title}”, IJIST, Vol. 8 Issue. 5 pp {page}-{page + 2}, August 2026
Received| July 01, 2026 Revised| July 15, 2026 Accepted| July 20, 2026 Published| Aug 01, 2026.
{abstract}
Keywords: {word}; Remote Sensing; Calibration
"""


def _topic_paragraph(n: int) -> str:
    word = f"Xenon{n}ology"
    return (
        f"Field teams recorded {word} measurements across the basin and applied {word} "
        f"drift correction so the operational {word} maps could be used in arid regions."
    )


@pytest.mark.asyncio
async def test_manuscript_keeps_top_10_suggestions_one_per_paragraph(client: AsyncClient):
    headers = await _auth(client)
    created = await client.post(
        "/api/v1/journals",
        headers=headers,
        json={"name": "Top Ten Journal", "abbreviation": "TTJ"},
    )
    jid = created.json()["id"]
    article_ids = []
    for n in range(22):
        paper = await client.post(
            f"/api/v1/journals/{jid}/papers-text",
            headers=headers,
            json={"filename": f"xenon-{n}.txt", "text": _topic_galley(n)},
        )
        assert paper.status_code == 200, paper.text
        article_ids.append(paper.json()["article"]["id"])

    paragraphs = [
        "A Compact Title Without Sentence Punctuation About Xenon Sensors",
        "Introduction",
        "Pat Researcher",
        "*Correspondence: pat@example.com",
        *[ _topic_paragraph(n) for n in range(22) ],
        "References",
        "[1] Researcher, P. (2026). Advances in Xenon0ology. IJIST.",
        GALLEY_WATER.strip().splitlines()[0],
    ]
    up = await client.post(
        "/api/v1/manuscripts",
        headers=headers,
        files={
            "file": (
                "many.docx",
                _docx_from_paragraphs(*paragraphs),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert up.status_code == 201, up.text
    mid = up.json()["id"]
    sug = await client.post(f"/api/v1/manuscripts/{mid}/suggest", headers=headers)
    assert sug.status_code == 200, sug.text
    assert sug.json()["suggestion_count"] <= 10
    detail = (await client.get(f"/api/v1/manuscripts/{mid}", headers=headers)).json()
    sugs = [s for p in detail["paragraphs"] for s in p["suggestions"]]
    assert 1 <= len(sugs) <= 10
    assert len(sugs) == sug.json()["suggestion_count"]
    for para in detail["paragraphs"]:
        assert len(para["suggestions"]) <= 1
    annotated = [
        (para["index"], para["suggestions"][0]["score"])
        for para in detail["paragraphs"]
        if para["suggestions"]
    ]
    assert [item[0] for item in annotated] == sorted(item[0] for item in annotated)
    stored_ids = {s["article_id"] for s in sugs}
    assert stored_ids <= set(article_ids)
    for s in sugs:
        assert s["reason"]
        assert s.get("journal") or s.get("article_title")
        stored = await client.get(f"/api/v1/articles/{s['article_id']}", headers=headers)
        assert stored.status_code == 200

    exported = await client.get(f"/api/v1/manuscripts/{mid}/export", headers=headers)
    assert exported.status_code == 200
    zipped = zipfile.ZipFile(io.BytesIO(exported.content))
    document = zipped.read("word/document.xml").decode()
    comments = zipped.read("word/comments.xml").decode()
    endnotes = zipped.read("word/endnotes.xml").decode()
    assert document.count("endnoteReference") <= 10
    assert "Why this was suggested" in comments
    assert "Accept" in comments and "Reject" in comments
    assert "Shared archive reference" in endnotes
    assert "ins" in document
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    from lxml import etree

    doc = etree.fromstring(zipped.read("word/document.xml"))
    refs = doc.findall(".//w:endnoteReference", ns)
    assert 1 <= len(refs) <= 10
    for s in sugs:
        acc = await client.patch(
            f"/api/v1/suggestions/{s['id']}",
            headers=headers,
            json={"status": "rejected"},
        )
        assert acc.status_code == 200
    exported2 = await client.get(f"/api/v1/manuscripts/{mid}/export", headers=headers)
    doc2 = etree.fromstring(zipfile.ZipFile(io.BytesIO(exported2.content)).read("word/document.xml"))
    assert doc2.findall(".//w:endnoteReference", ns) == []
    assert "xenon0ology" in etree.tostring(doc2).decode().lower()
