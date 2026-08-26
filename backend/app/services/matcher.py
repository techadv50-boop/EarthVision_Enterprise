"""Match manuscript paragraphs against the persistent article-chunk archive."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.citation import (
    Article,
    ArticleChunk,
    CitationSuggestion,
    Issue,
    Manuscript,
    ManuscriptParagraph,
)
from app.services.citation_parser import format_house_citation, parse_ijist_header, split_paragraphs
from app.services.embeddings import cosine, embed_text, overlap_terms


def _author_names(article: Article) -> list[str]:
    names: list[str] = []
    for item in article.authors or []:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict):
            names.append(str(item.get("name") or item))
    return names


def house_citation_for(article: Article) -> str:
    issue = article.issue
    journal = issue.journal if issue else None
    return format_house_citation(
        authors=_author_names(article),
        title=article.title,
        volume=issue.volume if issue else 0,
        issue=issue.issue_number if issue else 0,
        page_start=article.page_start,
        page_end=article.page_end,
        month=issue.month if issue else None,
        year=issue.year if issue else None,
        abbreviation=(journal.abbreviation if journal and journal.abbreviation else "IJIST"),
    )


def _keyword_list(article: Article) -> list[str]:
    raw = article.keywords or []
    if isinstance(raw, str):
        return [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out


def _topic_phrase(terms: list[str]) -> str:
    if not terms:
        return ""
    if len(terms) == 1:
        return terms[0]
    if len(terms) == 2:
        return f"{terms[0]} and {terms[1]}"
    return ", ".join(terms[:-1]) + f", and {terms[-1]}"


def _article_locator(article: Article) -> str:
    issue = article.issue
    journal = issue.journal if issue else None
    name = (journal.name if journal and journal.name else None) or (
        journal.abbreviation if journal and journal.abbreviation else "the journal archive"
    )
    if not issue:
        return name
    pages = str(article.page_start)
    if article.page_end:
        pages = f"{article.page_start}-{article.page_end}"
    return f"{name}, Vol. {issue.volume} Issue {issue.issue_number} pp {pages}"


def _archive_blob(article: Article, chunk_text: str) -> str:
    return " ".join(
        part
        for part in (
            article.title,
            article.abstract or "",
            " ".join(_keyword_list(article)),
            chunk_text or "",
        )
        if part
    )


def _reason(paragraph: str, article: Article, chunk_text: str, score: float) -> str:
    terms = overlap_terms(paragraph, _archive_blob(article, chunk_text), limit=8)
    loc = _article_locator(article)
    kw_hits = [k for k in _keyword_list(article) if k.lower() in (paragraph or "").lower()][:4]
    extra = ""
    if kw_hits:
        extra = f" Its listed keywords ({', '.join(kw_hits)}) also appear in this paragraph."
    if terms:
        return (
            f"This paragraph discusses {_topic_phrase(terms)}. "
            f"The selected article “{article.title}” ({loc}) analyzes the same subject "
            f"in its title, abstract, or full text, so it directly supports the statement "
            f"in this paragraph.{extra}"
        )
    return (
        f"This paragraph is semantically aligned with “{article.title}” ({loc}). "
        f"The archived article’s abstract and full text match the meaning of this passage "
        f"(relevance {score:.2f}), so it can support the claim made here.{extra}"
    )


async def suggest_for_manuscript(
    db: AsyncSession,
    manuscript: Manuscript,
    *,
    per_paragraph: int = 3,
    min_score: float = 0.16,
) -> list[CitationSuggestion]:
    text = manuscript.full_text or ""
    loaded = await db.execute(
        select(ManuscriptParagraph)
        .where(ManuscriptParagraph.manuscript_id == manuscript.id)
        .order_by(ManuscriptParagraph.index)
    )
    paragraphs = list(loaded.scalars().all())
    if not paragraphs:
        meta = parse_ijist_header(text)
        if not manuscript.title:
            manuscript.title = meta.get("title")
        paras = split_paragraphs(text, min_len=40) or [
            p.strip() for p in text.split("\n\n") if len(p.strip()) > 40
        ]
        for i, p in enumerate(paras):
            db.add(ManuscriptParagraph(manuscript_id=manuscript.id, index=i, text=p))
        await db.flush()
        loaded = await db.execute(
            select(ManuscriptParagraph)
            .where(ManuscriptParagraph.manuscript_id == manuscript.id)
            .order_by(ManuscriptParagraph.index)
        )
        paragraphs = list(loaded.scalars().all())

    chunks_result = await db.execute(
        select(ArticleChunk).options(
            selectinload(ArticleChunk.article)
            .selectinload(Article.issue)
            .selectinload(Issue.journal)
        )
    )
    chunks = list(chunks_result.scalars().all())

    old = await db.execute(
        select(CitationSuggestion).where(CitationSuggestion.manuscript_id == manuscript.id)
    )
    for row in old.scalars().all():
        await db.delete(row)
    await db.flush()

    created: list[CitationSuggestion] = []
    if not chunks:
        manuscript.status = "suggested"
        await db.flush()
        return created

    for para in paragraphs:
        if len((para.text or "").strip()) < 40:
            continue
        query_vec = embed_text(para.text)
        best: dict[int, tuple[float, ArticleChunk]] = {}
        for chunk in chunks:
            emb = chunk.embedding or []
            if not emb:
                continue
            score = cosine(query_vec, emb)
            prev = best.get(chunk.article_id)
            if prev is None or score > prev[0]:
                best[chunk.article_id] = (score, chunk)
        ranked = sorted(best.values(), key=lambda t: t[0], reverse=True)
        kept = 0
        for score, chunk in ranked:
            if score < min_score:
                continue
            article = chunk.article
            terms = overlap_terms(para.text, _archive_blob(article, chunk.text), limit=4)
            if score < min_score + 0.08 and not terms:
                continue
            sug = CitationSuggestion(
                manuscript_id=manuscript.id,
                paragraph_id=para.id,
                article_id=article.id,
                score=round(float(score), 4),
                reason=_reason(para.text, article, chunk.text, score),
                house_citation=house_citation_for(article),
                status="pending",
            )
            db.add(sug)
            created.append(sug)
            kept += 1
            if kept >= per_paragraph:
                break
    manuscript.status = "suggested"
    await db.flush()
    return created


house_citation_for = house_citation_for
suggest_for_manuscript = suggest_for_manuscript
