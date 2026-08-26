"""Pydantic schemas for the citation assistant."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class JournalCreate(BaseModel):
    name: str
    abbreviation: Optional[str] = "IJIST"
    publisher: Optional[str] = None
    issn: Optional[str] = None
    archive_url: Optional[str] = None


class JournalUpdate(BaseModel):
    name: Optional[str] = None
    abbreviation: Optional[str] = None
    publisher: Optional[str] = None
    issn: Optional[str] = None
    archive_url: Optional[str] = None


class JournalOut(BaseModel):
    id: int
    name: str
    abbreviation: Optional[str] = None
    publisher: Optional[str] = None
    issn: Optional[str] = None
    archive_url: Optional[str] = None
    article_count: int = 0
    volume_count: int = 0
    has_gaps: bool = False
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class VolumeOut(BaseModel):
    volume: int
    year_start: Optional[int] = None
    year_end: Optional[int] = None
    article_count: int = 0
    issue_count: int = 0
    missing: bool = False


class IssueStatsOut(BaseModel):
    id: int
    volume: int
    issue_number: int
    year: Optional[int] = None
    month: Optional[str] = None
    article_count: int = 0
    cited_count: int = 0
    uncited_count: int = 0
    scholar_total: int = 0
    crossref_total: int = 0
    citations_synced: bool = False


class PageRange(BaseModel):
    page_start: int
    page_end: int
    article_id: Optional[int] = None
    title: Optional[str] = None


class CoverageOut(BaseModel):
    present: list[dict[str, Any]] = Field(default_factory=list)
    gaps: list[dict[str, Any]] = Field(default_factory=list)
    overlaps: list[dict[str, Any]] = Field(default_factory=list)
    article_count: int = 0


class ArticleOut(BaseModel):
    id: int
    issue_id: int
    volume: Optional[int] = None
    issue_number: Optional[int] = None
    page_start: int
    page_end: Optional[int] = None
    title: str
    authors: Any = []
    affiliations: Any = []
    correspondence_email: Optional[str] = None
    citation_raw: Optional[str] = None
    received_date: Optional[str] = None
    revised_date: Optional[str] = None
    accepted_date: Optional[str] = None
    published_date: Optional[str] = None
    keywords: Any = []
    abstract: Optional[str] = None
    doi: Optional[str] = None
    ocr_status: Optional[str] = None
    pdf_path: Optional[str] = None
    source_url: Optional[str] = None
    crossref_citation_count: int = 0
    scholar_citation_count: int = 0
    citation_synced_at: Optional[datetime] = None
    citation_sync_status: Optional[str] = None
    crossref_work_url: Optional[str] = None
    scholar_url: Optional[str] = None
    citing_works: list[Any] = Field(default_factory=list)
    house_citation: Optional[str] = None

    model_config = {"from_attributes": True}


class ArticlePatch(BaseModel):
    title: Optional[str] = None
    authors: Optional[list[Any]] = None
    doi: Optional[str] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    keywords: Optional[list[str]] = None
    abstract: Optional[str] = None
    citation_raw: Optional[str] = None
    received_date: Optional[str] = None
    revised_date: Optional[str] = None
    accepted_date: Optional[str] = None
    published_date: Optional[str] = None
    scholar_citation_count: Optional[int] = None
    scholar_url: Optional[str] = None
    crossref_citation_count: Optional[int] = None


class CrawlStart(BaseModel):
    archive_url: str


class CrawlJobOut(BaseModel):
    id: int
    journal_id: int
    archive_url: str
    status: str
    issues_found: int = 0
    articles_found: int = 0
    articles_saved: int = 0
    articles_skipped: int = 0
    articles_remaining: int = 0
    pages_crawled: int = 0
    phase: Optional[str] = None
    message: Optional[str] = None
    inventory: list[Any] = Field(default_factory=list)
    error_log: Any = []
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

    def model_post_init(self, _context) -> None:
        found = int(self.articles_found or 0)
        saved = int(self.articles_saved or 0)
        skipped = int(self.articles_skipped or 0)
        self.articles_remaining = max(0, found - saved - skipped)
        if self.inventory is None:
            self.inventory = []


class CrawlDownloadIn(BaseModel):
    issue_urls: list[str] = Field(..., min_length=1, max_length=400)


class TextPaperIn(BaseModel):
    filename: str = "article.txt"
    text: str
    source_url: Optional[str] = None


class ManuscriptOut(BaseModel):
    id: int
    title: Optional[str] = None
    status: str
    created_at: Optional[datetime] = None
    paragraph_count: int = 0
    suggestion_count: int = 0

    model_config = {"from_attributes": True}


class SuggestionOut(BaseModel):
    id: int
    paragraph_id: int
    article_id: int
    score: float
    reason: str
    house_citation: Optional[str] = None
    status: str
    citation_number: Optional[int] = None
    journal: Optional[str] = None
    volume: Optional[int] = None
    issue_number: Optional[int] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    article_title: Optional[str] = None
    authors: Any = None
    doi: Optional[str] = None
    article: Optional[ArticleOut] = None


class ParagraphOut(BaseModel):
    id: int
    index: int
    text: str
    display_text: str = ""
    citation_numbers: list[int] = Field(default_factory=list)
    suggestions: list[SuggestionOut] = Field(default_factory=list)


class ReferenceOut(BaseModel):
    number: int
    house_citation: str = ""
    article_id: Optional[int] = None
    title: Optional[str] = None


class ManuscriptDetail(BaseModel):
    id: int
    title: Optional[str] = None
    status: str
    full_text: str = ""
    paragraphs: list[ParagraphOut] = Field(default_factory=list)
    references: list[ReferenceOut] = Field(default_factory=list)


class SuggestionPatch(BaseModel):
    status: str
