"""Crossref + Google Scholar cited-by counts (cached on Article)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.citation import Article

CROSSREF = "https://api.crossref.org/works"
OPENALEX = "https://api.openalex.org/works"
SCHOLAR = "https://scholar.google.com/scholar"
DOI_PREFIX_RE = re.compile(r"^(https?://)?(dx\.)?doi\.org/", re.I)
CITED_BY_RE = re.compile(r"Cited by\s+(\d+)", re.I)
BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def normalize_doi(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    doi = DOI_PREFIX_RE.sub("", value.strip())
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.I).strip().strip("/")
    return doi or None


def _crossref_headers() -> dict[str, str]:
    settings = get_settings()
    mail = getattr(settings, "crossref_mailto", None) or "citation-assistant@example.com"
    return {"User-Agent": f"CitationAssistant/1.0 (mailto:{mail})"}


def _title_overlap(left: str, right: str) -> bool:
    a = re.sub(r"[^a-z0-9]+", " ", (left or "").lower()).strip()
    b = re.sub(r"[^a-z0-9]+", " ", (right or "").lower()).strip()
    if not a or not b:
        return False
    if a[:48] in b or b[:48] in a:
        return True
    aw, bw = set(a.split()), set(b.split())
    if not aw or not bw:
        return False
    return len(aw & bw) / max(1, min(len(aw), len(bw))) >= 0.55


def _from_crossref_message(msg: dict, article: Article) -> tuple[int, Optional[str], Optional[str]]:
    doi = msg.get("DOI") or article.doi
    return (
        int(msg.get("is-referenced-by-count") or 0),
        doi,
        msg.get("URL") or (f"https://doi.org/{doi}" if doi else None),
    )


async def fetch_crossref(article: Article) -> tuple[int, Optional[str], Optional[str]]:
    timeout = httpx.Timeout(20.0)
    doi = normalize_doi(article.doi)
    async with httpx.AsyncClient(timeout=timeout, headers=_crossref_headers(), follow_redirects=True) as client:
        if doi:
            resp = await client.get(f"{CROSSREF}/{quote(doi, safe=':/')}")
            if resp.status_code == 200:
                return _from_crossref_message(resp.json().get("message") or {}, article)
            try:
                oa = await client.get(f"{OPENALEX}/https://doi.org/{doi}")
                if oa.status_code == 200:
                    body = oa.json()
                    count = int(body.get("cited_by_count") or 0)
                    return count, doi, body.get("id") or f"https://doi.org/{doi}"
            except Exception:
                pass
        query = " ".join(
            p
            for p in (
                article.title,
                " ".join(a for a in (article.authors or []) if isinstance(a, str))[:120],
            )
            if p
        )
        if not query.strip():
            return article.crossref_citation_count or 0, article.doi, article.crossref_work_url
        resp = await client.get(
            CROSSREF,
            params={"query.bibliographic": query, "rows": 5},
        )
        if resp.status_code != 200:
            return article.crossref_citation_count or 0, article.doi, article.crossref_work_url
        items = (resp.json().get("message") or {}).get("items") or []
        want = article.title or ""
        for msg in items:
            got = ((msg.get("title") or [""])[0]) if isinstance(msg.get("title"), list) else str(msg.get("title") or "")
            if _title_overlap(want, got) or not want:
                return _from_crossref_message(msg, article)
        if items and not want:
            return _from_crossref_message(items[0], article)
    return article.crossref_citation_count or 0, article.doi, article.crossref_work_url


async def _scholar_html(title: str, doi: Optional[str]) -> tuple[int, Optional[str], str]:
    queries = [q for q in (doi, f'"{title[:140]}"' if title else None, title[:140] if title else None) if q]
    headers = {"User-Agent": BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"}
    async with httpx.AsyncClient(timeout=20.0, headers=headers, follow_redirects=True) as client:
        for query in queries:
            resp = await client.get(SCHOLAR, params={"q": query, "hl": "en"})
            if resp.status_code != 200:
                continue
            match = CITED_BY_RE.search(resp.text or "")
            if not match:
                continue
            link = None
            href = re.search(r'href="(https?://scholar\.google\.[^"]+|/?scholar\?[^"]*q=([^"]+))"', resp.text)
            if href:
                link = href.group(1)
                if link.startswith("/"):
                    link = "https://scholar.google.com" + link
            return int(match.group(1)), link, "ok"
    return 0, None, "unavailable"


async def fetch_scholar(article: Article) -> tuple[int, Optional[str], str]:
    settings = get_settings()
    title = article.title or ""
    doi = normalize_doi(article.doi)
    api_key = getattr(settings, "serpapi_key", "") or ""
    if api_key and title:
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(
                    "https://serpapi.com/search.json",
                    params={"engine": "google_scholar", "q": title, "api_key": api_key},
                )
            if resp.status_code == 200:
                results = resp.json().get("organic_results") or []
                if results:
                    first = results[0]
                    cited = (first.get("inline_links") or {}).get("cited_by") or {}
                    return int(cited.get("total") or 0), first.get("link"), "ok"
        except Exception:
            pass
    if title or doi:
        try:
            return await _scholar_html(title, doi)
        except Exception:
            pass
    try:
        from scholarly import scholarly  # type: ignore

        pub = next(scholarly.search_pubs(title), None) if title else None
        if pub:
            return int(pub.get("num_citations") or 0), pub.get("pub_url"), "ok"
    except Exception:
        pass
    return article.scholar_citation_count or 0, article.scholar_url, "unavailable"


async def sync_article_citations(db: AsyncSession, article: Article) -> Article:
    status = "ok"
    try:
        count, doi, work_url = await fetch_crossref(article)
        article.crossref_citation_count = count
        if doi:
            article.doi = normalize_doi(doi) or doi
        if work_url:
            article.crossref_work_url = work_url
    except Exception:
        status = "stale"
    try:
        count, url, sc_status = await fetch_scholar(article)
        if sc_status == "ok":
            article.scholar_citation_count = count
            if url:
                article.scholar_url = url
        elif sc_status != "ok" and status == "ok":
            status = "partial" if (article.crossref_citation_count or 0) else sc_status
        if sc_status != "ok" and status == "ok":
            status = sc_status if sc_status != "unavailable" else "partial"
    except Exception:
        status = "stale" if status != "ok" else "partial"
    article.citation_synced_at = datetime.now(timezone.utc)
    article.citation_sync_status = status
    await db.flush()
    return article
