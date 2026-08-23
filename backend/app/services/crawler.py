"""Crawl a journal archive URL (OJS-first) and ingest PDFs into the shared store."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import AsyncSessionLocal
from app.models.citation import CrawlJob, Journal
from app.services.ingest import ingest_pdf_bytes

USER_AGENT = "CitationAssistant/1.0 (journal archive ingest)"
ISSUE_HREF = re.compile(r"/issue/view/\d+", re.I)
ARTICLE_HREF = re.compile(r"/article/view/\d+", re.I)


def _same_host(root: str, url: str) -> bool:
    return (urlparse(root).hostname or "").lower() == (urlparse(url).hostname or "").lower()


def extract_links(html: str, base: str) -> list[str]:
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        return [urljoin(base, a["href"]) for a in soup.find_all("a", href=True)]
    except ImportError:
        return [urljoin(base, h) for h in re.findall(r'href=["\']([^"\']+)["\']', html, re.I)]


async def default_fetch(url: str) -> tuple[int, bytes, str]:
    async with httpx.AsyncClient(
        timeout=40.0, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    ) as client:
        resp = await client.get(url)
        return resp.status_code, resp.content, resp.headers.get("content-type") or ""


def _robots_allows(robots_txt: str, path: str) -> bool:
    """Honor Disallow lines for a generic User-agent: * block."""
    in_star = False
    for raw in robots_txt.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lower = line.lower()
        if lower.startswith("user-agent:"):
            in_star = "*" in line.split(":", 1)[-1]
            continue
        if in_star and lower.startswith("disallow:"):
            rule = line.split(":", 1)[-1].strip()
            if rule and path.startswith(rule):
                return False
    return True


default_fetch = default_fetch


async def run_crawl_job(job_id: int, fetch=default_fetch, delay: float = 0.05) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(CrawlJob, job_id)
        if job is None:
            return
        journal = await db.get(Journal, job.journal_id)
        if journal is None:
            job.status = "failed"
            job.error_log = (job.error_log or []) + ["Journal not found"]
            job.finished_at = datetime.now(timezone.utc)
            await db.commit()
            return
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        job.error_log = list(job.error_log or [])
        await db.commit()
        try:
            await _crawl(db, job, journal, fetch, delay)
            job.status = "cancelled" if job.cancel_requested else "completed"
        except Exception as exc:
            job.status = "failed"
            job.error_log = (job.error_log or []) + [str(exc)]
        job.finished_at = datetime.now(timezone.utc)
        await db.commit()


async def _crawl(
    db: AsyncSession, job: CrawlJob, journal: Journal, fetch, delay: float
) -> None:
    archive = job.archive_url
    parsed = urlparse(archive)
    robots_txt = ""
    try:
        rst, rbody, _rct = await fetch(f"{parsed.scheme}://{parsed.netloc}/robots.txt")
        if rst < 400:
            robots_txt = rbody.decode("utf-8", errors="ignore")
    except Exception:
        robots_txt = ""
    status, body, _ctype = await fetch(archive)
    if status >= 400:
        raise RuntimeError(f"Archive URL returned HTTP {status}")
    html = body.decode("utf-8", errors="ignore")
    issue_urls: list[str] = []
    seen: set[str] = set()
    for href in extract_links(html, archive):
        if not _same_host(archive, href):
            continue
        if ISSUE_HREF.search(href) or re.search(r"/issue/archive", href, re.I):
            clean = href.split("#")[0]
            if clean not in seen:
                seen.add(clean)
                issue_urls.append(clean)
    if ISSUE_HREF.search(archive) and archive not in issue_urls:
        issue_urls.insert(0, archive)
    if not issue_urls:
        issue_urls = [archive]

    job.issues_found = len(issue_urls)
    await db.commit()

    pdf_urls: list[str] = []
    for issue_url in issue_urls:
        if job.cancel_requested:
            return
        await asyncio.sleep(delay)
        st, content, _ct = await fetch(issue_url)
        if st >= 400:
            job.error_log = (job.error_log or []) + [f"Issue {issue_url}: HTTP {st}"]
            continue
        page_html = content.decode("utf-8", errors="ignore")
        for href in extract_links(page_html, issue_url):
            if not _same_host(archive, href):
                continue
            low = href.lower()
            if low.endswith(".pdf") or "/article/download/" in low or "/download/" in low:
                clean = href.split("#")[0]
                if _robots_allows(robots_txt, urlparse(clean).path):
                    pdf_urls.append(clean)
            elif ARTICLE_HREF.search(href):
                await asyncio.sleep(delay)
                ast, abody, act = await fetch(href)
                if ast >= 400:
                    continue
                if "pdf" in (act or "").lower() or abody[:5] == b"%PDF-":
                    pdf_urls.append(href)
                    continue
                ahtml = abody.decode("utf-8", errors="ignore")
                for h2 in extract_links(ahtml, href):
                    if not _same_host(archive, h2):
                        continue
                    l2 = h2.lower()
                    if l2.endswith(".pdf") or "/article/download/" in l2 or "galley" in l2:
                        clean2 = h2.split("#")[0]
                        if _robots_allows(robots_txt, urlparse(clean2).path):
                            pdf_urls.append(clean2)

    uniq: list[str] = []
    seen_pdf: set[str] = set()
    for url in pdf_urls:
        if url not in seen_pdf:
            seen_pdf.add(url)
            uniq.append(url)
    job.articles_found = len(uniq)
    await db.commit()

    for i, pdf_url in enumerate(uniq):
        if job.cancel_requested:
            return
        await asyncio.sleep(delay)
        try:
            st, content, ct = await fetch(pdf_url)
            if st >= 400:
                job.articles_skipped += 1
                job.error_log = (job.error_log or []) + [f"{pdf_url}: HTTP {st}"]
                continue
            is_pdf = content[:5] == b"%PDF-" or "pdf" in (ct or "").lower()
            if not is_pdf:
                job.articles_skipped += 1
                continue
            name = pdf_url.rstrip("/").split("/")[-1]
            if not name.lower().endswith(".pdf"):
                name = f"article_{i + 1}.pdf"
            _article, created = await ingest_pdf_bytes(
                db, journal, content, name, source_url=pdf_url
            )
            if created:
                job.articles_saved += 1
            else:
                job.articles_skipped += 1
            if i % 5 == 0:
                await db.commit()
        except Exception as exc:
            job.articles_skipped += 1
            job.error_log = (job.error_log or []) + [f"{pdf_url}: {exc}"]
    await db.commit()


run_crawl_job = run_crawl_job
