"""Citation assistant archive models: journals, issues, articles, crawls, manuscripts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.database.base import Base


class Journal(Base):
    __tablename__ = "journals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    abbreviation: Mapped[Optional[str]] = mapped_column(String(50))
    publisher: Mapped[Optional[str]] = mapped_column(String(255))
    issn: Mapped[Optional[str]] = mapped_column(String(32))
    archive_url: Mapped[Optional[str]] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    issues: Mapped[List["Issue"]] = relationship(
        back_populates="journal", cascade="all, delete-orphan"
    )
    crawl_jobs: Mapped[List["CrawlJob"]] = relationship(
        back_populates="journal", cascade="all, delete-orphan"
    )


class Issue(Base):
    __tablename__ = "issues"
    __table_args__ = (
        UniqueConstraint("journal_id", "volume", "issue_number", name="uq_issue_journal_vol_num"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    journal_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("journals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    volume: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    issue_number: Mapped[int] = mapped_column(Integer, nullable=False)
    year: Mapped[Optional[int]] = mapped_column(Integer)
    month: Mapped[Optional[str]] = mapped_column(String(32))
    expected_page_start: Mapped[Optional[int]] = mapped_column(Integer)
    expected_page_end: Mapped[Optional[int]] = mapped_column(Integer)

    journal: Mapped["Journal"] = relationship(back_populates="issues")
    articles: Mapped[List["Article"]] = relationship(
        back_populates="issue", cascade="all, delete-orphan"
    )


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (
        UniqueConstraint("issue_id", "page_start", name="uq_article_issue_page"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    issue_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("issues.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_start: Mapped[int] = mapped_column(Integer, nullable=False)
    page_end: Mapped[Optional[int]] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    authors: Mapped[Any] = mapped_column(JSON, default=list)
    affiliations: Mapped[Any] = mapped_column(JSON, default=list)
    correspondence_email: Mapped[Optional[str]] = mapped_column(String(255))
    citation_raw: Mapped[Optional[str]] = mapped_column(Text)
    received_date: Mapped[Optional[str]] = mapped_column(String(64))
    revised_date: Mapped[Optional[str]] = mapped_column(String(64))
    accepted_date: Mapped[Optional[str]] = mapped_column(String(64))
    published_date: Mapped[Optional[str]] = mapped_column(String(64))
    keywords: Mapped[Any] = mapped_column(JSON, default=list)
    abstract: Mapped[Optional[str]] = mapped_column(Text)
    full_text: Mapped[str] = mapped_column(Text, default="")
    pdf_path: Mapped[Optional[str]] = mapped_column(String(1000))
    source_url: Mapped[Optional[str]] = mapped_column(String(1000))
    ocr_status: Mapped[str] = mapped_column(String(32), default="extracted")
    header_raw: Mapped[Optional[str]] = mapped_column(Text)
    doi: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    crossref_citation_count: Mapped[int] = mapped_column(Integer, default=0)
    scholar_citation_count: Mapped[int] = mapped_column(Integer, default=0)
    citation_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    citation_sync_status: Mapped[Optional[str]] = mapped_column(String(32))
    crossref_work_url: Mapped[Optional[str]] = mapped_column(String(1000))
    scholar_url: Mapped[Optional[str]] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    issue: Mapped["Issue"] = relationship(back_populates="articles")
    chunks: Mapped[List["ArticleChunk"]] = relationship(
        back_populates="article", cascade="all, delete-orphan"
    )


class ArticleChunk(Base):
    __tablename__ = "article_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("articles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    paragraph_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Any] = mapped_column(JSON, default=list)

    article: Mapped["Article"] = relationship(back_populates="chunks")


class CrawlJob(Base):
    __tablename__ = "crawl_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    journal_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("journals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    archive_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    issues_found: Mapped[int] = mapped_column(Integer, default=0)
    articles_found: Mapped[int] = mapped_column(Integer, default=0)
    articles_saved: Mapped[int] = mapped_column(Integer, default=0)
    articles_skipped: Mapped[int] = mapped_column(Integer, default=0)
    error_log: Mapped[Any] = mapped_column(JSON, default=list)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    journal: Mapped["Journal"] = relationship(back_populates="crawl_jobs")


class Manuscript(Base):
    __tablename__ = "manuscripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[Optional[str]] = mapped_column(String(1000))
    pdf_path: Mapped[Optional[str]] = mapped_column(String(1000))
    full_text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="uploaded")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    paragraphs: Mapped[List["ManuscriptParagraph"]] = relationship(
        back_populates="manuscript", cascade="all, delete-orphan"
    )
    suggestions: Mapped[List["CitationSuggestion"]] = relationship(
        back_populates="manuscript", cascade="all, delete-orphan"
    )


class ManuscriptParagraph(Base):
    __tablename__ = "manuscript_paragraphs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    manuscript_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("manuscripts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)

    manuscript: Mapped["Manuscript"] = relationship(back_populates="paragraphs")
    suggestions: Mapped[List["CitationSuggestion"]] = relationship(
        back_populates="paragraph"
    )


class CitationSuggestion(Base):
    __tablename__ = "citation_suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    manuscript_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("manuscripts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    paragraph_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("manuscript_paragraphs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    article_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("articles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="")
    house_citation: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending")

    manuscript: Mapped["Manuscript"] = relationship(back_populates="suggestions")
    paragraph: Mapped["ManuscriptParagraph"] = relationship(back_populates="suggestions")
    article: Mapped["Article"] = relationship()
