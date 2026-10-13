"""Save PDFs into the journal → volume → issue archive and embed their text."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.citation import Article, ArticleChunk, Issue, Journal
from app.services.citation_parser import (
    article_id_from_url,
    parse_ijist_header,
    parse_volume_issue,
    split_paragraphs,
)
from app.services.embeddings import embed_text
from app.services.pdf_text import extract_pdf_text


async def get_or_create_issue(
    db: AsyncSession,
    journal_id: int,
    volume: int,
    issue_number: int,
    *,
    year: Optional[int] = None,
    month: Optional[str] = None,
) -> Issue:
    result = await db.execute(
        select(Issue).where(
            Issue.journal_id == journal_id,
            Issue.volume == volume,
            Issue.issue_number == issue_number,
        )
    )
    issue = result.scalar_one_or_none()
    if issue:
        if year and not issue.year:
            issue.year = year
        if month and not issue.month:
            issue.month = month
        return issue
    issue = Issue(
        journal_id=journal_id,
        volume=volume,
        issue_number=issue_number,
        year=year,
        month=month,
    )
    db.add(issue)
    await db.flush()
    return issue


def resolve_placement(
    text: str = "",
    *,
    filename: Optional[str] = None,
    source_url: Optional[str] = None,
    volume: Optional[int] = None,
    issue_number: Optional[int] = None,
    year: Optional[int] = None,
    inventory: Optional[list[dict[str, Any]]] = None,
) -> tuple[int, int, Optional[int]]:
    """Header first, then caller hints, inventory, filename/URL — never invent volume 0 when a rack is known."""
    meta = parse_ijist_header(text or "")
    hint_vol, hint_iss, hint_year = parse_volume_issue(
        filename or "",
        source_url or "",
        Path(filename or "").stem,
    )
    inv_vol, inv_iss, inv_year = placement_from_inventory(source_url, inventory)
    parsed_vol = meta.get("volume")
    parsed_iss = meta.get("issue")
    parsed_year = meta.get("year")
    vol = _first_positive(parsed_vol, volume, inv_vol, hint_vol)
    iss = _first_positive(parsed_iss, issue_number, inv_iss, hint_iss)
    year_out = _first_positive(parsed_year, year, inv_year, hint_year)
    return int(vol or 0), int(iss or 0), year_out


def _first_positive(*values: Any) -> Optional[int]:
    for value in values:
        if value is None or value == "":
            continue
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            return number
    return None


def _norm_match(url: str) -> str:
    return (url or "").rstrip("/").lower()


def placement_from_inventory(
    source_url: Optional[str], inventory: Optional[list[dict[str, Any]]]
) -> tuple[Optional[int], Optional[int], Optional[int]]:
    if not source_url or not inventory:
        return None, None, None
    needle = _norm_match(source_url)
    article_id = article_id_from_url(source_url)
    for row in inventory:
        urls = [row.get("url"), *(row.get("pdf_urls") or []), *(row.get("article_urls") or [])]
        for url in urls:
            if not url:
                continue
            if _norm_match(str(url)) == needle:
                return (
                    _first_positive(row.get("volume")),
                    _first_positive(row.get("issue_number")),
                    _first_positive(row.get("year")),
                )
            if article_id and article_id_from_url(str(url)) == article_id:
                return (
                    _first_positive(row.get("volume")),
                    _first_positive(row.get("issue_number")),
                    _first_positive(row.get("year")),
                )
    return None, None, None


async def ingest_article_text(
    db: AsyncSession,
    journal: Journal,
    text: str,
    *,
    pdf_path: Optional[str] = None,
    source_url: Optional[str] = None,
    ocr_status: str = "extracted",
    original_filename: Optional[str] = None,
    volume: Optional[int] = None,
    issue_number: Optional[int] = None,
    year: Optional[int] = None,
    month: Optional[str] = None,
    inventory: Optional[list[dict[str, Any]]] = None,
) -> tuple[Article, bool]:
    meta = parse_ijist_header(text)
    volume_no, issue_no, year_no = resolve_placement(
        text,
        filename=original_filename,
        source_url=source_url,
        volume=volume,
        issue_number=issue_number,
        year=year,
        inventory=inventory,
    )
    page_start = int(meta.get("page_start") or 0) or 1

    issue = await get_or_create_issue(
        db,
        journal.id,
        volume_no,
        issue_no,
        year=year_no or meta.get("year"),
        month=month or meta.get("month"),
    )

    existing = None
    if meta.get("doi"):
        found = await db.execute(select(Article).where(Article.doi == meta["doi"]))
        existing = found.scalar_one_or_none()
    if existing is None and source_url:
        found = await db.execute(select(Article).where(Article.source_url == source_url))
        existing = found.scalar_one_or_none()
    if existing is None:
        found = await db.execute(
            select(Article).where(Article.issue_id == issue.id, Article.page_start == page_start)
        )
        existing = found.scalar_one_or_none()
    page_start = await _free_page_start(db, issue.id, page_start, keep_id=existing.id if existing else None)

    title = meta.get("title") or (original_filename or "Untitled article")
    authors = meta.get("authors") or []
    payload = dict(
        title=title,
        authors=authors,
        affiliations=meta.get("affiliations") or [],
        correspondence_email=meta.get("correspondence_email"),
        citation_raw=meta.get("citation_raw"),
        page_end=meta.get("page_end"),
        received_date=meta.get("received_date"),
        revised_date=meta.get("revised_date"),
        accepted_date=meta.get("accepted_date"),
        published_date=meta.get("published_date"),
        keywords=meta.get("keywords") or [],
        abstract=meta.get("abstract"),
        full_text=text,
        pdf_path=pdf_path,
        source_url=source_url,
        ocr_status=ocr_status,
        header_raw=meta.get("header_raw"),
        doi=meta.get("doi"),
    )

    if existing:
        for key, value in payload.items():
            if key == "pdf_path" and not value:
                continue
            if key == "source_url" and not value:
                continue
            setattr(existing, key, value)
        existing.page_start = page_start
        if existing.issue_id != issue.id:
            existing.issue_id = issue.id
        article = existing
        created = False
        await db.execute(delete(ArticleChunk).where(ArticleChunk.article_id == article.id))
        await db.flush()
    else:
        article = Article(issue_id=issue.id, page_start=page_start, **payload)
        db.add(article)
        await db.flush()
        created = True

    paras = split_paragraphs(text)
    if not paras:
        paras = [p for p in (meta.get("abstract"), title) if p]
    for idx, para in enumerate(paras):
        db.add(
            ArticleChunk(
                article_id=article.id,
                paragraph_index=idx,
                text=para,
                embedding=embed_text(para),
            )
        )
    await db.flush()
    return article, created


def archive_pdf_path(journal_id: int, volume: int, issue: int, filename: str) -> Path:
    settings = get_settings()
    safe = Path(filename).name.replace(" ", "_")
    dest_dir = (
        Path(settings.upload_dir)
        / "archive"
        / "journals"
        / str(journal_id)
        / f"vol{volume}"
        / f"issue{issue}"
    )
    dest_dir.mkdir(parents=True, exist_ok=True)
    return dest_dir / safe


async def ingest_pdf_bytes(
    db: AsyncSession,
    journal: Journal,
    data: bytes,
    filename: str,
    *,
    source_url: Optional[str] = None,
    volume: Optional[int] = None,
    issue_number: Optional[int] = None,
    year: Optional[int] = None,
    inventory: Optional[list[dict[str, Any]]] = None,
) -> tuple[Article, bool]:
    text, ocr_status = extract_pdf_text(data)
    if not text.strip():
        text = f"Untitled article from {filename}"
        ocr_status = "empty"
    vol, iss, year_no = resolve_placement(
        text,
        filename=filename,
        source_url=source_url,
        volume=volume,
        issue_number=issue_number,
        year=year,
        inventory=inventory,
    )
    dest = archive_pdf_path(journal.id, vol, iss, filename)
    dest.write_bytes(data)
    return await ingest_article_text(
        db,
        journal,
        text,
        pdf_path=str(dest),
        source_url=source_url,
        ocr_status=ocr_status,
        original_filename=filename,
        volume=vol,
        issue_number=iss,
        year=year_no,
        inventory=inventory,
    )


async def _free_page_start(
    db: AsyncSession, issue_id: int, page_start: int, *, keep_id: Optional[int] = None
) -> int:
    taken = {
        int(row)
        for row in (
            await db.execute(select(Article.page_start).where(Article.issue_id == issue_id))
        ).scalars().all()
        if row is not None
    }
    if keep_id:
        current = await db.get(Article, keep_id)
        if current is not None and current.issue_id == issue_id and current.page_start is not None:
            taken.discard(int(current.page_start))
    candidate = max(1, page_start)
    while candidate in taken:
        candidate += 1
    return candidate


def _relocate_pdf(article: Article, journal_id: int, volume: int, issue_number: int) -> None:
    path = article.pdf_path
    if not path:
        return
    src = Path(path)
    dest = archive_pdf_path(journal_id, volume, issue_number, src.name or "article.pdf")
    if dest.resolve() == src.resolve():
        return
    if src.exists():
        dest.write_bytes(src.read_bytes())
    article.pdf_path = str(dest)


async def refile_unfiled_articles(
    db: AsyncSession,
    journal: Journal,
    inventory: Optional[list[dict[str, Any]]] = None,
) -> dict[str, int]:
    """Move volume/issue 0 dumps into the racks named by header, filename, or crawl inventory."""
    unfiled = list(
        (
            await db.execute(
                select(Issue).where(Issue.journal_id == journal.id, Issue.volume == 0)
            )
        ).scalars().all()
    )
    moved = 0
    remaining = 0
    for issue in unfiled:
        articles = list(
            (await db.execute(select(Article).where(Article.issue_id == issue.id))).scalars().all()
        )
        for article in articles:
            vol, iss, year_no = resolve_placement(
                article.full_text or article.header_raw or "",
                filename=Path(article.pdf_path or "").name,
                source_url=article.source_url,
                inventory=inventory,
            )
            if vol <= 0 or iss <= 0:
                remaining += 1
                continue
            target = await get_or_create_issue(
                db,
                journal.id,
                vol,
                iss,
                year=year_no or issue.year,
                month=issue.month,
            )
            if target.id == issue.id:
                remaining += 1
                continue
            article.page_start = await _free_page_start(
                db, target.id, article.page_start or 1, keep_id=article.id
            )
            article.issue_id = target.id
            _relocate_pdf(article, journal.id, vol, iss)
            moved += 1
        await db.flush()
    return {"moved": moved, "remaining": remaining}


def compute_issue_coverage(articles: list[Article], issue: Issue) -> dict[str, Any]:
    rows = sorted(articles, key=lambda a: a.page_start or 0)
    present = []
    gaps = []
    overlaps = []
    prev_end: Optional[int] = None
    prev_id: Optional[int] = None
    for art in rows:
        start = art.page_start
        end = art.page_end or art.page_start
        present.append(
            {
                "article_id": art.id,
                "page_start": start,
                "page_end": end,
                "title": art.title,
            }
        )
        if prev_end is not None:
            if start <= prev_end:
                overlaps.append(
                    {
                        "from_article_id": prev_id,
                        "to_article_id": art.id,
                        "page_start": start,
                        "page_end": prev_end,
                    }
                )
            elif start > prev_end + 1:
                gaps.append({"page_start": prev_end + 1, "page_end": start - 1})
        prev_end = max(prev_end or 0, end)
        prev_id = art.id

    if issue.expected_page_start and rows and rows[0].page_start > issue.expected_page_start:
        gaps.insert(
            0, {"page_start": issue.expected_page_start, "page_end": rows[0].page_start - 1}
        )
    if issue.expected_page_end and prev_end is not None and prev_end < issue.expected_page_end:
        gaps.append({"page_start": prev_end + 1, "page_end": issue.expected_page_end})

    return {
        "present": present,
        "gaps": gaps,
        "overlaps": overlaps,
        "article_count": len(rows),
    }


ingest_article_text = ingest_article_text
ingest_pdf_bytes = ingest_pdf_bytes
compute_issue_coverage = compute_issue_coverage
