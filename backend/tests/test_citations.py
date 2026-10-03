"""API tests for journal archive ingest, coverage gaps, matching, and crawler."""

from __future__ import annotations

import io
import re

import pytest
from httpx import AsyncClient
from reportlab.pdfgen import canvas

from tests.test_citation_parser import GALLEY_EDDSA, GALLEY_FCSI, GALLEY_WATER
from app.services.citation_counts import normalize_doi
from xml.sax.saxutils import escape
import zipfile


def test_normalize_doi():
    assert normalize_doi("https://doi.org/10.33411/IJIST/20190101011") == "10.33411/IJIST/20190101011"
    assert normalize_doi("doi:10.33411/IJIST/20190101011") == "10.33411/IJIST/20190101011"


def test_unique_pdfs_by_article_keeps_one_galley():
    from app.services.crawler import _unique_pdfs_by_article as unique_pdfs

    urls = [
        "https://example.test/article/view/9/11",
        "https://example.test/article/download/9/11",
        "https://example.test/article/view/9",
        "https://example.test/article/view/10/12",
        "https://files.example.test/extra.pdf",
    ]
    out = unique_pdfs(urls)
    assert out.count("https://example.test/article/download/9/11") == 1
    assert not any(item.endswith("/view/9/11") for item in out)
    assert "https://example.test/article/view/10/12" in out
    assert "https://files.example.test/extra.pdf" in out
    assert len(out) == 3


def test_article_page_pdfs_ignore_related_links():
    from app.services.crawler import _pdfs_for_article as pdfs_for_article

    html = """
    <html>
      <meta name="citation_pdf_url" content="https://example.test/article/download/12/30">
      <a href="https://example.test/article/view/99">Related</a>
      <a href="https://example.test/article/view/99/1">PDF</a>
      <a href="https://example.test/article/view/12/31">PDF</a>
    </html>
    """
    pdfs = pdfs_for_article(html, "https://example.test/article/view/12", "12")
    assert "https://example.test/article/download/12/30" in pdfs
    assert any(item.endswith("/view/12/31") for item in pdfs)
    assert not any("/view/99" in item for item in pdfs)


def test_citing_record_from_crossref():
    from app.services.citation_counts import citing_record_from_crossref

    row = citing_record_from_crossref(
        {
            "DOI": "10.1007/s00500-022-06794-6",
            "title": ["A citing article about heat islands"],
            "author": [{"given": "Jane", "family": "Doe"}],
            "container-title": ["Soft Computing"],
            "published-print": {"date-parts": [[2022, 3]]},
            "URL": "https://doi.org/10.1007/s00500-022-06794-6",
        }
    )
    assert row["source"] == "crossref"
    assert row["year"] == 2022
    assert row["venue"] == "Soft Computing"
    assert "Jane Doe" in row["authors"]
    assert row["doi"] == "10.1007/s00500-022-06794-6"


def test_merge_citing_works_dedupes_within_crossref_and_keeps_scholar_separate():
    from app.services.citation_counts import _citing_record, merge_citing_works

    merged = merge_citing_works(
        [
            _citing_record(
                source="crossref",
                title="Same paper",
                doi="10.1/abc",
                authors="CR Author",
                year=2022,
                venue="Soft Computing",
            ),
            _citing_record(
                source="crossref",
                title="Same paper.",
                doi="10.1/ABC",
                authors="",
                year=2022,
            ),
            _citing_record(source="crossref", title="Only Crossref", doi="10.cr/1", year=2023),
            _citing_record(source="openalex", title="Same paper", doi="10.1/abc", authors="OA Only"),
            _citing_record(source="openalex", title="Only OpenAlex", doi="10.oa/1", year=2024),
        ],
        [
            _citing_record(
                source="scholar",
                title="Same paper",
                doi="10.1/abc",
                authors="Scholar Author",
                year=2022,
            ),
            _citing_record(source="scholar", title="Same paper", doi="10.1/abc"),
        ],
    )
    crossref = [row for row in merged if row["source"] == "crossref"]
    scholar = [row for row in merged if row["source"] == "scholar"]
    assert [row["doi"] for row in crossref] == ["10.cr/1", "10.1/abc"]
    assert [row["doi"] for row in scholar] == ["10.1/abc"]
    assert all(row["source"] == "crossref" for row in crossref)
    assert all(row["source"] == "scholar" for row in scholar)
    assert not any("openalex" in (row["source"] or "") for row in merged)
    same = next(row for row in crossref if row["doi"] == "10.1/abc")
    assert same["venue"] == "Soft Computing"
    assert same["authors"] == "CR Author"


def test_dedupe_citing_works_collapses_title_only_duplicate():
    from app.services.citation_counts import _citing_record, dedupe_citing_works

    rows = dedupe_citing_works(
        [
            _citing_record(source="crossref", title="Heat Island Study", doi="10.1/keep", year=2021),
            _citing_record(source="crossref", title="Heat Island Study!"),
            _citing_record(source="crossref", title="A different citing paper"),
        ],
        source="crossref",
    )
    titles = [row["title"] for row in rows]
    assert titles.count("Heat Island Study") == 1
    assert "A different citing paper" in titles


@pytest.mark.asyncio
async def test_fetch_citing_works_does_not_use_openalex(monkeypatch):
    from types import SimpleNamespace

    from app.services import citation_counts as counts_mod

    async def fake_crossref(_client, doi):
        assert doi == "10.33411/ijist/20190101011"
        return [
            counts_mod._citing_record(
                source="crossref",
                title="Crossref citing article",
                doi="10.1007/s00500-022-06794-6",
                year=2022,
                venue="Soft Computing",
            ),
            counts_mod._citing_record(
                source="crossref",
                title="Crossref citing article",
                doi="10.1007/s00500-022-06794-6",
            ),
        ]

    async def fake_scholar(_article):
        return [
            counts_mod._citing_record(
                source="scholar",
                title="Scholar citing article",
                url="https://scholar.google.com/scholar?q=cite",
                year=2024,
            )
        ]

    monkeypatch.setattr(counts_mod, "_fetch_crossref_citing_works", fake_crossref)
    monkeypatch.setattr(counts_mod, "_fetch_scholar_citing_works", fake_scholar)

    rows = await counts_mod.fetch_citing_works(
        SimpleNamespace(
            doi="10.33411/ijist/20190101011",
            title="Urban Heat Island",
            scholar_url="https://scholar.google.com/scholar?cites=123",
        )
    )
    assert [row["source"] for row in rows] == ["crossref", "scholar"]
    assert rows[0]["doi"] == "10.1007/s00500-022-06794-6"
    assert rows[1]["title"] == "Scholar citing article"
    source = __import__("inspect").getsource(counts_mod.fetch_citing_works)
    assert "openalex.org" not in source.lower()
    assert "OPENALEX" not in source
    source_file = __import__("inspect").getsource(counts_mod)
    assert "api.openalex.org" not in source_file


def test_parse_scholar_citing_html_reads_results_once():
    from app.services.citation_counts import parse_scholar_citing_html

    html = """
    <div class="gs_ri">
      <h3 class="gs_rt"><a href="https://doi.org/10.1007/cite">A <b>citing</b> article</a></h3>
      <div class="gs_a">Jane Doe - Soft Computing, 2022 - Springer</div>
    </div>
    <div class="gs_ri">
      <h3 class="gs_rt"><a href="https://doi.org/10.1007/cite">A citing article</a></h3>
      <div class="gs_a">Jane Doe - Soft Computing, 2022 - Springer</div>
    </div>
    """
    rows = parse_scholar_citing_html(html)
    assert len(rows) == 1
    assert rows[0]["source"] == "scholar"
    assert rows[0]["title"] == "A citing article"
    assert rows[0]["year"] == 2022
    assert "Jane Doe" in rows[0]["authors"]
    assert rows[0]["doi"] == "10.1007/cite"


def test_citing_dois_from_opencitations():
    from app.services.citation_counts import _citing_dois_from_opencitations

    dois = _citing_dois_from_opencitations(
        [
            {"citing": "10.1007/s00500-022-06794-6", "cited": "10.33411/ijist/20190101011"},
            {"citing": "doi:10.1007/s00500-022-06794-6", "cited": "10.33411/ijist/20190101011"},
        ]
    )
    assert dois == ["10.1007/s00500-022-06794-6"]


def _pdf_from_text(text: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    y = 800
    for line in text.strip().splitlines():
        c.drawString(40, y, line[:110])
        y -= 14
        if y < 40:
            c.showPage()
            y = 800
    c.save()
    return buf.getvalue()


async def _auth(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "citation@xdgen.com", "password": "pak123"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.asyncio
async def test_journal_ingest_coverage_and_match(client: AsyncClient):
    headers = await _auth(client)
    created = await client.post(
        "/api/v1/journals",
        headers=headers,
        json={
            "name": "International Journal of Innovations in Science & Technology",
            "abbreviation": "IJIST",
            "publisher": "50Sea",
        },
    )
    assert created.status_code == 201, created.text
    jid = created.json()["id"]

    a1 = await client.post(
        f"/api/v1/journals/{jid}/papers-text",
        headers=headers,
        json={"filename": "eddsa.txt", "text": GALLEY_EDDSA},
    )
    assert a1.status_code == 200, a1.text
    a2 = await client.post(
        f"/api/v1/journals/{jid}/papers-text",
        headers=headers,
        json={"filename": "water.txt", "text": GALLEY_WATER},
    )
    assert a2.status_code == 200, a2.text

    listing = await client.get("/api/v1/journals", headers=headers)
    assert listing.status_code == 200
    row = next(j for j in listing.json() if j["id"] == jid)
    assert row["article_count"] == 2
    assert row["volume_count"] >= 1

    vols = await client.get(f"/api/v1/journals/{jid}/volumes", headers=headers)
    assert vols.status_code == 200
    vol8 = next(v for v in vols.json() if v["volume"] == 8)
    assert vol8["article_count"] == 2

    issues = await client.get(f"/api/v1/journals/{jid}/volumes/8/issues", headers=headers)
    assert issues.status_code == 200
    iss5 = next(i for i in issues.json() if i["issue_number"] == 5)
    assert iss5["article_count"] == 2

    arts = await client.get(
        f"/api/v1/journals/{jid}/volumes/8/issues/5/articles", headers=headers
    )
    assert arts.status_code == 200
    payload = arts.json()
    gaps = payload["coverage"]["gaps"]
    assert any(g["page_start"] == 1814 and g["page_end"] == 2210 for g in gaps)
    titles = {a["title"] for a in payload["articles"]}
    assert any("Digital Signature" in t for t in titles)
    assert any("Drinking Water" in t for t in titles)

    pdf = _pdf_from_text(
        "Introduction\n"
        "This manuscript reviews drinking water contamination, Water Quality Index (WQI) "
        "and SPI modelling for groundwater in rural Sindh and Khairpur.\n"
        "Materials and Methods\n"
        "Field teams sampled groundwater in rural Sindh and calibrated WQI and SPI models.\n"
        "Results\n"
        "The results should not receive archive citation suggestions."
    )
    up = await client.post(
        "/api/v1/manuscripts",
        headers=headers,
        files={"file": ("ms.pdf", pdf, "application/pdf")},
    )
    assert up.status_code == 201, up.text
    mid = up.json()["id"]
    sug = await client.post(f"/api/v1/manuscripts/{mid}/suggest", headers=headers)
    assert sug.status_code == 200, sug.text
    detail = await client.get(f"/api/v1/manuscripts/{mid}", headers=headers)
    assert detail.status_code == 200
    body = detail.json()
    reasons = " ".join(
        s["reason"] + " " + (s.get("article") or {}).get("title", "")
        for p in body["paragraphs"]
        for s in p["suggestions"]
    )
    assert "Drinking Water" in reasons or "Water" in reasons

    pdf2 = _pdf_from_text(
        "Introduction\n"
        "This manuscript proposes an EdDSA watermarking scheme for digital document "
        "authentication and tamper detection using Edward curve signatures.\n"
        "Materials and Methods\n"
        "The EdDSA watermarking pipeline signs each document page before embedding.\n"
        "Results\n"
        "The signature scheme results are reported separately."
    )
    up2 = await client.post(
        "/api/v1/manuscripts",
        headers=headers,
        files={"file": ("eddsa-ms.pdf", pdf2, "application/pdf")},
    )
    assert up2.status_code == 201, up2.text
    mid2 = up2.json()["id"]
    sug2 = await client.post(f"/api/v1/manuscripts/{mid2}/suggest", headers=headers)
    assert sug2.status_code == 200, sug2.text
    detail2 = (await client.get(f"/api/v1/manuscripts/{mid2}", headers=headers)).json()
    reasons2 = " ".join(
        s["reason"] + " " + (s.get("article") or {}).get("title", "")
        for p in detail2["paragraphs"]
        for s in p["suggestions"]
    )
    assert "Digital Signature" in reasons2 or "EDDSA" in reasons2 or "Watermark" in reasons2

    search = await client.get("/api/v1/archive/search", headers=headers, params={"q": "watermarking"})
    assert search.status_code == 200
    assert search.json()["count"] >= 1


def _docx_from_text(text: str) -> bytes:
    return _docx_from_paragraphs(text)


def _docx_from_paragraphs(*texts: str) -> bytes:
    body = "".join(
        f"<w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p>" for text in texts
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("word/document.xml", document)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_word_manuscript_suggest_and_delete(client: AsyncClient):
    headers = await _auth(client)
    created = await client.post(
        "/api/v1/journals",
        headers=headers,
        json={"name": "Word Suggestion Journal", "abbreviation": "WSJ"},
    )
    jid = created.json()["id"]
    paper = await client.post(
        f"/api/v1/journals/{jid}/papers-text",
        headers=headers,
        json={"filename": "water.txt", "text": GALLEY_WATER},
    )
    assert paper.status_code == 200, paper.text
    archive_id = paper.json()["article"]["id"]
    docx = _docx_from_paragraphs(
        "Introduction",
        "This manuscript reviews drinking water contamination, Water Quality Index (WQI) "
        "and SPI modelling for groundwater in rural Sindh and Khairpur.",
        "Materials and Methods",
        "Groundwater samples from rural Sindh and Khairpur were analysed with WQI and SPI models.",
        "Results",
        "These result tables about drinking water must not receive a citation.",
        "References",
    )
    up = await client.post(
        "/api/v1/manuscripts",
        headers=headers,
        files={
            "file": (
                "water-review.docx",
                docx,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert up.status_code == 201, up.text
    mid = up.json()["id"]
    sug = await client.post(f"/api/v1/manuscripts/{mid}/suggest", headers=headers)
    assert sug.status_code == 200, sug.text
    detail = (await client.get(f"/api/v1/manuscripts/{mid}", headers=headers)).json()
    blob = " ".join(
        s["reason"] + " " + (s.get("article") or {}).get("title", "")
        for p in detail["paragraphs"]
        for s in p["suggestions"]
    )
    assert "Water" in blob or "Drinking" in blob
    first = next(s for p in detail["paragraphs"] for s in p["suggestions"])
    assert first["article_id"]
    assert first["reason"]
    assert "related to your paragraph" not in first["reason"].lower()
    assert "directly supports" in first["reason"] or "semantically aligned" in first["reason"] or "discusses" in first["reason"]
    assert first.get("journal")
    assert first.get("volume") is not None
    assert first.get("article_title")
    for p in detail["paragraphs"]:
        assert len(p["suggestions"]) <= 1
        if (p.get("text") or "").startswith("These result tables"):
            assert p["suggestions"] == []
        for s in p["suggestions"]:
            stored = await client.get(f"/api/v1/articles/{s['article_id']}", headers=headers)
            assert stored.status_code == 200
            assert stored.json()["id"] == s["article_id"]
    exported = await client.get(f"/api/v1/manuscripts/{mid}/export", headers=headers)
    assert exported.status_code == 200, exported.text
    assert exported.content[:2] == b"PK"
    zipped = zipfile.ZipFile(io.BytesIO(exported.content))
    document = zipped.read("word/document.xml").decode()
    comments = zipped.read("word/comments.xml").decode()
    endnotes = zipped.read("word/endnotes.xml").decode()
    assert "endnoteReference" in document
    assert "ins" in document
    assert "drinking water contamination" in document.lower()
    assert "Why this was suggested" in comments
    assert "Suggestion S-" in comments
    assert "Accept" in comments and "Reject" in comments
    assert "Shared archive reference" in endnotes
    assert "References" in document
    assert first["house_citation"] in document or first["house_citation"].split("“")[0].strip() in document
    listing = await client.get("/api/v1/manuscripts", headers=headers)
    assert any(row["id"] == mid for row in listing.json())
    deleted = await client.delete(f"/api/v1/manuscripts/{mid}", headers=headers)
    assert deleted.status_code == 204, deleted.text
    listing = await client.get("/api/v1/manuscripts", headers=headers)
    assert all(row["id"] != mid for row in listing.json())


@pytest.mark.asyncio
async def test_word_review_shares_one_reference_for_same_article(client: AsyncClient):
    from lxml import etree

    headers = await _auth(client)
    created = await client.post(
        "/api/v1/journals",
        headers=headers,
        json={"name": "Shared Reference Journal", "abbreviation": "SRJ"},
    )
    jid = created.json()["id"]
    paper = await client.post(
        f"/api/v1/journals/{jid}/papers-text",
        headers=headers,
        json={"filename": "water.txt", "text": GALLEY_WATER},
    )
    archive_id = paper.json()["article"]["id"]
    docx = _docx_from_paragraphs(
        "Introduction",
        "This manuscript reviews drinking water contamination and Water Quality Index (WQI) in rural Sindh.",
        "Materials and Methods",
        "SPI modelling for groundwater contamination in Khairpur also depends on drinking water quality.",
        "Results",
        "Result scores for drinking water quality are listed below.",
        "References",
    )
    up = await client.post(
        "/api/v1/manuscripts",
        headers=headers,
        files={
            "file": (
                "shared.docx",
                docx,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    mid = up.json()["id"]
    await client.post(f"/api/v1/manuscripts/{mid}/suggest", headers=headers)
    detail = (await client.get(f"/api/v1/manuscripts/{mid}", headers=headers)).json()
    sugs = [s for p in detail["paragraphs"] for s in p["suggestions"]]
    assert len(sugs) >= 2
    for s in sugs:
        stored = await client.get(f"/api/v1/articles/{s['article_id']}", headers=headers)
        assert stored.status_code == 200
    exported = await client.get(f"/api/v1/manuscripts/{mid}/export", headers=headers)
    assert exported.status_code == 200
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    zipped = zipfile.ZipFile(io.BytesIO(exported.content))
    doc = etree.fromstring(zipped.read("word/document.xml"))
    notes = etree.fromstring(zipped.read("word/endnotes.xml"))
    refs = [node.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}id") for node in doc.findall(".//w:endnoteReference", ns)]
    content_notes = [
        node
        for node in notes.findall("w:endnote", ns)
        if node.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}id") not in {"-1", "0"}
        and node.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}type") is None
    ]
    unique_articles = {s["article_id"] for s in sugs}
    assert len(content_notes) == len(unique_articles)
    assert len(set(refs)) == len(content_notes)
    assert len(refs) >= 2
    if len(sugs) > len(unique_articles):
        assert len(refs) > len(content_notes)
    for sug in sugs:
        acc = await client.patch(
            f"/api/v1/suggestions/{sug['id']}",
            headers=headers,
            json={"status": "rejected"},
        )
        assert acc.status_code == 200
    exported2 = await client.get(f"/api/v1/manuscripts/{mid}/export", headers=headers)
    doc2 = etree.fromstring(zipfile.ZipFile(io.BytesIO(exported2.content)).read("word/document.xml"))
    assert doc2.findall(".//w:endnoteReference", ns) == []
    assert "drinking water contamination" in etree.tostring(doc2).decode().lower()


@pytest.mark.asyncio
async def test_citation_sync_and_operator_patch(client: AsyncClient, monkeypatch):
    headers = await _auth(client)
    created = await client.post(
        "/api/v1/journals",
        headers=headers,
        json={"name": "Count Journal", "abbreviation": "CJ"},
    )
    jid = created.json()["id"]
    a1 = await client.post(
        f"/api/v1/journals/{jid}/papers-text",
        headers=headers,
        json={"filename": "eddsa.txt", "text": GALLEY_EDDSA},
    )
    assert a1.status_code == 200, a1.text
    aid = a1.json()["article"]["id"]

    async def fake_crossref(article):
        return 14, "10.1234/fake", "https://doi.org/10.1234/fake"

    async def fake_scholar(article):
        return 20, "https://scholar.google.com/fake", "ok"

    from app.services import citation_counts as counts_mod

    monkeypatch.setattr(counts_mod, "fetch_crossref", fake_crossref)
    monkeypatch.setattr(counts_mod, "fetch_scholar", fake_scholar)

    async def fake_citing(article):
        return [
            {
                "source": "crossref",
                "title": "A Crossref paper that cites this work",
                "authors": "C. Reviewer",
                "year": 2023,
                "venue": "Soft Computing",
                "doi": "10.1007/cite",
                "url": "https://doi.org/10.1007/cite",
            },
            {
                "source": "scholar",
                "title": "A Scholar paper that cites this work",
                "authors": "A. Reviewer, B. Editor",
                "year": 2024,
                "venue": "Example Journal",
                "doi": None,
                "url": "https://scholar.google.com/scholar?q=cite",
            },
        ]

    monkeypatch.setattr(counts_mod, "fetch_citing_works", fake_citing)

    synced = await client.post(f"/api/v1/articles/{aid}/sync-citations", headers=headers)
    assert synced.status_code == 200, synced.text
    body = synced.json()
    assert body["crossref_citation_count"] == 14
    assert body["scholar_citation_count"] == 20
    assert body["doi"] == "10.1234/fake"
    sources = {row["source"]: row for row in body["citing_works"]}
    assert sources["crossref"]["doi"] == "10.1007/cite"
    assert sources["scholar"]["authors"] == "A. Reviewer, B. Editor"
    assert sources["scholar"]["title"] == "A Scholar paper that cites this work"

    patched = await client.patch(
        f"/api/v1/articles/{aid}",
        headers=headers,
        json={"scholar_url": "https://scholar.google.com/manual", "scholar_citation_count": 21},
    )
    assert patched.status_code == 200
    assert patched.json()["scholar_citation_count"] == 21

    listing = await client.get(f"/api/v1/journals/{jid}/issues", headers=headers)
    assert listing.status_code == 200
    row = listing.json()[0]
    assert row["scholar_total"] == 21
    assert row["crossref_total"] == 14
    assert row["cited_count"] >= 1
    assert row["citations_synced"] is True


@pytest.mark.asyncio
async def test_archive_crawler_mock(client: AsyncClient, monkeypatch):
    headers = await _auth(client)
    created = await client.post(
        "/api/v1/journals",
        headers=headers,
        json={"name": "Crawl Journal", "abbreviation": "CJ"},
    )
    jid = created.json()["id"]
    pdf_bytes = _pdf_from_text(GALLEY_WATER)

    async def fake_fetch(url: str):
        pages = {
            "https://example.test/issue/archive": (
                b"<html>"
                b'<a href="https://example.test/issue/view/1">Vol. 8 No. 5 (2026)</a>'
                b'<a href="https://example.test/issue/archive/2">Next</a>'
                b"</html>"
            ),
            "https://example.test/issue/archive/2": (
                b"<html><a href='https://example.test/issue/view/2'>Vol. 8 No. 2 (2026)</a></html>"
            ),
            "https://example.test/issue/view/1": (
                b"<html>"
                b'<a href="https://example.test/article/view/9">Article</a>'
                b'<a href="https://example.test/article/view/9/11">PDF</a>'
                b'<a href="https://example.test/article/view/10">Second</a>'
                b'<a href="https://example.test/article/view/10/12">PDF</a>'
                b'<a href="https://example.test/article/view/12">Third, PDF only on article page</a>'
                b"</html>"
            ),
            "https://example.test/article/view/12": (
                b"<html>"
                b'<meta name="citation_pdf_url" content="https://example.test/article/download/12/30">'
                b'<a href="https://example.test/article/view/99">Related</a>'
                b'<a href="https://example.test/article/view/99/1">PDF</a>'
                b"</html>"
            ),
            "https://example.test/issue/view/2": (
                b"<html>"
                b'<a href="https://example.test/article/view/8">Other</a>'
                b'<a href="https://example.test/article/download/8/b.pdf">PDF</a>'
                b"</html>"
            ),
        }
        if url in pages:
            return 200, pages[url], "text/html"
        if url.endswith(".pdf") or "/download/" in url or re.search(r"/article/view/\d+/\d+", url):
            return 200, pdf_bytes, "application/pdf"
        if url.endswith("/robots.txt"):
            return 404, b"", "text/plain"
        return 404, b"", "text/plain"

    from app.services import crawler as crawler_mod

    monkeypatch.setattr(crawler_mod, "default_fetch", fake_fetch)

    start = await client.post(
        f"/api/v1/journals/{jid}/crawl",
        headers=headers,
        json={"archive_url": "https://example.test/issue/archive"},
    )
    assert start.status_code == 200, start.text
    job_id = start.json()["id"]
    await crawler_mod.run_crawl_job(job_id, fetch=fake_fetch)

    job = await client.get(f"/api/v1/crawl-jobs/{job_id}", headers=headers)
    assert job.status_code == 200
    body = job.json()
    assert body["status"] == "awaiting_selection", body
    assert body["issues_found"] == 2
    by_url = {row["url"]: row for row in body["inventory"]}
    assert by_url["https://example.test/issue/view/1"]["article_count"] == 3
    assert by_url["https://example.test/issue/view/2"]["article_count"] == 1
    assert body["articles_found"] == 4
    pdfs = by_url["https://example.test/issue/view/1"]["pdf_urls"]
    assert any(url.endswith("/download/12/30") or "/download/12/" in url for url in pdfs)
    assert not any("/article/view/99" in url for url in pdfs)
    listing = await client.get("/api/v1/journals", headers=headers)
    crawled = next(row for row in listing.json() if row["id"] == jid)
    assert crawled["article_count"] == 0

    unknown = await client.post(
        f"/api/v1/crawl-jobs/{job_id}/download",
        headers=headers,
        json={"issue_urls": ["https://example.test/issue/view/999"]},
    )
    assert unknown.status_code == 400

    await crawler_mod.run_download_job(
        job_id, ["https://example.test/issue/view/1"], fetch=fake_fetch
    )
    downloaded = (await client.get(f"/api/v1/crawl-jobs/{job_id}", headers=headers)).json()

    assert downloaded["status"] == "completed", downloaded
    assert downloaded["articles_saved"] >= 1
    assert downloaded["articles_remaining"] == 0
    listing = await client.get("/api/v1/journals", headers=headers)
    crawled = next(row for row in listing.json() if row["id"] == jid)
    assert crawled["article_count"] >= 1
    first_count = crawled["article_count"]

    await crawler_mod.run_download_job(
        job_id, ["https://example.test/issue/view/1"], fetch=fake_fetch
    )
    dup = (await client.get(f"/api/v1/crawl-jobs/{job_id}", headers=headers)).json()
    assert dup["articles_skipped"] >= 1
    assert dup.get("articles_already", 0) >= 1
    listing = await client.get("/api/v1/journals", headers=headers)
    crawled = next(row for row in listing.json() if row["id"] == jid)
    assert crawled["article_count"] == first_count


@pytest.mark.asyncio
async def test_archive_state_update_adds_and_removes_live_articles(client: AsyncClient, monkeypatch):
    headers = await _auth(client)
    created = await client.post(
        "/api/v1/journals",
        headers=headers,
        json={"name": "State Update Journal", "abbreviation": "SUJ"},
    )
    jid = created.json()["id"]
    manual = await client.post(
        f"/api/v1/journals/{jid}/papers-text",
        headers=headers,
        json={"filename": "manual.txt", "text": GALLEY_WATER},
    )
    assert manual.status_code == 200, manual.text
    extra_galley = GALLEY_EDDSA.replace("1788", "3001").replace("1813", "3010").replace(
        "Digital Signature Scheme", "State Update Extra Paper"
    )
    live = {
        "https://example.test/issue/archive": (
            b"<html><a href='https://example.test/issue/view/1'>Vol. 8 No. 5 (2026)</a></html>"
        ),
        "https://example.test/issue/view/1": (
            b"<html>"
            b'<a href="https://example.test/article/view/9">One</a>'
            b'<a href="https://example.test/article/view/9/11">PDF</a>'
            b'<a href="https://example.test/article/view/10">Two</a>'
            b'<a href="https://example.test/article/view/10/12">PDF</a>'
            b"</html>"
        ),
    }
    pdf_by_url = {
        "https://example.test/article/view/9/11": _pdf_from_text(GALLEY_EDDSA),
        "https://example.test/article/view/10/12": _pdf_from_text(GALLEY_WATER.replace("2211", "4001").replace("2224", "4010")),
        "https://example.test/article/view/21/31": _pdf_from_text(extra_galley),
    }

    async def fake_fetch(url: str):
        if url in live:
            return 200, live[url], "text/html"
        if url in pdf_by_url:
            return 200, pdf_by_url[url], "application/pdf"
        if url.endswith("/robots.txt"):
            return 404, b"", "text/plain"
        return 404, b"", "text/plain"

    from app.services import crawler as crawler_mod

    monkeypatch.setattr(crawler_mod, "default_fetch", fake_fetch)
    start = await client.post(
        f"/api/v1/journals/{jid}/crawl",
        headers=headers,
        json={"archive_url": "https://example.test/issue/archive"},
    )
    job_id = start.json()["id"]
    await crawler_mod.run_crawl_job(job_id, fetch=fake_fetch)
    await crawler_mod.run_download_job(job_id, ["https://example.test/issue/view/1"], fetch=fake_fetch)
    before = await client.get("/api/v1/journals", headers=headers)
    count_before = next(row for row in before.json() if row["id"] == jid)["article_count"]
    assert count_before >= 2

    live["https://example.test/issue/view/1"] = (
        b"<html>"
        b'<a href="https://example.test/article/view/10">Two</a>'
        b'<a href="https://example.test/article/view/10/12">PDF</a>'
        b'<a href="https://example.test/article/view/21">New</a>'
        b'<a href="https://example.test/article/view/21/31">PDF</a>'
        b"</html>"
    )
    sync = await client.post(
        f"/api/v1/journals/{jid}/sync-state",
        headers=headers,
        json={"archive_url": "https://example.test/issue/archive"},
    )
    assert sync.status_code == 200, sync.text
    sync_id = sync.json()["id"]
    await crawler_mod.run_state_update_job(sync_id, fetch=fake_fetch)
    result = (await client.get(f"/api/v1/crawl-jobs/{sync_id}", headers=headers)).json()
    assert result["status"] == "completed", result
    assert result["articles_saved"] >= 1
    assert result["articles_removed"] >= 1
    arts = await client.get(f"/api/v1/journals/{jid}/issues", headers=headers)
    assert arts.status_code == 200
    titles = []
    for issue in arts.json():
        if not issue["id"] or not issue["article_count"]:
            continue
        payload = await client.get(
            f"/api/v1/journals/{jid}/volumes/{issue['volume']}/issues/{issue['issue_number']}/articles",
            headers=headers,
        )
        titles.extend(a["title"] for a in payload.json()["articles"])
    blob = " ".join(titles)
    assert "State Update Extra Paper" in blob
    assert not any("Digital Signature Scheme" in t for t in titles)
    assert any("Drinking Water" in t or "Water" in t for t in titles)


@pytest.mark.asyncio
async def test_fcsi_suggestions_use_real_title_authors_and_ieee_citation(client: AsyncClient):
    headers = await _auth(client)
    created = await client.post(
        "/api/v1/journals",
        headers=headers,
        json={
            "name": "Frontiers in Computational Spatial Intelligence",
            "abbreviation": "FCSI",
        },
    )
    jid = created.json()["id"]
    paper = await client.post(
        f"/api/v1/journals/{jid}/papers-text",
        headers=headers,
        json={"filename": "safflower.txt", "text": GALLEY_FCSI},
    )
    assert paper.status_code == 200, paper.text
    article = paper.json()["article"]
    assert "Safflower" in article["title"]
    assert "Frontiers in Computational Spatial Intelligence" not in article["title"]
    assert article["authors"]
    assert article["doi"]
    assert article["page_start"] == 66
    assert article["page_end"] == 76

    broken = await client.post(
        f"/api/v1/journals/{jid}/papers-text",
        headers=headers,
        json={
            "filename": "broken.txt",
            "text": (
                "Frontiers in Computational Spatial Intelligence underexplored. Efficient scheduling "
                "and conflict-free coordination among multiple robots in constrained environments, "
                "such as safflower fields, is therefore a critical research direction[7][8].\n"
                "May 2025|Vol 03 | Issue 02 Page |210\n"
            ),
        },
    )
    assert broken.status_code == 200
    broken_id = broken.json()["article"]["id"]
    restored = (
        GALLEY_FCSI.replace("66-76", "210-218")
        .replace("Page |66", "Page |210")
        .replace("Issue 02", "Issue 03")
        .replace("Issue. 2", "Issue. 3")
        .replace(
            "An Integrated Ant Colony and Dynamic Window Approach for Cooperative Multi-Robot Trajectory Planning in Safflower Cultivation",
            "Cooperative Multi-Robot Harvesting With Spatial Planning",
        )
    )
    from sqlalchemy import select
    from app.database.session import AsyncSessionLocal
    from app.models.citation import Article

    async with AsyncSessionLocal() as db:
        row = await db.get(Article, broken_id)
        assert row is not None
        row.full_text = restored
        row.title = "Frontiers in Computational Spatial Intelligence underexplored. Efficient scheduling."
        row.authors = []
        await db.commit()

    repaired = await client.post(f"/api/v1/journals/{jid}/repair-metadata", headers=headers)
    assert repaired.status_code == 200, repaired.text
    assert repaired.json()["repaired"] >= 1
    stored = (await client.get(f"/api/v1/articles/{broken_id}", headers=headers)).json()
    assert "Spatial Planning" in stored["title"] or "Safflower" in stored["title"]
    assert stored["authors"]
    assert not stored["title"].startswith("Frontiers in Computational Spatial Intelligence")

    pdf = _pdf_from_text(
        "Introduction\n"
        "This manuscript studies cooperative multi-robot trajectory planning in safflower "
        "cultivation using ant colony optimization and the dynamic window approach.\n"
        "Materials and Methods\n"
        "Robots were scheduled in a safflower field with collision-free coordination.\n"
        "Results\n"
        "The results should not receive archive citation suggestions."
    )
    up = await client.post(
        "/api/v1/manuscripts",
        headers=headers,
        files={"file": ("fcsi-ms.pdf", pdf, "application/pdf")},
    )
    assert up.status_code == 201, up.text
    mid = up.json()["id"]
    sug = await client.post(f"/api/v1/manuscripts/{mid}/suggest", headers=headers)
    assert sug.status_code == 200, sug.text
    assert sug.json()["suggestion_count"] >= 1
    detail = (await client.get(f"/api/v1/manuscripts/{mid}", headers=headers)).json()
    sugs = [s for p in detail["paragraphs"] for s in p["suggestions"]]
    assert sugs
    cite = sugs[0]["house_citation"]
    assert "Authors," not in cite
    assert "vol." in cite and "no." in cite and "pp." in cite
    assert "FCSI" in cite or "Frontiers in Computational Spatial Intelligence" in cite
    assert "Safflower" in cite or "Spatial Planning" in cite or (sugs[0].get("article_title") or "")
    assert not cite.lower().startswith("authors")
    exported = await client.get(f"/api/v1/manuscripts/{mid}/export", headers=headers)
    assert exported.status_code == 200
    document = zipfile.ZipFile(io.BytesIO(exported.content)).read("word/document.xml").decode()
    assert "vol." in document
    assert "underexplored. Efficient scheduling" not in document


@pytest.mark.asyncio
async def test_journal_duplicate_and_delete(client: AsyncClient):
    headers = await _auth(client)
    first = await client.post(
        "/api/v1/journals",
        headers=headers,
        json={"name": "Once Only Journal", "abbreviation": "OOJ"},
    )
    assert first.status_code == 201, first.text
    jid = first.json()["id"]
    second = await client.post(
        "/api/v1/journals",
        headers=headers,
        json={"name": "once only journal", "abbreviation": "OOJ"},
    )
    assert second.status_code == 409
    deleted = await client.delete(f"/api/v1/journals/{jid}", headers=headers)
    assert deleted.status_code == 204
    listing = await client.get("/api/v1/journals", headers=headers)
    names = [row["name"] for row in listing.json()]
    assert "Once Only Journal" not in names


@pytest.mark.asyncio
async def test_user_journal_assignment_hides_journals_and_filters_suggestions(client: AsyncClient):
    admin = await _auth(client)
    journal_a = await client.post(
        "/api/v1/journals",
        headers=admin,
        json={"name": "Journal Alpha Cite Scope", "abbreviation": "JAC"},
    )
    journal_b = await client.post(
        "/api/v1/journals",
        headers=admin,
        json={"name": "Journal Beta Cite Scope", "abbreviation": "JBC"},
    )
    assert journal_a.status_code == 201, journal_a.text
    assert journal_b.status_code == 201, journal_b.text
    id_a = journal_a.json()["id"]
    id_b = journal_b.json()["id"]

    paper_a = await client.post(
        f"/api/v1/journals/{id_a}/papers-text",
        headers=admin,
        json={"filename": "eddsa.txt", "text": GALLEY_EDDSA},
    )
    paper_b = await client.post(
        f"/api/v1/journals/{id_b}/papers-text",
        headers=admin,
        json={"filename": "water.txt", "text": GALLEY_WATER},
    )
    assert paper_a.status_code == 200, paper_a.text
    assert paper_b.status_code == 200, paper_b.text

    created = await client.post(
        "/api/v1/admin/users",
        headers=admin,
        json={
            "email": "citeuser@example.com",
            "username": "citeuser",
            "password": "CiteUser@123456",
            "full_name": "Cite User",
            "role": "user",
            "assigned_journal_ids": [id_b],
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["assigned_journal_ids"] == [id_b]
    uid = created.json()["id"]

    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "citeuser", "password": "CiteUser@123456"},
    )
    user = {"Authorization": f"Bearer {login.json()['access_token']}"}

    visible = await client.get("/api/v1/journals", headers=user)
    assert visible.status_code == 200
    names = {row["name"] for row in visible.json()}
    assert "Journal Beta Cite Scope" in names
    assert "Journal Alpha Cite Scope" not in names

    assert (await client.get(f"/api/v1/journals/{id_a}", headers=user)).status_code == 404
    seen_b = await client.get(f"/api/v1/journals/{id_b}", headers=user)
    assert seen_b.status_code == 200
    assert seen_b.json()["article_count"] == 1
    vols = await client.get(f"/api/v1/journals/{id_b}/volumes", headers=user)
    assert vols.status_code == 200, vols.text
    vol = next(row["volume"] for row in vols.json() if row["article_count"] > 0)
    issues = await client.get(f"/api/v1/journals/{id_b}/volumes/{vol}/issues", headers=user)
    assert issues.status_code == 200, issues.text
    iss = next(row for row in issues.json() if row["article_count"] > 0)
    arts = await client.get(
        f"/api/v1/journals/{id_b}/volumes/{vol}/issues/{iss['issue_number']}/articles",
        headers=user,
    )
    assert arts.status_code == 200, arts.text
    assert arts.json()["articles"]
    assert all(not row.get("pdf_path") for row in arts.json()["articles"])

    assert (await client.delete(f"/api/v1/journals/{id_b}", headers=user)).status_code == 403
    assert (
        await client.post(
            f"/api/v1/journals/{id_b}/papers-text",
            headers=user,
            json={"filename": "nope.txt", "text": GALLEY_WATER},
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/journals/{id_b}/crawl",
            headers=user,
            json={"archive_url": "https://example.test/archive"},
        )
    ).status_code == 403

    pdf = _pdf_from_text(
        "Introduction\n"
        "This manuscript proposes an EdDSA watermarking scheme for digital document "
        "authentication and tamper detection using Edward curve signatures.\n"
        "Materials and Methods\n"
        "The EdDSA watermarking pipeline signs each document page before embedding.\n"
        "Results\n"
        "The signature scheme results are reported separately."
    )
    up = await client.post(
        "/api/v1/manuscripts",
        headers=user,
        files={"file": ("eddsa-ms.pdf", pdf, "application/pdf")},
    )
    assert up.status_code == 201, up.text
    mid = up.json()["id"]
    blocked = await client.post(f"/api/v1/manuscripts/{mid}/suggest", headers=user)
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["suggestion_count"] == 0
    assert blocked.json()["report"]["citations_found"] == 0
    assert "0 citations found" in blocked.json()["report"]["message"].lower()

    assigned = await client.patch(
        f"/api/v1/admin/users/{uid}",
        headers=admin,
        json={"assigned_journal_ids": [id_a, id_b]},
    )
    assert assigned.status_code == 200, assigned.text
    assert set(assigned.json()["assigned_journal_ids"]) == {id_a, id_b}

    allowed = await client.post(f"/api/v1/manuscripts/{mid}/suggest", headers=user)
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["suggestion_count"] >= 1
    detail = (await client.get(f"/api/v1/manuscripts/{mid}", headers=user)).json()
    reasons = " ".join(
        s["reason"] + " " + (s.get("article") or {}).get("title", "")
        for p in detail["paragraphs"]
        for s in p["suggestions"]
    )
    assert "Digital Signature" in reasons or "EDDSA" in reasons or "Watermark" in reasons
    assert all(not (s.get("article") or {}).get("pdf_path") for p in detail["paragraphs"] for s in p["suggestions"])


@pytest.mark.asyncio
async def test_admin_adds_users_and_manuscripts_stay_private(client: AsyncClient):
    operator = await client.post(
        "/api/v1/auth/login",
        json={"username": "citation@xdgen.com", "password": "pak123"},
    )
    admin = {"Authorization": f"Bearer {operator.json()['access_token']}"}
    first = await client.post(
        "/api/v1/admin/users",
        headers=admin,
        json={
            "email": "alpha@example.com",
            "username": "alpha_user",
            "password": "AlphaUser@123456",
            "role": "user",
        },
    )
    second = await client.post(
        "/api/v1/admin/users",
        headers=admin,
        json={
            "email": "beta@example.com",
            "username": "beta_user",
            "password": "BetaUser@123456",
            "role": "user",
        },
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["access_status"] == "approved"
    assert second.json()["access_status"] == "approved"

    login_a = await client.post(
        "/api/v1/auth/login",
        json={"username": "alpha_user", "password": "AlphaUser@123456"},
    )
    login_b = await client.post(
        "/api/v1/auth/login",
        json={"username": "beta_user", "password": "BetaUser@123456"},
    )
    assert login_a.status_code == 200
    assert login_b.status_code == 200
    user_a = {"Authorization": f"Bearer {login_a.json()['access_token']}"}
    user_b = {"Authorization": f"Bearer {login_b.json()['access_token']}"}

    pdf_a = _pdf_from_text("Introduction\nAlpha only manuscript about soil moisture.\nMaterials and Methods\nPlots were irrigated.")
    pdf_b = _pdf_from_text("Introduction\nBeta only manuscript about urban heat.\nMaterials and Methods\nSensors were calibrated.")
    up_a = await client.post(
        "/api/v1/manuscripts",
        headers=user_a,
        files={"file": ("alpha.pdf", pdf_a, "application/pdf")},
    )
    up_b = await client.post(
        "/api/v1/manuscripts",
        headers=user_b,
        files={"file": ("beta.pdf", pdf_b, "application/pdf")},
    )
    assert up_a.status_code == 201, up_a.text
    assert up_b.status_code == 201, up_b.text
    id_a = up_a.json()["id"]
    id_b = up_b.json()["id"]

    listed_a = {row["id"] for row in (await client.get("/api/v1/manuscripts", headers=user_a)).json()}
    listed_b = {row["id"] for row in (await client.get("/api/v1/manuscripts", headers=user_b)).json()}
    assert id_a in listed_a and id_b not in listed_a
    assert id_b in listed_b and id_a not in listed_b
    assert (await client.get(f"/api/v1/manuscripts/{id_b}", headers=user_a)).status_code == 404
    assert (await client.get(f"/api/v1/manuscripts/{id_a}", headers=user_b)).status_code == 404

    report_a = await client.post(f"/api/v1/manuscripts/{id_a}/suggest", headers=user_a)
    assert report_a.status_code == 200, report_a.text
    assert report_a.json()["report"]["citations_found"] == report_a.json()["suggestion_count"]
    assert "citations found" in report_a.json()["report"]["message"].lower()

