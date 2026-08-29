"""Match manuscript paragraphs against the persistent article-chunk archive."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Sequence

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

MAX_SUGGESTIONS_PER_MANUSCRIPT = 10
MAX_SUGGESTIONS_PER_PARAGRAPH = 1
MIN_SUGGESTION_SCORE = 0.16
WEAK_SCORE_MARGIN = 0.08

_HEADING_RE = re.compile(
    r"^(abstract|introduction|related work|literature review|materials and methods|"
    r"methodology|methods|results and discussion|results|discussion|conclusion|"
    r"conclusions|acknowledg(e)?ments?|references|bibliography|works cited|"
    r"literature cited|appendix( [a-z0-9]+)?)\s*$",
    re.I,
)
_NUMBERED_HEADING_RE = re.compile(
    r"^(\d+(?:\.\d+){0,3}|[IVXLCM]+)[\.\)]\s+(.*)$",
    re.I,
)
_REFERENCES_HEADING_RE = re.compile(
    r"^(references|bibliography|works cited|literature cited)\s*$",
    re.I,
)
_BIBLIO_LINE_RE = re.compile(
    r"^(\[\d+\]|\d+\.)\s+[A-Z].+",
)
_AUTHOR_AFFIL_RE = re.compile(
    r"(corresponding author|correspondence:|\borcid\b|\b[\w.-]+@[\w.-]+\.[a-z]{2,}\b)",
    re.I,
)
_AFFIL_LINE_RE = re.compile(
    r"^\d+\s*(Department|Faculty|School|College|University|Institute)\b",
    re.I,
)
_NUMBERED_PREFIX_RE = re.compile(
    r"^(?:\d+(?:\.\d+)*|[IVXLCM]+)[\.\)]\s+",
    re.I,
)
_INTRO_LABELS = {
    "introduction",
    "introduction importance of study",
    "introduction importance of the study",
}
_METHODS_LABELS = {
    "materials and methods",
    "material and methods",
    "materials and method",
    "material and method",
    "methodology",
    "methods",
    "experimental setup",
    "experimental procedure",
    "experimental section",
}
_AFTER_METHODS_LABELS = {
    "results",
    "result",
    "results and discussion",
    "result and discussion",
    "discussion",
    "conclusion",
    "conclusions",
    "acknowledgement",
    "acknowledgements",
    "acknowledgment",
    "acknowledgments",
    "references",
    "bibliography",
    "works cited",
    "literature cited",
    "appendix",
}


@dataclass(frozen=True)
class RankedCandidate:
    paragraph_index: int
    paragraph_id: int
    article_id: int
    score: float
    chunk_text: str
    article: Any
    chunk: Any


def is_references_heading(text: str) -> bool:
    compact = re.sub(r"\s+", " ", (text or "").strip())
    return bool(compact and _REFERENCES_HEADING_RE.match(compact))


def _heading_label(text: str) -> str:
    compact = re.sub(r"\s+", " ", (text or "").strip())
    compact = _NUMBERED_PREFIX_RE.sub("", compact)
    prefix = compact.split(":", 1)[0]
    return re.sub(r"[^a-z]+", " ", prefix.lower()).strip()


def section_heading_kind(text: str) -> str | None:
    """Classify a paragraph as a major manuscript heading, if it is one."""
    compact = re.sub(r"\s+", " ", (text or "").strip())
    if not compact:
        return None
    if is_references_heading(compact):
        return "after_methods"
    label = _heading_label(compact)
    words = label.split()
    if not label:
        return None
    if label in _INTRO_LABELS or (label.startswith("introduction") and len(words) <= 6):
        return "introduction"
    if label in _METHODS_LABELS:
        return "methods"
    if label in _AFTER_METHODS_LABELS or (label.startswith("appendix") and len(words) <= 4):
        return "after_methods"
    if _HEADING_RE.match(compact):
        if label in {"related work", "literature review", "abstract"}:
            return None
    return None


def citation_section_range(texts: Sequence[str]) -> tuple[int, int] | None:
    """Return [start, end) covering Introduction through Materials and Methods.

    Citations are not suggested in the title, abstract, results, discussion,
    or reference list. If Introduction is missing, no citation window is used.
    """
    intro_at: int | None = None
    stop_at: int | None = None
    for index, text in enumerate(texts):
        kind = section_heading_kind(text)
        if kind == "introduction" and intro_at is None:
            intro_at = index
            continue
        if intro_at is None:
            continue
        if kind == "after_methods":
            stop_at = index
            break
    if intro_at is None:
        return None
    return intro_at, len(texts) if stop_at is None else stop_at


def in_citation_window(index: int, window: tuple[int, int] | None) -> bool:
    if window is None:
        return False
    start, end = window
    return start <= index < end


def split_manuscript_paragraphs(text: str) -> list[str]:
    """Keep section headings even when they are short single lines."""
    paragraphs: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        if not buf:
            return
        para = re.sub(r"\s+", " ", " ".join(buf)).strip()
        if para:
            paragraphs.append(para)
        buf.clear()

    for raw in (text or "").splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            flush()
            continue
        if (
            section_heading_kind(line)
            or is_references_heading(line)
            or _HEADING_RE.match(line)
        ):
            flush()
            paragraphs.append(line)
            continue
        buf.append(line)
    flush()
    return paragraphs


def is_substantive_paragraph(text: str, *, index: int = 0, in_references: bool = False) -> bool:
    """Skip titles, headings, author lines, bibliography, and short boilerplate."""
    if in_references:
        return False
    compact = re.sub(r"\s+", " ", (text or "").strip())
    if len(compact) < 40:
        return False
    if is_references_heading(compact) or _HEADING_RE.match(compact):
        return False
    if _AUTHOR_AFFIL_RE.search(compact) and len(compact) < 220:
        return False
    if _AFFIL_LINE_RE.match(compact):
        return False
    if _BIBLIO_LINE_RE.match(compact) and len(compact) < 400:
        return False
    numbered = _NUMBERED_HEADING_RE.match(compact)
    if numbered:
        rest = (numbered.group(2) or "").strip()
        if len(rest) <= 80 and len(rest.split()) <= 12 and not re.search(r"[.!?]$", rest):
            return False
    words = compact.split()
    if len(words) <= 12 and not re.search(r"[.!?]", compact):
        caps = sum(1 for word in words if word[:1].isupper())
        if caps >= max(2, int(0.7 * len(words))):
            return False
    if index == 0 and not re.search(r"[.!?]", compact) and len(words) <= 20:
        caps = sum(1 for word in words if word[:1].isupper())
        if caps >= max(3, int(0.55 * len(words))):
            return False
    return True


def passes_relevance_gate(
    score: float,
    terms: Sequence[str],
    *,
    min_score: float = MIN_SUGGESTION_SCORE,
) -> bool:
    if score < min_score:
        return False
    if score < min_score + WEAK_SCORE_MARGIN and not terms:
        return False
    return True


def one_per_paragraph(matches: Sequence[RankedCandidate]) -> list[RankedCandidate]:
    """Keep the highest-scoring article for each paragraph."""
    best: dict[int, RankedCandidate] = {}
    for match in matches:
        prev = best.get(match.paragraph_id)
        if prev is None or match.score > prev.score:
            best[match.paragraph_id] = match
    return list(best.values())


def select_manuscript_matches(
    matches: Sequence[RankedCandidate],
    *,
    limit: int = MAX_SUGGESTIONS_PER_MANUSCRIPT,
) -> list[RankedCandidate]:
    """Pick the strongest manuscript-wide matches, then restore paragraph order."""
    unique = one_per_paragraph(matches)
    ranked = sorted(unique, key=lambda item: (-item.score, item.paragraph_index))
    top = ranked[: max(0, int(limit))]
    return sorted(top, key=lambda item: item.paragraph_index)


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
    per_paragraph: int = MAX_SUGGESTIONS_PER_PARAGRAPH,
    max_suggestions: int = MAX_SUGGESTIONS_PER_MANUSCRIPT,
    min_score: float = MIN_SUGGESTION_SCORE,
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
        paras = split_manuscript_paragraphs(text) or split_paragraphs(text, min_len=40) or [
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

    per_paragraph = max(1, int(per_paragraph or MAX_SUGGESTIONS_PER_PARAGRAPH))
    raw_matches: list[RankedCandidate] = []
    window = citation_section_range([para.text or "" for para in paragraphs])
    in_references = False
    for para in paragraphs:
        if is_references_heading(para.text or ""):
            in_references = True
            continue
        if not in_citation_window(para.index, window):
            continue
        if not is_substantive_paragraph(para.text or "", index=para.index, in_references=in_references):
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
        ranked = sorted(best.values(), key=lambda item: item[0], reverse=True)
        kept_for_para = 0
        for score, chunk in ranked:
            article = chunk.article
            terms = overlap_terms(para.text, _archive_blob(article, chunk.text), limit=4)
            if not passes_relevance_gate(score, terms, min_score=min_score):
                continue
            raw_matches.append(
                RankedCandidate(
                    paragraph_index=para.index,
                    paragraph_id=para.id,
                    article_id=article.id,
                    score=round(float(score), 4),
                    chunk_text=chunk.text or "",
                    article=article,
                    chunk=chunk,
                )
            )
            kept_for_para += 1
            if kept_for_para >= per_paragraph:
                break

    para_by_id = {para.id: para for para in paragraphs}
    for match in select_manuscript_matches(raw_matches, limit=max_suggestions):
        article = match.article
        para = para_by_id[match.paragraph_id]
        sug = CitationSuggestion(
            manuscript_id=manuscript.id,
            paragraph_id=match.paragraph_id,
            article_id=match.article_id,
            score=match.score,
            reason=_reason(para.text, article, match.chunk_text, match.score),
            house_citation=house_citation_for(article),
            status="pending",
        )
        db.add(sug)
        created.append(sug)
    manuscript.status = "suggested"
    await db.flush()
    return created


house_citation_for = house_citation_for
suggest_for_manuscript = suggest_for_manuscript
