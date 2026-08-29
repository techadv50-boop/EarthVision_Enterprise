"""Crossref + Google Scholar cited-by counts (cached on Article)."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from html import unescape
from itertools import chain
from typing import Optional
from urllib.parse import quote, urlparse, parse_qs

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import get_settings
from app.models.citation import Article

CROSSREF = "https://api.crossref.org/works"
SCHOLAR = "https://scholar.google.com/scholar"
OPENCITATIONS_CITATIONS = "https://api.opencitations.net/index/v1/citations"
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


def _display_source(value: Optional[str]) -> Optional[str]:
    parts = _source_parts(value)
    if "scholar" in parts:
        return "scholar"
    if "crossref" in parts:
        return "crossref"
    return None


def _norm_title(value: Optional[str]) -> str:
    text = unescape(re.sub(r"<[^>]+>", " ", value or ""))
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return " ".join(text.split())


def _prefer_row(existing: dict, incoming: dict) -> dict:
    out = dict(existing)
    for field in ("authors", "year", "venue", "url", "doi", "title"):
        if not out.get(field) and incoming.get(field):
            out[field] = incoming[field]
    return out


def dedupe_citing_works(rows: list[dict], *, source: Optional[str] = None) -> list[dict]:
    """Keep one row per DOI, or per normalized title when a row has no DOI."""
    by_doi: dict[str, dict] = {}
    by_title: dict[str, dict] = {}
    untitled: list[dict] = []
    for raw in rows:
        if not raw:
            continue
        row = dict(raw)
        if source:
            row["source"] = source
        doi = normalize_doi(row.get("doi")) if row.get("doi") else None
        if doi:
            row["doi"] = doi
        title = (row.get("title") or "").strip() or doi or ""
        if not title:
            continue
        row["title"] = title
        if doi:
            key = doi.lower()
            by_doi[key] = _prefer_row(by_doi[key], row) if key in by_doi else row
            continue
        nt = _norm_title(title)
        if not nt:
            untitled.append(row)
            continue
        by_title[nt] = _prefer_row(by_title[nt], row) if nt in by_title else row

    doi_titles = {_norm_title(item.get("title")) for item in by_doi.values()}
    leftover = [item for item in by_title.values() if _norm_title(item.get("title")) not in doi_titles]
    out = list(by_doi.values()) + leftover + untitled

    def _sort_key(item: dict) -> tuple:
        year = item.get("year") or 0
        try:
            year_n = -int(year)
        except (TypeError, ValueError):
            year_n = 0
        return (year_n, (item.get("title") or "").lower())

    out.sort(key=_sort_key)
    return out


def merge_citing_works(*groups: list[dict]) -> list[dict]:
    """Dedupe within Crossref and within Scholar. Never mix the two sources."""
    by_source: dict[str, list[dict]] = {"crossref": [], "scholar": []}
    for row in chain.from_iterable(groups):
        if not row:
            continue
        source = _display_source(row.get("source"))
        if source is None:
            continue
        by_source[source].append(row)
    ordered: list[dict] = []
    for source in ("crossref", "scholar"):
        ordered.extend(dedupe_citing_works(by_source[source], source=source))
    return ordered


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


async def _hydrate_crossref_citing_doi(client: httpx.AsyncClient, citing_doi: str) -> dict:
    resp = await client.get(f"{CROSSREF}/{quote(citing_doi, safe=':/')}")
    if resp.status_code == 200:
        return citing_record_from_crossref(resp.json().get("message") or {})
    return _citing_record(source="crossref", title=citing_doi, doi=citing_doi)


async def _opencitations_citing_dois(client: httpx.AsyncClient, doi: str) -> list[str]:
    encoded = quote(doi, safe="")
    found: list[str] = []
    seen: set[str] = set()
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
        for citing in dois:
            key = citing.lower()
            if key not in seen:
                seen.add(key)
                found.append(citing)
    return found


async def _fetch_crossref_citing_works(client: httpx.AsyncClient, doi: str) -> list[dict]:
    """Citing articles from the Crossref citation graph (OpenCitations COCI)."""
    cited_key = doi.lower()
    found: list[str] = []
    seen: set[str] = set()
    for citing in await _opencitations_citing_dois(client, doi):
        key = citing.lower()
        if key == cited_key or key in seen:
            continue
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
    return dedupe_citing_works([row for row in rows if row], source="crossref")


def _scholar_cites_id(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    parsed = urlparse(url)
    cites = (parse_qs(parsed.query).get("cites") or [None])[0]
    if cites and str(cites).isdigit():
        return str(cites)
    return None


def _parse_gs_a(meta: str) -> tuple[str, int | None, str]:
    text = unescape(re.sub(r"<[^>]+>", "", meta or "")).replace("\xa0", " ").strip()
    authors = ""
    venue = ""
    year = None
    year_match = re.search(r"\b((?:19|20)\d{2})\b", text)
    if year_match:
        year = int(year_match.group(1))
    parts = [part.strip(" -") for part in re.split(r"\s+-\s+", text) if part.strip(" -")]
    if parts:
        authors = parts[0]
    if len(parts) >= 2:
        venue = re.sub(r"\b(?:19|20)\d{2}\b", "", parts[1]).strip(" ,-")
    return authors, year, venue


def parse_scholar_citing_html(html: str) -> list[dict]:
    """Parse citing articles from a Google Scholar cited-by results page."""
    rows: list[dict] = []
    seen: set[str] = set()
    pattern = re.compile(
        r'<div class="gs_ri">\s*<h3 class="gs_rt">(.*?)</h3>\s*<div class="gs_a">(.*?)</div>',
        re.I | re.S,
    )
    for match in pattern.finditer(html or ""):
        rt, meta = match.group(1), match.group(2)
        href = None
        link = re.search(r'<a[^>]+href="([^"]+)"', rt, re.I)
        if link:
            href = unescape(link.group(1))
            if href.startswith("/"):
                href = "https://scholar.google.com" + href
        title = unescape(re.sub(r"<[^>]+>", " ", rt)).strip()
        title = re.sub(r"\s+", " ", title)
        if not title:
            continue
        key = _norm_title(title)
        if key in seen:
            continue
        seen.add(key)
        authors, year, venue = _parse_gs_a(meta)
        doi = normalize_doi(href) if href and "doi.org/" in href else None
        rows.append(
            _citing_record(
                source="scholar",
                title=title,
                authors=authors,
                year=year,
                venue=venue,
                doi=doi,
                url=href,
            )
        )
    return rows


def parse_serpapi_scholar_citing(payload: dict) -> list[dict]:
    rows: list[dict] = []
    for item in payload.get("organic_results") or []:
        title = (item.get("title") or "").strip()
        if not title:
            continue
        info = item.get("publication_info") or {}
        authors = ""
        names = info.get("authors") or []
        if isinstance(names, list):
            authors = ", ".join(
                (person.get("name") or "").strip() for person in names if isinstance(person, dict) and person.get("name")
            )
        summary = info.get("summary") or ""
        meta_authors, year, venue = _parse_gs_a(summary)
        rows.append(
            _citing_record(
                source="scholar",
                title=title,
                authors=authors or meta_authors,
                year=year,
                venue=venue,
                url=item.get("link"),
            )
        )
    return dedupe_citing_works(rows, source="scholar")


async def _scholar_cited_by_url(article: Article) -> Optional[str]:
    url = getattr(article, "scholar_url", None)
    cites = _scholar_cites_id(url)
    if cites:
        return f"{SCHOLAR}?cites={cites}&hl=en"
    if not url:
        return None
    headers = {"User-Agent": BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"}
    async with httpx.AsyncClient(timeout=20.0, headers=headers, follow_redirects=True) as client:
        resp = await client.get(url)
        if resp.status_code != 200:
            return None
        found = SCHOLAR_CITES_RE.search(resp.text or "")
        if not found:
            return None
        link = found.group(1)
        if link.startswith("/"):
            link = "https://scholar.google.com" + link
        return link


async def _fetch_scholar_citing_html(cited_by_url: str) -> list[dict]:
    headers = {"User-Agent": BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"}
    rows: list[dict] = []
    async with httpx.AsyncClient(timeout=20.0, headers=headers, follow_redirects=True) as client:
        parsed = urlparse(cited_by_url)
        query = parse_qs(parsed.query)
        cites = (query.get("cites") or [None])[0]
        for start in (0, 10):
            if cites:
                resp = await client.get(SCHOLAR, params={"cites": cites, "hl": "en", "start": start})
            else:
                resp = await client.get(cited_by_url, params={"start": start} if start else None)
            if resp.status_code != 200:
                break
            page = parse_scholar_citing_html(resp.text or "")
            if not page:
                break
            rows.extend(page)
            if len(page) < 10:
                break
    return dedupe_citing_works(rows, source="scholar")


async def _fetch_scholar_citing_works(article: Article) -> list[dict]:
    """Citing articles from Google Scholar only. Does not change fetch_scholar() counts."""
    settings = get_settings()
    api_key = getattr(settings, "serpapi_key", "") or ""
    cites = _scholar_cites_id(getattr(article, "scholar_url", None))
    if api_key and cites:
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(
                    "https://serpapi.com/search.json",
                    params={"engine": "google_scholar", "cites": cites, "api_key": api_key},
                )
            if resp.status_code == 200:
                rows = parse_serpapi_scholar_citing(resp.json() or {})
                if rows:
                    return rows
        except Exception:
            pass
    cited_by = await _scholar_cited_by_url(article)
    if not cited_by:
        return []
    try:
        return await _fetch_scholar_citing_html(cited_by)
    except Exception:
        return []


async def fetch_citing_works(article: Article) -> list[dict]:
    """Return works that cite this article: Crossref list, then Google Scholar list.

    Duplicate DOIs/titles are dropped within each source so the same paper
    is not listed two or three times.
    """
    doi = normalize_doi(article.doi)
    crossref_rows: list[dict] = []
    scholar_rows: list[dict] = []
    if doi:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(25.0), headers=_crossref_headers(), follow_redirects=True
        ) as client:
            try:
                crossref_rows = await _fetch_crossref_citing_works(client, doi)
            except Exception:
                crossref_rows = []
    try:
        scholar_rows = await _fetch_scholar_citing_works(article)
    except Exception:
        scholar_rows = []
    return merge_citing_works(crossref_rows, scholar_rows)


async def fetch_crossref(article: Article) -> tuple[int, Optional[str], Optional[str]]:
    """Cited-by count from an exact Crossref DOI lookup only.

    Never searches by title or bibliography, and never reuses
    previously stored citation counts when the lookup fails.
    """
    requested_doi = normalize_doi(article.doi)
    if not requested_doi:
        return 0, None, None
    timeout = httpx.Timeout(20.0)
    async with httpx.AsyncClient(timeout=timeout, headers=_crossref_headers(), follow_redirects=True) as client:
        resp = await client.get(f"{CROSSREF}/{quote(requested_doi, safe=':/')}")
        if resp.status_code != 200:
            return 0, None, None
        msg = resp.json().get("message") or {}
        returned_doi = normalize_doi(msg.get("DOI"))
        if not returned_doi or returned_doi.lower() != requested_doi.lower():
            return 0, None, None
        work_url = msg.get("URL") or f"https://doi.org/{returned_doi}"
        return int(msg.get("is-referenced-by-count") or 0), returned_doi, work_url


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
