"""Crossref + Google Scholar cited-by counts (cached on Article)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.citation import Article

CROSSREF = "https://api.crossref.org/works"


def _headers() -> dict[str, str]:
    mail = get_settings().crossref_mailto or "citation-assistant@example.com"
    return {"User-Agent": f"CitationAssistant/1.0 (mailto:{mail})"}


async def fetch_crossref(article: Article) -> tuple[int, Optional[str], Optional[str]]:
    timeout = httpx.Timeout(20.0)
    async with httpx.AsyncClient(timeout=timeout, headers=_headers()) as client:
        if article.doi:
            resp = await client.get(f"{CROSSREF}/{article.doi.strip()}")
            if resp.status_code == 200:
                msg = resp.json().get("message") or {}
                doi = msg.get("DOI") or article.doi
                return (
                    int(msg.get("is-referenced-by-count") or 0),
                    doi,
                    msg.get("URL") or f"https://doi.org/{doi}",
                )
        query = " ".join(
            p
            for p in (
                article.title,
                " ".join(a for a in (article.authors or []) if isinstance(a, str)),
            )
            if p
        )
        if not query.strip():
            return article.crossref_citation_count or 0, article.doi, article.crossref_work_url
        resp = await client.get(CROSSREF, params={"query.bibliographic": query, "rows": 1})
        if resp.status_code != 200:
            return article.crossref_citation_count or 0, article.doi, article.crossref_work_url
        items = (resp.json().get("message") or {}).get("items") or []
        if not items:
            return 0, article.doi, article.crossref_work_url
        msg = items[0]
        got = (msg.get("title") or [""])[0].lower()
        want = (article.title or "").lower()
        if want and got and want[:40] not in got and got[:40] not in want:
            return article.crossref_citation_count or 0, article.doi, article.crossref_work_url
        doi = msg.get("DOI")
        return (
            int(msg.get("is-referenced-by-count") or 0),
            doi,
            msg.get("URL") or (f"https://doi.org/{doi}" if doi else None),
        )


async def fetch_scholar(article: Article) -> tuple[int, Optional[str], str]:
    settings = get_settings()
    title = article.title or ""
    if settings.serpapi_key and title:
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(
                    "https://serpapi.com/search.json",
                    params={
                        "engine": "google_scholar",
                        "q": title,
                        "api_key": settings.serpapi_key,
                    },
                )
            if resp.status_code == 200:
                results = resp.json().get("organic_results") or []
                if results:
                    first = results[0]
                    cited = (first.get("inline_links") or {}).get("cited_by") or {}
                    return int(cited.get("total") or 0), first.get("link"), "ok"
        except Exception:
            return article.scholar_citation_count or 0, article.scholar_url, "stale"
    try:
        from scholarly import scholarly  # type: ignore

        pub = next(scholarly.search_pubs(title), None)
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
            article.doi = doi
        if work_url:
            article.crossref_work_url = work_url
    except Exception:
        status = "stale"
    try:
        count, url, sc_status = await fetch_scholar(article)
        article.scholar_citation_count = count
        if url:
            article.scholar_url = url
        if sc_status != "ok":
            status = sc_status
    except Exception:
        status = "stale"
    article.citation_synced_at = datetime.now(timezone.utc)
    article.citation_sync_status = status
    await db.flush()
    return article


sync_article_citations = sync_article_citations
