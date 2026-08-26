"""API tests for journal archive ingest, coverage gaps, matching, and crawler."""

from __future__ import annotations

import io
import re

import pytest
from httpx import AsyncClient
from reportlab.pdfgen import canvas

from tests.test_citation_parser import GALLEY_EDDSA, GALLEY_WATER
from app.services.citation_counts import normalize_doi
from xml.sax.saxutils import escape
import zipfile


def test_normalize_doi():
    assert normalize_doi("https://doi.org/10.33411/IJIST/20190101011") == "10.33411/IJIST/20190101011"
    assert normalize_doi("doi:10.33411/IJIST/20190101011") == "10.33411/IJIST/20190101011"


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


def test_merge_citing_works_includes_crossref_and_dedupes():
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
            _citing_record(source="crossref", title="Only Crossref", doi="10.cr/1", year=2023),
        ],
        [
            _citing_record(source="openalex", title="Same paper", doi="10.1/abc", authors="OA Only"),
            _citing_record(source="openalex", title="Only OpenAlex", doi="10.oa/1", year=2024),
        ],
    )
    dois = [row["doi"] for row in merged]
    assert dois[0] in {"10.cr/1", "10.1/abc"}
    assert "10.cr/1" in dois
    assert "10.oa/1" in dois
    same = next(row for row in merged if row["doi"] == "10.1/abc")
    assert "crossref" in same["source"]
    assert "openalex" in same["source"]
    assert same["venue"] == "Soft Computing"
    assert same["authors"] == "CR Author"
    assert merged[0]["source"].split(",")[0] == "crossref" or "crossref" in merged[0]["source"]


@pytest.mark.asyncio
async def test_fetch_citing_works_keeps_crossref_if_openalex_fails(monkeypatch):
    from types import SimpleNamespace

    from app.services import citation_counts as counts_mod

    async def boom(*_args, **_kwargs):
        raise RuntimeError("openalex down")

    async def fake_crossref(_client, doi):
        assert doi == "10.33411/ijist/20190101011"
        return [
            counts_mod._citing_record(
                source="crossref",
                title="Crossref citing article",
                doi="10.1007/s00500-022-06794-6",
                year=2022,
                venue="Soft Computing",
            )
        ]

    monkeypatch.setattr(counts_mod, "_fetch_openalex_citing_works", boom)
    monkeypatch.setattr(counts_mod, "_fetch_crossref_citing_works", fake_crossref)

    rows = await counts_mod.fetch_citing_works(
        SimpleNamespace(doi="10.33411/ijist/20190101011", title="Urban Heat Island")
    )
    assert len(rows) == 1
    assert rows[0]["source"] == "crossref"
    assert rows[0]["doi"] == "10.1007/s00500-022-06794-6"


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
        json={"username": "demo", "password": "Demo@123456"},
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
        "This manuscript reviews drinking water contamination, Water Quality Index (WQI) "
        "and SPI modelling for groundwater in rural Sindh and Khairpur."
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
        "This manuscript proposes an EdDSA watermarking scheme for digital document "
        "authentication and tamper detection using Edward curve signatures."
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
    docx = _docx_from_text(
        "This manuscript reviews drinking water contamination, Water Quality Index (WQI) "
        "and SPI modelling for groundwater in rural Sindh and Khairpur."
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
        "This manuscript reviews drinking water contamination and Water Quality Index (WQI) in rural Sindh.",
        "SPI modelling for groundwater contamination in Khairpur also depends on drinking water quality.",
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
                "source": "openalex",
                "title": "A later paper that cites this work",
                "authors": "A. Reviewer, B. Editor",
                "year": 2024,
                "venue": "Example Journal",
                "doi": "10.9999/cite",
                "url": "https://doi.org/10.9999/cite",
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
    assert sources["openalex"]["authors"] == "A. Reviewer, B. Editor"
    assert sources["openalex"]["doi"] == "10.9999/cite"

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
    listing = await client.get("/api/v1/journals", headers=headers)
    crawled = next(row for row in listing.json() if row["id"] == jid)
    assert crawled["article_count"] == first_count


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
