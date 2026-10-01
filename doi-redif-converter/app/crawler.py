"""Crawl journal archive / issue / sitemap pages for research article HTML URLs (not PDFs)."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urljoin, urlparse, urldefrag

import httpx
from bs4 import BeautifulSoup

USER_AGENT = "DOI-REDIF-Converter/1.4.1 (archive crawler; mailto:redif-converter@local)"

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
    sources_used: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
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


def journal_base_from_url(url: str) -> str:
    """Derive OJS journal base, e.g. https://host/index.php/IJIST"""
    parsed = urlparse(url)
    path = parsed.path or ""
    m = re.search(r"^(.*?/index\.php/[^/]+)", path, flags=re.I)
    if m:
        return f"{parsed.scheme}://{parsed.netloc}{m.group(1)}".rstrip("/")
    # fallback: origin only
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def sitemap_candidates(seed_url: str) -> list[str]:
    base = journal_base_from_url(seed_url)
    origin = f"{urlparse(seed_url).scheme}://{urlparse(seed_url).netloc}"
    return [
        f"{base}/sitemap",
        f"{base}/sitemap.xml",
        f"{origin}/sitemap.xml",
        f"{origin}/sitemap",
    ]


def extract_urls_from_sitemap_xml(xml_text: str) -> tuple[list[str], list[str]]:
    """Return (article_html_urls, issue_urls) from a sitemap xml/html document."""
    locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml_text or "", flags=re.I)
    # Also accept plain URL lists accidentally returned as text/html
    if not locs:
        locs = re.findall(r"https?://[^\s<>\"']+", xml_text or "")
    articles: list[str] = []
    issues: list[str] = []
    seen_a: set[str] = set()
    seen_i: set[str] = set()
    for loc in locs:
        url = loc.strip().rstrip("/")
        if is_article_html_url(url):
            key = url.lower()
            if key not in seen_a:
                seen_a.add(key)
                articles.append(url)
        elif is_issue_url(url):
            key = url.lower()
            if key not in seen_i:
                seen_i.add(key)
                issues.append(url)
    return articles, issues


def _extract_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html or "", "lxml")
    out: list[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        classes = " ".join(a.get("class") or []).lower()
        if "pdf" in classes or "galley" in classes:
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


async def _fetch(client: httpx.AsyncClient, url: str) -> tuple[str, str, str]:
    resp = await client.get(url, headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"})
    resp.raise_for_status()
    return str(resp.url), resp.text, (resp.headers.get("content-type") or "").lower()


async def crawl_archive(
    archive_url: str,
    *,
    max_issues: int = 2000,
    concurrency: int = 5,
    progress_cb: Callable[[dict], None] | None = None,
) -> CrawlResult:
    """Crawl archive/issue/sitemap and return unique research-article HTML URLs."""
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

    def add_article(url: str) -> bool:
        key = url.lower()
        if key in article_seen:
            return False
        article_seen.add(key)
        result.article_urls.append(url)
        return True

    def add_issue(url: str) -> bool:
        key = url.lower()
        if key in issue_seen:
            return False
        issue_seen.add(key)
        result.issue_urls.append(url)
        return True

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=60.0,
        headers={"User-Agent": USER_AGENT},
    ) as client:

        # ---- 1) Sitemap first (most complete for OJS public published articles) ----
        sitemap_articles = 0
        for sm_url in sitemap_candidates(seed):
            try:
                emit({"phase": "fetch", "url": sm_url, "message": f"Checking sitemap: {sm_url}"})
                final_url, body, ctype = await _fetch(client, sm_url)
                result.pages_visited += 1
                if "xml" not in ctype and "<urlset" not in body[:2000].lower() and "<loc>" not in body[:5000].lower():
                    continue
                arts, issues = extract_urls_from_sitemap_xml(body)
                if not arts and not issues:
                    continue
                result.sources_used.append(final_url)
                for u in arts:
                    if add_article(u):
                        sitemap_articles += 1
                for u in issues:
                    add_issue(u)
                emit(
                    {
                        "phase": "sitemap",
                        "url": final_url,
                        "articles": len(arts),
                        "issues": len(issues),
                        "total_articles": result.count,
                        "message": f"Sitemap: {len(arts)} article URL(s), {len(issues)} issue(s)",
                    }
                )
                break
            except Exception as exc:  # noqa: BLE001
                result.notes.append(f"Sitemap miss {sm_url}: {exc}")

        # ---- 2) Open seed page (archive/issue) and collect links ----
        try:
            emit({"phase": "fetch", "url": seed, "message": "Opening archive/issue URL…"})
            final_url, html, _ctype = await _fetch(client, seed)
            result.pages_visited += 1
            result.sources_used.append(final_url)
        except Exception as exc:  # noqa: BLE001
            if result.count == 0:
                result.errors.append(f"Could not open archive URL: {exc}")
                emit({"phase": "error", "message": result.errors[-1]})
                return result
            result.notes.append(f"Seed page failed ({exc}); continuing with sitemap results")
            html = ""
            final_url = seed

        if html:
            for u in extract_article_urls_from_html(html, final_url):
                add_article(u)
            for u in extract_issue_urls_from_html(html, final_url):
                add_issue(u)

            # If seed is a single issue and sitemap empty, that may be enough
            if is_issue_url(final_url) and not is_archive_url(final_url) and result.count and sitemap_articles == 0:
                emit(
                    {
                        "phase": "completed",
                        "total_articles": result.count,
                        "issues": len(result.issue_urls),
                        "pages_visited": result.pages_visited,
                        "message": f"Done. {result.count} article URL(s) from issue page.",
                    }
                )
                return result

        # ---- 3) Crawl issue pages not yet covered (fills gaps when archive lists only recent issues) ----
        issues_to_crawl = result.issue_urls[:max_issues]
        # If we already have a strong sitemap article set, still crawl issues that might add slug-only pages,
        # but skip if sitemap already returned articles AND issue list is large (sitemap is authoritative).
        if sitemap_articles >= 50 and len(issues_to_crawl) > 0:
            # Still crawl issues only if archive/sitemap issue count suggests missing articles is unlikely;
            # Prefer trusting sitemap article list. Record note and skip heavy issue crawl.
            result.notes.append(
                "Used journal sitemap as primary source for published article pages. "
                "Editorial 'Archives' counts often include declined/unpublished submissions and are larger."
            )
            emit(
                {
                    "phase": "completed",
                    "total_articles": result.count,
                    "issues": len(result.issue_urls),
                    "pages_visited": result.pages_visited,
                    "sources": list(result.sources_used),
                    "message": f"Done. {result.count} published article URL(s) from sitemap (+ archive links).",
                }
            )
            return result

        if issues_to_crawl:
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
                        page_url, page_html, _ = await _fetch(client, issue_url)
                        result.pages_visited += 1
                        added = 0
                        for u in extract_article_urls_from_html(page_html, page_url):
                            if add_article(u):
                                added += 1
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

            await asyncio.gather(*(crawl_issue(u) for u in issues_to_crawl))

    if result.count == 0:
        result.errors.append(
            "No article URLs found. Try the journal sitemap/archive URL, or an issue URL."
        )

    result.notes.append(
        "Collected public HTML article pages only (PDF/galley links excluded). "
        "OJS editorial Archives totals include declined/unpublished items and are usually higher."
    )
    emit(
        {
            "phase": "completed",
            "total_articles": result.count,
            "issues": len(result.issue_urls),
            "pages_visited": result.pages_visited,
            "sources": list(result.sources_used),
            "message": f"Done. {result.count} article URL(s) found.",
        }
    )
    return result


def crawl_archive_sync(
    archive_url: str,
    *,
    max_issues: int = 2000,
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
