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


def _reason(paragraph: str, article: Article, chunk_text: str, score: float) -> str:
    terms = overlap_terms(paragraph, f"{article.title} {article.abstract or ''} {chunk_text}")
    issue = article.issue
    loc = ""
    if issue:
        loc = f"Vol. {issue.volume} Issue {issue.issue_number} pp {article.page_start}"
        if article.page_end:
            loc += f"-{article.page_end}"
    if terms:
        joined = ", ".join(terms)
        return (
            f"This paragraph discusses {joined}. The archived paper “{article.title}” ({loc}) "
            f"covers the same topic (similarity {score:.2f}) and is a suitable IJIST house citation."
        )
    return (
        f"This passage is semantically close to “{article.title}” ({loc}; score {score:.2f}). "
        f"Citing it would keep the manuscript aligned with the journal archive."
    )


async def suggest_for_manuscript(
    db: AsyncSession,
    manuscript: Manuscript,
    *,
    per_paragraph: int = 1,
    min_score: float = 0.12,
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
