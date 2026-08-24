"""Citation assistant HTTP API."""

from __future__ import annotations

from collections import defaultdict
from typing import Annotated, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.dependencies import get_current_user
from app.database.session import get_db
from app.models.citation import (
    Article,
    CrawlJob,
    Issue,
    Journal,
    Manuscript,
    ManuscriptParagraph,
    CitationSuggestion,
)
from app.models.user import User
from app.schemas.citation import (
    ArticleOut,
    ArticlePatch,
    CoverageOut,
    CrawlDownloadIn,
    CrawlJobOut,
    CrawlStart,
    IssueStatsOut,
    JournalCreate,
    JournalOut,
    JournalUpdate,
    ManuscriptDetail,
    ManuscriptOut,
    ParagraphOut,
    ReferenceOut,
    SuggestionOut,
    SuggestionPatch,
    TextPaperIn,
    VolumeOut,
)
from app.services.citation_counts import sync_article_citations
from app.services.crawler import run_crawl_job, run_download_job
from app.services.ingest import compute_issue_coverage, ingest_article_text, ingest_pdf_bytes
from app.services.matcher import house_citation_for, suggest_for_manuscript
from app.services.manuscript_export import assign_citations, build_amended_docx
from app.services.manuscript_text import extract_manuscript_text, suffix_for

router = APIRouter(tags=["Citation Assistant"])

Db = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


def _article_out(article: Article) -> ArticleOut:
    issue = article.issue
    return ArticleOut(
        id=article.id,
        issue_id=article.issue_id,
        volume=issue.volume if issue else None,
        issue_number=issue.issue_number if issue else None,
        page_start=article.page_start,
        page_end=article.page_end,
        title=article.title,
        authors=article.authors or [],
        affiliations=article.affiliations or [],
        correspondence_email=article.correspondence_email,
        citation_raw=article.citation_raw,
        received_date=article.received_date,
        revised_date=article.revised_date,
        accepted_date=article.accepted_date,
        published_date=article.published_date,
        keywords=article.keywords or [],
        abstract=article.abstract,
        doi=article.doi,
        ocr_status=article.ocr_status,
        pdf_path=article.pdf_path,
        source_url=article.source_url,
        crossref_citation_count=article.crossref_citation_count or 0,
        scholar_citation_count=article.scholar_citation_count or 0,
        citation_synced_at=article.citation_synced_at,
        citation_sync_status=article.citation_sync_status,
        crossref_work_url=article.crossref_work_url,
        scholar_url=article.scholar_url,
        citing_works=article.citing_works or [],
        house_citation=house_citation_for(article) if issue else None,
    )


async def _journal_or_404(db: AsyncSession, journal_id: int) -> Journal:
    journal = await db.get(Journal, journal_id)
    if journal is None:
        raise HTTPException(status_code=404, detail="Journal not found")
    return journal


def _is_cited(article: Article) -> bool:
    return (article.scholar_citation_count or 0) > 0 or (article.crossref_citation_count or 0) > 0


def _issue_stats(issue: Issue, arts: list[Article]) -> IssueStatsOut:
    cited = [a for a in arts if _is_cited(a)]
    return IssueStatsOut(
        id=issue.id,
        volume=issue.volume,
        issue_number=issue.issue_number,
        year=issue.year,
        month=issue.month,
        article_count=len(arts),
        cited_count=len(cited),
        uncited_count=len(arts) - len(cited),
        scholar_total=sum(a.scholar_citation_count or 0 for a in arts),
        crossref_total=sum(a.crossref_citation_count or 0 for a in arts),
        citations_synced=bool(arts) and all(a.citation_synced_at for a in arts),
    )


@router.post("/journals", response_model=JournalOut, status_code=status.HTTP_201_CREATED)
async def create_journal(body: JournalCreate, db: Db, _user: CurrentUser):
    taken = await db.execute(
        select(Journal).where(func.lower(Journal.name) == body.name.strip().lower())
    )
    if taken.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail="A journal with this name already exists. Open that card instead of adding it again.",
        )
    journal = Journal(
        name=body.name.strip(),
        abbreviation=body.abbreviation,
        publisher=body.publisher,
        issn=body.issn,
        archive_url=body.archive_url,
    )
    db.add(journal)
    await db.flush()
    return JournalOut.model_validate(journal).model_copy(
        update={"article_count": 0, "volume_count": 0, "has_gaps": False}
    )


@router.get("/journals", response_model=list[JournalOut])
async def list_journals(db: Db, _user: CurrentUser):
    result = await db.execute(select(Journal).order_by(Journal.name))
    journals = list(result.scalars().all())
    out: list[JournalOut] = []
    for journal in journals:
        issues_res = await db.execute(select(Issue).where(Issue.journal_id == journal.id))
        issues = list(issues_res.scalars().all())
        vols = {i.volume for i in issues}
        count_res = await db.execute(
            select(func.count(Article.id))
            .join(Issue, Article.issue_id == Issue.id)
            .where(Issue.journal_id == journal.id)
        )
        article_count = int(count_res.scalar() or 0)
        has_gaps = False
        if vols:
            expected = set(range(min(vols), max(vols) + 1))
            if expected - vols:
                has_gaps = True
        for issue in issues:
            arts = (
                await db.execute(select(Article).where(Article.issue_id == issue.id))
            ).scalars().all()
            cov = compute_issue_coverage(list(arts), issue)
            if cov["gaps"]:
                has_gaps = True
        out.append(
            JournalOut(
                id=journal.id,
                name=journal.name,
                abbreviation=journal.abbreviation,
                publisher=journal.publisher,
                issn=journal.issn,
                archive_url=journal.archive_url,
                article_count=article_count,
                volume_count=len(vols),
                has_gaps=has_gaps,
                created_at=journal.created_at,
            )
        )
    return out


@router.get("/journals/{journal_id}", response_model=JournalOut)
async def get_journal(journal_id: int, db: Db, _user: CurrentUser):
    rows = await list_journals(db, _user)
    for row in rows:
        if row.id == journal_id:
            return row
    raise HTTPException(status_code=404, detail="Journal not found")


@router.patch("/journals/{journal_id}", response_model=JournalOut)
async def update_journal(journal_id: int, body: JournalUpdate, db: Db, _user: CurrentUser):
    journal = await _journal_or_404(db, journal_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(journal, field, value)
    await db.flush()
    return await get_journal(journal_id, db, _user)


@router.delete("/journals/{journal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_journal(journal_id: int, db: Db, _user: CurrentUser):
    journal = await _journal_or_404(db, journal_id)
    await db.delete(journal)
    await db.flush()


@router.get("/journals/{journal_id}/volumes", response_model=list[VolumeOut])
async def list_volumes(journal_id: int, db: Db, _user: CurrentUser):
    await _journal_or_404(db, journal_id)
    issues = list(
        (await db.execute(select(Issue).where(Issue.journal_id == journal_id))).scalars().all()
    )
    by_vol: dict[int, list[Issue]] = defaultdict(list)
    for issue in issues:
        by_vol[issue.volume].append(issue)
    volumes = sorted(by_vol)
    out: list[VolumeOut] = []
    if volumes:
        for missing in range(volumes[0], volumes[-1] + 1):
            if missing not in by_vol:
                out.append(VolumeOut(volume=missing, article_count=0, issue_count=0, missing=True))
                continue
            group = by_vol[missing]
            years = [i.year for i in group if i.year]
            count_res = await db.execute(
                select(func.count(Article.id))
                .join(Issue, Article.issue_id == Issue.id)
                .where(Issue.journal_id == journal_id, Issue.volume == missing)
            )
            out.append(
                VolumeOut(
                    volume=missing,
                    year_start=min(years) if years else None,
                    year_end=max(years) if years else None,
                    article_count=int(count_res.scalar() or 0),
                    issue_count=len(group),
                    missing=False,
                )
            )
    return out


@router.get("/journals/{journal_id}/issues", response_model=list[IssueStatsOut])
async def list_journal_issues(journal_id: int, db: Db, _user: CurrentUser):
    await _journal_or_404(db, journal_id)
    issues = list(
        (
            await db.execute(
                select(Issue)
                .where(Issue.journal_id == journal_id)
                .order_by(Issue.volume.desc(), Issue.issue_number.desc())
            )
        ).scalars().all()
    )
    out: list[IssueStatsOut] = []
    for issue in issues:
        arts = list(
            (await db.execute(select(Article).where(Article.issue_id == issue.id))).scalars().all()
        )
        out.append(_issue_stats(issue, arts))
    return out


@router.get(
    "/journals/{journal_id}/volumes/{volume}/issues",
    response_model=list[IssueStatsOut],
)
async def list_issues(journal_id: int, volume: int, db: Db, _user: CurrentUser):
    await _journal_or_404(db, journal_id)
    issues = list(
        (
            await db.execute(
                select(Issue)
                .where(Issue.journal_id == journal_id, Issue.volume == volume)
                .order_by(Issue.issue_number)
            )
        ).scalars().all()
    )
    present = {i.issue_number for i in issues}
    out: list[IssueStatsOut] = []
    if present:
        for num in range(min(present), max(present) + 1):
            issue = next((i for i in issues if i.issue_number == num), None)
            if issue is None:
                out.append(
                    IssueStatsOut(
                        id=0, volume=volume, issue_number=num, article_count=0,
                        cited_count=0, uncited_count=0,
                    )
                )
                continue
            arts = list(
                (await db.execute(select(Article).where(Article.issue_id == issue.id))).scalars().all()
            )
            out.append(_issue_stats(issue, arts))
    return out


@router.get("/journals/{journal_id}/volumes/{volume}/issues/{issue_number}/articles")
async def list_issue_articles(
    journal_id: int, volume: int, issue_number: int, db: Db, _user: CurrentUser
):
    await _journal_or_404(db, journal_id)
    issue = (
        await db.execute(
            select(Issue).where(
                Issue.journal_id == journal_id,
                Issue.volume == volume,
                Issue.issue_number == issue_number,
            )
        )
    ).scalar_one_or_none()
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    arts = list(
        (
            await db.execute(
                select(Article)
                .options(selectinload(Article.issue).selectinload(Issue.journal))
                .where(Article.issue_id == issue.id)
                .order_by(Article.page_start)
            )
        ).scalars().all()
    )
    coverage = compute_issue_coverage(arts, issue)
    return {
        "issue": _issue_stats(issue, arts),
        "articles": [_article_out(a) for a in arts],
        "coverage": coverage,
    }


@router.get(
    "/journals/{journal_id}/volumes/{volume}/issues/{issue_number}/coverage",
    response_model=CoverageOut,
)
async def issue_coverage(
    journal_id: int, volume: int, issue_number: int, db: Db, _user: CurrentUser
):
    data = await list_issue_articles(journal_id, volume, issue_number, db, _user)
    return data["coverage"]


@router.post("/journals/{journal_id}/papers")
async def upload_papers(
    journal_id: int,
    db: Db,
    _user: CurrentUser,
    files: list[UploadFile] = File(...),
):
    journal = await _journal_or_404(db, journal_id)
    saved = []
    for upload in files:
        data = await upload.read()
        article, created = await ingest_pdf_bytes(
            db, journal, data, upload.filename or "upload.pdf"
        )
        await db.flush()
        article = (
            await db.execute(
                select(Article)
                .options(selectinload(Article.issue).selectinload(Issue.journal))
                .where(Article.id == article.id)
            )
        ).scalar_one()
        saved.append({"created": created, "article": _article_out(article)})
    return {"articles": saved}


@router.post("/journals/{journal_id}/papers-text")
async def upload_paper_text(journal_id: int, body: TextPaperIn, db: Db, _user: CurrentUser):
    journal = await _journal_or_404(db, journal_id)
    article, created = await ingest_article_text(
        db,
        journal,
        body.text,
        source_url=body.source_url,
        original_filename=body.filename,
    )
    await db.flush()
    article = (
        await db.execute(
            select(Article)
            .options(selectinload(Article.issue).selectinload(Issue.journal))
            .where(Article.id == article.id)
        )
    ).scalar_one()
    return {"created": created, "article": _article_out(article)}


@router.post("/journals/{journal_id}/crawl", response_model=CrawlJobOut)
async def start_crawl(
    journal_id: int,
    body: CrawlStart,
    background: BackgroundTasks,
    db: Db,
    _user: CurrentUser,
):
    journal = await _journal_or_404(db, journal_id)
    journal.archive_url = body.archive_url
    job = CrawlJob(journal_id=journal.id, archive_url=body.archive_url, status="queued")
    db.add(job)
    await db.flush()
    job_id = job.id
    await db.commit()
    background.add_task(run_crawl_job, job_id)
    return CrawlJobOut.model_validate(job)


@router.get("/journals/{journal_id}/latest-crawl", response_model=CrawlJobOut)
async def latest_crawl(journal_id: int, db: Db, _user: CurrentUser):
    await _journal_or_404(db, journal_id)
    job = (
        await db.execute(
            select(CrawlJob)
            .where(CrawlJob.journal_id == journal_id)
            .order_by(CrawlJob.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="No crawl job found")
    return CrawlJobOut.model_validate(job)


@router.get("/crawl-jobs/{job_id}", response_model=CrawlJobOut)
async def get_crawl_job(job_id: int, db: Db, _user: CurrentUser):
    job = await db.get(CrawlJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Crawl job not found")
    return CrawlJobOut.model_validate(job)


@router.post("/crawl-jobs/{job_id}/cancel", response_model=CrawlJobOut)
async def cancel_crawl(job_id: int, db: Db, _user: CurrentUser):
    job = await db.get(CrawlJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Crawl job not found")
    job.cancel_requested = True
    if job.status == "queued":
        job.status = "cancelled"
    await db.flush()
    return CrawlJobOut.model_validate(job)


@router.post("/crawl-jobs/{job_id}/download", response_model=CrawlJobOut)
async def start_download(
    job_id: int,
    body: CrawlDownloadIn,
    background: BackgroundTasks,
    db: Db,
    _user: CurrentUser,
):
    job = await db.get(CrawlJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Crawl job not found")
    if job.status == "running":
        raise HTTPException(status_code=409, detail="This job is already running")
    inventory = list(job.inventory or [])
    if not inventory:
        raise HTTPException(
            status_code=400,
            detail="Scan the archive first so issues can be listed",
        )
    known = {str(row.get("url") or "").rstrip("/") for row in inventory}
    selected = []
    seen: set[str] = set()
    for url in body.issue_urls:
        key = url.rstrip("/")
        if key in known and key not in seen:
            selected.append(url)
            seen.add(key)
    if not selected:
        raise HTTPException(
            status_code=400,
            detail="None of the selected issue URLs are in this scan",
        )
    job.status = "queued"
    job.phase = "downloading"
    job.message = f"Queued download of {len(selected)} issue(s)…"
    await db.commit()
    background.add_task(run_download_job, job_id, selected)
    return CrawlJobOut.model_validate(job)


@router.get("/archive/search")
async def search_archive(
    db: Db,
    _user: CurrentUser,
    q: str = "",
    journal_id: Optional[int] = None,
    volume: Optional[int] = None,
    issue: Optional[int] = None,
):
    stmt = (
        select(Article)
        .options(selectinload(Article.issue).selectinload(Issue.journal))
        .join(Issue, Article.issue_id == Issue.id)
    )
    if journal_id:
        stmt = stmt.where(Issue.journal_id == journal_id)
    if volume is not None:
        stmt = stmt.where(Issue.volume == volume)
    if issue is not None:
        stmt = stmt.where(Issue.issue_number == issue)
    needle = (q or "").strip().lower()
    rows = list((await db.execute(stmt.order_by(Issue.volume.desc(), Article.page_start))).scalars().all())
    hits = []
    for article in rows:
        blob = " ".join(
            [
                article.title or "",
                " ".join(a for a in (article.authors or []) if isinstance(a, str)),
                article.abstract or "",
                article.full_text or "",
            ]
        ).lower()
        if needle and needle not in blob:
            continue
        item = _article_out(article)
        snippet = (article.full_text or article.abstract or "")[:400]
        hits.append({**item.model_dump(), "snippet": snippet})
        if len(hits) >= 50:
            break
    return {"query": q, "count": len(hits), "articles": hits}


@router.get("/articles/{article_id}")
async def get_article(article_id: int, db: Db, _user: CurrentUser):
    article = (
        await db.execute(
            select(Article)
            .options(selectinload(Article.issue).selectinload(Issue.journal))
            .where(Article.id == article_id)
        )
    ).scalar_one_or_none()
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    data = _article_out(article).model_dump()
    data["full_text"] = article.full_text or ""
    return data


@router.patch("/articles/{article_id}", response_model=ArticleOut)
async def patch_article(article_id: int, body: ArticlePatch, db: Db, _user: CurrentUser):
    article = (
        await db.execute(
            select(Article)
            .options(selectinload(Article.issue).selectinload(Issue.journal))
            .where(Article.id == article_id)
        )
    ).scalar_one_or_none()
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(article, field, value)
    await db.flush()
    return _article_out(article)


@router.post("/articles/{article_id}/sync-citations", response_model=ArticleOut)
async def sync_one_article(article_id: int, db: Db, _user: CurrentUser):
    article = (
        await db.execute(
            select(Article)
            .options(selectinload(Article.issue).selectinload(Issue.journal))
            .where(Article.id == article_id)
        )
    ).scalar_one_or_none()
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    await sync_article_citations(db, article)
    return _article_out(article)


@router.post("/issues/{issue_id}/sync-citations")
async def sync_issue_citations(issue_id: int, db: Db, _user: CurrentUser):
    issue = await db.get(Issue, issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    arts = list(
        (
            await db.execute(
                select(Article)
                .options(selectinload(Article.issue).selectinload(Issue.journal))
                .where(Article.issue_id == issue_id)
            )
        ).scalars().all()
    )
    synced = []
    for article in arts:
        await sync_article_citations(db, article)
        synced.append(_article_out(article))
    return {"articles": synced}


@router.post("/journals/{journal_id}/sync-citations")
async def sync_journal_citations(journal_id: int, db: Db, _user: CurrentUser):
    await _journal_or_404(db, journal_id)
    arts = list(
        (
            await db.execute(
                select(Article)
                .options(selectinload(Article.issue).selectinload(Issue.journal))
                .join(Issue, Article.issue_id == Issue.id)
                .where(Issue.journal_id == journal_id)
            )
        ).scalars().all()
    )
    synced = []
    for article in arts[:80]:
        await sync_article_citations(db, article)
        synced.append(_article_out(article))
    return {"synced": len(synced), "articles": synced}


@router.post("/manuscripts", status_code=status.HTTP_201_CREATED)
async def upload_manuscript(
    db: Db,
    _user: CurrentUser,
    file: UploadFile = File(...),
):
    data = await file.read()
    filename = file.filename or "manuscript.pdf"
    lower = filename.lower()
    if lower.endswith(".doc") and not lower.endswith(".docx"):
        raise HTTPException(
            status_code=400,
            detail="Old .doc files are not supported. Save the manuscript as .docx or PDF.",
        )
    text = extract_manuscript_text(data, filename)
    if not text.strip():
        raise HTTPException(
            status_code=400,
            detail="Could not read text from that file. Upload a Word (.docx) or PDF manuscript.",
        )
    from app.core.config import get_settings
    from pathlib import Path
    from uuid import uuid4

    dest_dir = Path(get_settings().upload_dir) / "manuscripts"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{uuid4().hex[:8]}_{Path(filename).stem}{suffix_for(filename)}"
    dest.write_bytes(data)
    manuscript = Manuscript(
        title=filename,
        pdf_path=str(dest),
        full_text=text,
        status="uploaded",
    )
    db.add(manuscript)
    await db.flush()
    return {"id": manuscript.id, "title": manuscript.title, "status": manuscript.status}


@router.post("/manuscripts/{manuscript_id}/suggest")
async def run_suggestions(manuscript_id: int, db: Db, _user: CurrentUser):
    manuscript = (
        await db.execute(
            select(Manuscript)
            .options(selectinload(Manuscript.paragraphs))
            .where(Manuscript.id == manuscript_id)
        )
    ).scalar_one_or_none()
    if manuscript is None:
        raise HTTPException(status_code=404, detail="Manuscript not found")
    created = await suggest_for_manuscript(db, manuscript)
    return {"suggestion_count": len(created), "status": manuscript.status}


@router.get("/manuscripts", response_model=list[ManuscriptOut])
async def list_manuscripts(db: Db, _user: CurrentUser):
    rows = list((await db.execute(select(Manuscript).order_by(Manuscript.id.desc()))).scalars().all())
    out = []
    for ms in rows:
        pc = int(
            (
                await db.execute(
                    select(func.count(ManuscriptParagraph.id)).where(
                        ManuscriptParagraph.manuscript_id == ms.id
                    )
                )
            ).scalar()
            or 0
        )
        sc = int(
            (
                await db.execute(
                    select(func.count(CitationSuggestion.id)).where(
                        CitationSuggestion.manuscript_id == ms.id
                    )
                )
            ).scalar()
            or 0
        )
        out.append(
            ManuscriptOut(
                id=ms.id,
                title=ms.title,
                status=ms.status,
                created_at=ms.created_at,
                paragraph_count=pc,
                suggestion_count=sc,
            )
        )
    return out


@router.delete("/manuscripts/{manuscript_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_manuscript(manuscript_id: int, db: Db, _user: CurrentUser):
    manuscript = await db.get(Manuscript, manuscript_id)
    if manuscript is None:
        raise HTTPException(status_code=404, detail="Manuscript not found")
    path = manuscript.pdf_path
    await db.delete(manuscript)
    await db.flush()
    if path:
        from pathlib import Path

        stored = Path(path)
        if stored.exists() and stored.is_file():
            stored.unlink()
    return None


@router.get("/manuscripts/{manuscript_id}", response_model=ManuscriptDetail)
async def get_manuscript(manuscript_id: int, db: Db, _user: CurrentUser):
    manuscript = (
        await db.execute(
            select(Manuscript)
            .options(
                selectinload(Manuscript.paragraphs)
                .selectinload(ManuscriptParagraph.suggestions)
                .selectinload(CitationSuggestion.article)
                .selectinload(Article.issue)
                .selectinload(Issue.journal)
            )
            .where(Manuscript.id == manuscript_id)
        )
    ).scalar_one_or_none()
    if manuscript is None:
        raise HTTPException(status_code=404, detail="Manuscript not found")
    paragraphs = []
    for para in sorted(manuscript.paragraphs, key=lambda p: p.index):
        suggestions = []
        for sug in para.suggestions:
            suggestions.append(
                {
                    "id": sug.id,
                    "paragraph_id": sug.paragraph_id,
                    "article_id": sug.article_id,
                    "score": sug.score,
                    "reason": sug.reason,
                    "house_citation": sug.house_citation,
                    "status": sug.status,
                    "article": _article_out(sug.article).model_dump() if sug.article else None,
                }
            )
        paragraphs.append({"id": para.id, "index": para.index, "text": para.text, "suggestions": suggestions})
    cited_paras, references = assign_citations(paragraphs)
    return ManuscriptDetail(
        id=manuscript.id,
        title=manuscript.title,
        status=manuscript.status,
        full_text=manuscript.full_text or "",
        paragraphs=[ParagraphOut(**row) for row in cited_paras],
        references=[ReferenceOut(**row) for row in references],
    )


@router.patch("/suggestions/{suggestion_id}", response_model=SuggestionOut)
async def patch_suggestion(suggestion_id: int, body: SuggestionPatch, db: Db, _user: CurrentUser):
    if body.status not in {"pending", "accepted", "rejected"}:
        raise HTTPException(status_code=400, detail="Invalid status")
    sug = (
        await db.execute(
            select(CitationSuggestion)
            .options(
                selectinload(CitationSuggestion.article)
                .selectinload(Article.issue)
                .selectinload(Issue.journal)
            )
            .where(CitationSuggestion.id == suggestion_id)
        )
    ).scalar_one_or_none()
    if sug is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    sug.status = body.status
    await db.flush()
    return SuggestionOut(
        id=sug.id,
        paragraph_id=sug.paragraph_id,
        article_id=sug.article_id,
        score=sug.score,
        reason=sug.reason,
        house_citation=sug.house_citation,
        status=sug.status,
        article=_article_out(sug.article) if sug.article else None,
    )


@router.get("/manuscripts/{manuscript_id}/export")
async def export_manuscript(manuscript_id: int, db: Db, _user: CurrentUser):
    from pathlib import Path

    detail = await get_manuscript(manuscript_id, db, _user)
    data = build_amended_docx(
        title=detail.title or "Manuscript",
        paragraphs=[p.model_dump() for p in detail.paragraphs],
        references=[r.model_dump() for r in detail.references],
    )
    stem = Path(detail.title or "manuscript").stem or "manuscript"
    filename = f"{stem}-cited.docx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
