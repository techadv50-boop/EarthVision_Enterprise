"""Crawl journal archive / issue pages for research article HTML URLs (not PDFs)."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urljoin, urlparse, urldefrag

import httpx
from bs4 import BeautifulSoup

USER_AGENT = "DOI-REDIF-Converter/1.4 (archive crawler; mailto:redif-converter@local)"

# OJS-style article HTML pages look like .../article/view/123
# PDF galleys look like .../article/view/123/456 or .../article/download/...
ARTICLE_VIEW_RE = re.compile(r"/article/view/([^/?#]+)/?$", re.I)
ARTICLE_GALLEY_RE = re.compile(r"/article/view/([^/?#]+)/\d+/?", re.I)
ARTICLE_DOWNLOAD_RE = re.compile(r"/article/download/", re.I)
ISSUE_VIEW_RE = re.compile(r"/issue/view/([^/?#]+)/?$", re.I)
ISSUE_ARCHIVE_RE = re.compile(r"/issue/(archive|current)/?", re.I)


@dataclass
class CrawlResult:
    archive_url: str
    article_urls: list[str] = field(default_factory=list)
    issue_urls: list[str] = field(default_factory=list)
    pages_visited: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.article_urls)


def normalize_url(base: str, href: str) -> str:
    href = (href or "").strip()
    if not href or href.startswith(("#", "mailto:", "javascript:")):
        return ""
    absolute = urljoin(base, href)
    absolute, _frag = urldefrag(absolute)
    return absolute.rstrip("/")


def is_pdf_or_galley_url(url: str) -> bool:
    lower = (url or "").lower()
    if lower.endswith(".pdf"):
        return True
    if ARTICLE_DOWNLOAD_RE.search(lower):
        return True
    if ARTICLE_GALLEY_RE.search(lower):
        return True
    if "/galley/" in lower:
        return True
    if "format=pdf" in lower or "file=pdf" in lower:
        return True
    return False


def is_article_html_url(url: str) -> bool:
    """True for article landing/HTML pages, false for PDF/galley links."""
    if not url or is_pdf_or_galley_url(url):
        return False
    return bool(ARTICLE_VIEW_RE.search(urlparse(url).path))


def is_issue_url(url: str) -> bool:
    path = urlparse(url or "").path
    if ISSUE_VIEW_RE.search(path):
        return True
    if re.search(r"/issue/current/?$", path, re.I):
        return True
    return False


def is_archive_url(url: str) -> bool:
    path = urlparse(url or "").path.lower()
    return bool(ISSUE_ARCHIVE_RE.search(path)) or path.endswith("/archive")


def _extract_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html or "", "lxml")
    out: list[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        # Skip explicit PDF galley buttons
        classes = " ".join(a.get("class") or []).lower()
        if "pdf" in classes or "galley" in classes:
            # Still allow non-galley article title links elsewhere
            href = normalize_url(base_url, a["href"])
            if not is_article_html_url(href):
                continue
        href = normalize_url(base_url, a["href"])
        if not href or href in seen:
            continue
        seen.add(href)
        out.append(href)
    return out


def extract_article_urls_from_html(html: str, base_url: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    soup = BeautifulSoup(html or "", "lxml")
    # Prefer OJS article summary / title anchors
    for a in soup.select(
        ".obj_article_summary .title a[href], "
        ".obj_article_summary h3 a[href], "
        "h3.title a[href], "
        "a[href*='/article/view/']"
    ):
        classes = " ".join(a.get("class") or []).lower()
        if "galley" in classes or "pdf" in classes:
            continue
        href = normalize_url(base_url, a.get("href", ""))
        if not is_article_html_url(href):
            continue
        key = href.lower()
        if key in seen:
            continue
        seen.add(key)
        urls.append(href)

    # Fallback: any article/view link that is not a galley/pdf
    if not urls:
        for href in _extract_links(html, base_url):
            if is_article_html_url(href):
                key = href.lower()
                if key in seen:
                    continue
                seen.add(key)
                urls.append(href)
    return urls


def extract_issue_urls_from_html(html: str, base_url: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for href in _extract_links(html, base_url):
        if not is_issue_url(href):
            continue
        key = href.lower()
        if key in seen:
            continue
        seen.add(key)
        urls.append(href)
    return urls


async def _fetch(client: httpx.AsyncClient, url: str) -> tuple[str, str]:
    resp = await client.get(url, headers={"Accept": "text/html,application/xhtml+xml"})
    resp.raise_for_status()
    return str(resp.url), resp.text


async def crawl_archive(
    archive_url: str,
    *,
    max_issues: int = 500,
    concurrency: int = 5,
    progress_cb: Callable[[dict], None] | None = None,
) -> CrawlResult:
    """Crawl an archive/issue URL and return unique research-article HTML URLs."""
    seed = (archive_url or "").strip()
    result = CrawlResult(archive_url=seed)
    if not seed:
        result.errors.append("Empty archive URL")
        return result
    if not re.match(r"^https?://", seed, re.I):
        result.errors.append("Archive URL must start with http:// or https://")
        return result

    def emit(event: dict) -> None:
        if progress_cb:
            progress_cb(event)

    sem = asyncio.Semaphore(max(1, min(concurrency, 10)))
    article_seen: set[str] = set()
    issue_seen: set[str] = set()

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=45.0,
        headers={"User-Agent": USER_AGENT},
    ) as client:

        async def add_articles_from_page(page_url: str, html: str) -> int:
            found = extract_article_urls_from_html(html, page_url)
            added = 0
            for url in found:
                key = url.lower()
                if key in article_seen:
                    continue
                article_seen.add(key)
                result.article_urls.append(url)
                added += 1
            return added

        try:
            emit({"phase": "fetch", "url": seed, "message": "Opening archive URL…"})
            final_url, html = await _fetch(client, seed)
            result.pages_visited += 1
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"Could not open archive URL: {exc}")
            emit({"phase": "error", "message": result.errors[-1]})
            return result

        # Case A: seed itself is an issue / current page with articles
        direct_articles = await add_articles_from_page(final_url, html)
        issue_urls = extract_issue_urls_from_html(html, final_url)

        # If seed is an issue page, we already have articles; still allow nested issue links rarely
        if direct_articles and (is_issue_url(final_url) or not is_archive_url(final_url)):
            emit(
                {
                    "phase": "done_page",
                    "url": final_url,
                    "articles": direct_articles,
                    "total_articles": result.count,
                    "message": f"Found {direct_articles} article URL(s) on page",
                }
            )
            # If this looks like a single issue page, stop after it
            if is_issue_url(final_url) and not is_archive_url(final_url):
                emit(
                    {
                        "phase": "completed",
                        "total_articles": result.count,
                        "issues": len(result.issue_urls),
                        "pages_visited": result.pages_visited,
                    }
                )
                return result

        # Case B: archive listing → crawl each issue
        for iu in issue_urls:
            key = iu.lower()
            if key in issue_seen:
                continue
            issue_seen.add(key)
            result.issue_urls.append(iu)

        if not result.issue_urls and not result.article_urls:
            # Generic fallback: treat any article/view links already collected
            result.errors.append(
                "No issue or article links found. Try an issue URL or OJS archive page."
            )
            emit({"phase": "completed", "total_articles": 0, "message": result.errors[-1]})
            return result

        # Limit issues for safety
        issues_to_crawl = result.issue_urls[:max_issues]
        emit(
            {
                "phase": "issues",
                "count": len(issues_to_crawl),
                "message": f"Crawling {len(issues_to_crawl)} issue page(s)…",
            }
        )

        async def crawl_issue(issue_url: str) -> None:
            async with sem:
                try:
                    emit({"phase": "fetch", "url": issue_url, "message": f"Opening {issue_url}"})
                    page_url, page_html = await _fetch(client, issue_url)
                    result.pages_visited += 1
                    added = await add_articles_from_page(page_url, page_html)
                    emit(
                        {
                            "phase": "done_page",
                            "url": page_url,
                            "articles": added,
                            "total_articles": result.count,
                            "message": f"{added} article(s) from issue",
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    msg = f"Issue failed {issue_url}: {exc}"
                    result.errors.append(msg)
                    emit({"phase": "error", "message": msg, "total_articles": result.count})

        if issues_to_crawl:
            await asyncio.gather(*(crawl_issue(u) for u in issues_to_crawl))

    emit(
        {
            "phase": "completed",
            "total_articles": result.count,
            "issues": len(result.issue_urls),
            "pages_visited": result.pages_visited,
            "message": f"Done. {result.count} article URL(s) found.",
        }
    )
    return result


def crawl_archive_sync(
    archive_url: str,
    *,
    max_issues: int = 500,
    concurrency: int = 5,
    progress_cb: Callable[[dict], None] | None = None,
) -> CrawlResult:
    return asyncio.run(
        crawl_archive(
            archive_url,
            max_issues=max_issues,
            concurrency=concurrency,
            progress_cb=progress_cb,
        )
    )
