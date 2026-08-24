"""API tests for journal archive ingest, coverage gaps, matching, and crawler."""

from __future__ import annotations

import io
import re

import pytest
from httpx import AsyncClient
from reportlab.pdfgen import canvas

from tests.test_citation_parser import GALLEY_EDDSA, GALLEY_WATER


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

    synced = await client.post(f"/api/v1/articles/{aid}/sync-citations", headers=headers)
    assert synced.status_code == 200, synced.text
    body = synced.json()
    assert body["crossref_citation_count"] == 14
    assert body["scholar_citation_count"] == 20
    assert body["doi"] == "10.1234/fake"

    patched = await client.patch(
        f"/api/v1/articles/{aid}",
        headers=headers,
        json={"scholar_url": "https://scholar.google.com/manual", "scholar_citation_count": 21},
    )
    assert patched.status_code == 200
    assert patched.json()["scholar_citation_count"] == 21


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
    assert by_url["https://example.test/issue/view/1"]["article_count"] == 2
    assert by_url["https://example.test/issue/view/2"]["article_count"] == 1
    assert body["articles_found"] == 3
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
