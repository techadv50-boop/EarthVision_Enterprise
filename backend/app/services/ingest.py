"""Save PDFs into the journal → volume → issue archive and embed their text."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.citation import Article, ArticleChunk, Issue, Journal
from app.services.citation_parser import parse_ijist_header, split_paragraphs
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


async def ingest_article_text(
    db: AsyncSession,
    journal: Journal,
    text: str,
    *,
    pdf_path: Optional[str] = None,
    source_url: Optional[str] = None,
    ocr_status: str = "extracted",
    original_filename: Optional[str] = None,
) -> tuple[Article, bool]:
    meta = parse_ijist_header(text)
    volume = int(meta.get("volume") or 0)
    issue_no = int(meta.get("issue") or 0)
    page_start = int(meta.get("page_start") or 0) or 1

    issue = await get_or_create_issue(
        db,
        journal.id,
        volume,
        issue_no,
        year=meta.get("year"),
        month=meta.get("month"),
    )

    existing = None
    if meta.get("doi"):
        found = await db.execute(select(Article).where(Article.doi == meta["doi"]))
        existing = found.scalar_one_or_none()
    if existing is None:
        found = await db.execute(
            select(Article).where(Article.issue_id == issue.id, Article.page_start == page_start)
        )
        existing = found.scalar_one_or_none()

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
) -> tuple[Article, bool]:
    text, ocr_status = extract_pdf_text(data)
    if not text.strip():
        text = f"Untitled article from {filename}"
        ocr_status = "empty"
    meta = parse_ijist_header(text)
    dest = archive_pdf_path(
        journal.id, int(meta.get("volume") or 0), int(meta.get("issue") or 0), filename
    )
    dest.write_bytes(data)
    return await ingest_article_text(
        db,
        journal,
        text,
        pdf_path=str(dest),
        source_url=source_url,
        ocr_status=ocr_status,
        original_filename=filename,
    )


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
