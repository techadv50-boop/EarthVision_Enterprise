"""Crossref + Google Scholar cited-by counts (cached on Article)."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from itertools import chain
from typing import Optional
from urllib.parse import quote

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import get_settings
from app.models.citation import Article

CROSSREF = "https://api.crossref.org/works"
OPENALEX = "https://api.openalex.org/works"
SCHOLAR = "https://scholar.google.com/scholar"
OPENCITATIONS_CITATIONS = "https://api.opencitations.net/index/v1/citations"
SOURCE_RANK = {"crossref": 0, "openalex": 1, "scholar": 2}
DOI_PREFIX_RE = re.compile(r"^(https?://)?(dx\.)?doi\.org/", re.I)
CITED_BY_RE = re.compile(r"Cited by\s+(\d+)", re.I)
SCHOLAR_CITES_RE = re.compile(
    r'href="(https?://scholar\.google\.[^"]*?/scholar\?[^"]*cites=\d+[^"]*|/scholar\?[^"]*cites=\d+[^"]*)"',
    re.I,
)
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


def _openalex_headers() -> dict[str, str]:
    settings = get_settings()
    mail = getattr(settings, "crossref_mailto", None) or "citation-assistant@example.com"
    return {"User-Agent": f"CitationAssistant/1.0 (mailto:{mail})"}


def _citing_record(
    *,
    source: str,
    title: str,
    authors: str = "",
    year: int | None = None,
    venue: str = "",
    doi: str | None = None,
    url: str | None = None,
) -> dict:
    doi = normalize_doi(doi) if doi else None
    return {
        "source": source,
        "title": title,
        "authors": authors,
        "year": year,
        "venue": venue,
        "doi": doi,
        "url": url or (f"https://doi.org/{doi}" if doi else None),
    }


def _openalex_authors(work: dict) -> str:
    names = []
    for item in work.get("authorships") or []:
        name = ((item.get("author") or {}).get("display_name") or "").strip()
        if name:
            names.append(name)
        if len(names) >= 8:
            break
    return ", ".join(names)


def _from_openalex_work(work: dict) -> dict:
    doi = (work.get("ids") or {}).get("doi") or work.get("doi")
    loc = work.get("primary_location") or {}
    venue = ((loc.get("source") or {}).get("display_name") or "").strip()
    url = loc.get("landing_page_url") or (work.get("ids") or {}).get("doi") or work.get("id")
    return _citing_record(
        source="openalex",
        title=(work.get("display_name") or work.get("title") or "").strip(),
        authors=_openalex_authors(work),
        year=work.get("publication_year"),
        venue=venue,
        doi=doi,
        url=url,
    )


def _crossref_authors(msg: dict) -> str:
    names = []
    for item in msg.get("author") or []:
        given = (item.get("given") or "").strip()
        family = (item.get("family") or "").strip()
        name = " ".join(part for part in (given, family) if part) or (item.get("name") or "").strip()
        if name:
            names.append(name)
        if len(names) >= 8:
            break
    return ", ".join(names)


def _crossref_year(msg: dict) -> int | None:
    for key in ("published-print", "published-online", "published", "issued", "created"):
        parts = ((msg.get(key) or {}).get("date-parts") or [[None]])[0]
        if parts and parts[0]:
            try:
                return int(parts[0])
            except (TypeError, ValueError):
                continue
    return None


def citing_record_from_crossref(msg: dict) -> dict:
    """Build a citing-work row from a Crossref `/works` message."""
    title = msg.get("title")
    if isinstance(title, list):
        title = title[0] if title else ""
    venue = msg.get("container-title")
    if isinstance(venue, list):
        venue = venue[0] if venue else ""
    doi = normalize_doi(msg.get("DOI"))
    return _citing_record(
        source="crossref",
        title=(str(title or "").strip() or doi or "Untitled citing work"),
        authors=_crossref_authors(msg),
        year=_crossref_year(msg),
        venue=str(venue or "").strip(),
        doi=doi,
        url=msg.get("URL"),
    )


def _source_parts(value: Optional[str]) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def merge_citing_works(*groups: list[dict]) -> list[dict]:
    """Dedupe citing records by DOI/title and keep Crossref rows first."""
    by_key: dict[str, dict] = {}
    for row in chain.from_iterable(groups):
        if not row:
            continue
        doi = normalize_doi(row.get("doi")) if row.get("doi") else None
        title = (row.get("title") or "").strip() or doi or ""
        if not title:
            continue
        merged = dict(row)
        merged["title"] = title
        if doi:
            merged["doi"] = doi
        key = (doi or title).lower()
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = merged
            continue
        sources: list[str] = []
        for part in _source_parts(existing.get("source")) + _source_parts(merged.get("source")):
            if part not in sources:
                sources.append(part)
        existing["source"] = ",".join(sources)
        prefer_incoming = "crossref" in _source_parts(merged.get("source")) and "crossref" not in _source_parts(
            existing.get("source")
        )
        for field in ("authors", "year", "venue", "url", "doi", "title"):
            if prefer_incoming and merged.get(field):
                existing[field] = merged[field]
            elif not existing.get(field) and merged.get(field):
                existing[field] = merged[field]
    rows = list(by_key.values())

    def _sort_key(item: dict) -> tuple:
        sources = _source_parts(item.get("source"))
        rank = min((SOURCE_RANK.get(source, 9) for source in sources), default=9)
        year = item.get("year") or 0
        try:
            year_n = -int(year)
        except (TypeError, ValueError):
            year_n = 0
        return (rank, year_n, (item.get("title") or "").lower())

    rows.sort(key=_sort_key)
    return rows


def _citing_dois_from_opencitations(payload) -> list[str]:
    rows = payload if isinstance(payload, list) else []
    dois: list[str] = []
    seen: set[str] = set()
    for row in rows:
        citing = row.get("citing") or row.get("citing_doi") or ""
        citing = re.sub(r"^doi:", "", str(citing), flags=re.I).strip()
        doi = normalize_doi(citing)
        if doi and doi.lower() not in seen:
            seen.add(doi.lower())
            dois.append(doi)
    return dois


async def _fetch_openalex_citing_works(client: httpx.AsyncClient, doi: Optional[str], title: str) -> list[dict]:
    work = None
    if doi:
        resp = await client.get(f"{OPENALEX}/doi:{doi}")
        if resp.status_code == 200:
            work = resp.json()
    if work is None and title:
        resp = await client.get(OPENALEX, params={"search": title, "per-page": 5})
        if resp.status_code == 200:
            for item in resp.json().get("results") or []:
                if _title_overlap(title, item.get("display_name") or item.get("title") or ""):
                    work = item
                    break
    if not work:
        return []
    oid = str(work.get("id") or "").rsplit("/", 1)[-1]
    if not oid:
        return []
    cited = await client.get(
        OPENALEX,
        params={"filter": f"cites:{oid}", "per-page": 50, "sort": "publication_year:desc"},
    )
    if cited.status_code != 200:
        return []
    return [_from_openalex_work(item) for item in cited.json().get("results") or []]


async def _hydrate_crossref_citing_doi(client: httpx.AsyncClient, citing_doi: str) -> dict:
    resp = await client.get(f"{CROSSREF}/{quote(citing_doi, safe=':/')}")
    if resp.status_code == 200:
        return citing_record_from_crossref(resp.json().get("message") or {})
    return _citing_record(source="crossref", title=citing_doi, doi=citing_doi)


async def _opencitations_citing_dois(client: httpx.AsyncClient, doi: str) -> list[str]:
    encoded = quote(doi, safe="")
    for url in (
        f"{OPENCITATIONS_CITATIONS}/{encoded}",
        f"https://opencitations.net/index/coci/api/v1/citations/{encoded}",
        f"https://opencitations.net/index/api/v1/citations/{encoded}",
    ):
        try:
            resp = await client.get(url)
        except Exception:
            continue
        if resp.status_code != 200:
            continue
        try:
            dois = _citing_dois_from_opencitations(resp.json())
        except Exception:
            continue
        if dois:
            return dois
    return []


async def _fetch_crossref_citing_works(client: httpx.AsyncClient, doi: str) -> list[dict]:
    """Citing articles from the Crossref citation graph (OpenCitations COCI)."""
    found: list[str] = []
    seen: set[str] = set()
    for citing in await _opencitations_citing_dois(client, doi):
        key = citing.lower()
        if key not in seen:
            seen.add(key)
            found.append(citing)
    if not found:
        return []
    sem = asyncio.Semaphore(5)

    async def _one(citing_doi: str) -> dict:
        async with sem:
            try:
                return await _hydrate_crossref_citing_doi(client, citing_doi)
            except Exception:
                return _citing_record(source="crossref", title=citing_doi, doi=citing_doi)

    rows = await asyncio.gather(*[_one(citing_doi) for citing_doi in found[:50]])
    return [row for row in rows if row]


async def fetch_citing_works(article: Article) -> list[dict]:
    """Return works that cite this article (Crossref + OpenAlex) so the operator can open them."""
    doi = normalize_doi(article.doi)
    title = (article.title or "").strip()
    openalex_rows: list[dict] = []
    crossref_rows: list[dict] = []
    headers = {**_crossref_headers(), **_openalex_headers()}
    async with httpx.AsyncClient(timeout=httpx.Timeout(25.0), headers=headers, follow_redirects=True) as client:
        try:
            openalex_rows = await _fetch_openalex_citing_works(client, doi, title)
        except Exception:
            openalex_rows = []
        if doi:
            try:
                crossref_rows = await _fetch_crossref_citing_works(client, doi)
            except Exception:
                crossref_rows = []
    return merge_citing_works(crossref_rows, openalex_rows)


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
            cites = SCHOLAR_CITES_RE.search(resp.text or "")
            if cites:
                link = cites.group(1)
                if link.startswith("/"):
                    link = "https://scholar.google.com" + link
            else:
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
    try:
        article.citing_works = await fetch_citing_works(article)
        flag_modified(article, "citing_works")
    except Exception:
        if not article.citing_works:
            article.citing_works = []
        if status == "ok":
            status = "partial"
    article.citation_synced_at = datetime.now(timezone.utc)
    article.citation_sync_status = status
    await db.flush()
    return article
