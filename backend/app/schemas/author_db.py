"""Schemas for the author database management system."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


WINGS = ("in_process", "published")

FIELD_LABELS = {
    "wing": "Wing",
    "journal_id": "Journal",
    "ojs_number": "OJS number",
    "title": "Title",
    "author_names": "Author names",
    "author_emails": "Email addresses of authors",
    "email_sent": "Email sent",
    "plagiarism": "Plagiarism",
    "orcid_id": "ORCID ID",
    "received_date": "Receive date",
    "review_date": "Review date",
    "accepted_date": "Accepted date",
    "publish_date": "Publish date",
    "repeat_done": "Repeat done",
    "doi_in_pdf": "DOI in PDF",
}


class AuthorArticleIn(BaseModel):
    wing: str = Field(default="in_process")
    journal_id: Optional[int] = None
    ojs_number: str = ""
    title: str = ""
    author_names: str = ""
    author_emails: str = ""
    email_sent: bool = False
    plagiarism: str = ""
    orcid_id: str = ""
    received_date: Optional[str] = None
    review_date: Optional[str] = None
    accepted_date: Optional[str] = None
    publish_date: Optional[str] = None
    repeat_done: bool = False
    doi_in_pdf: str = ""


class AuthorArticlePatch(BaseModel):
    wing: Optional[str] = None
    journal_id: Optional[int] = None
    ojs_number: Optional[str] = None
    title: Optional[str] = None
    author_names: Optional[str] = None
    author_emails: Optional[str] = None
    email_sent: Optional[bool] = None
    plagiarism: Optional[str] = None
    orcid_id: Optional[str] = None
    received_date: Optional[str] = None
    review_date: Optional[str] = None
    accepted_date: Optional[str] = None
    publish_date: Optional[str] = None
    repeat_done: Optional[bool] = None
    doi_in_pdf: Optional[str] = None


class AuthorFieldChangeOut(BaseModel):
    field: str
    label: str
    previous: str
    new: str


class AuthorModificationOut(BaseModel):
    mod_number: int
    changed_at: datetime
    account: str
    account_username: str = ""
    account_email: str = ""
    account_name: str = ""
    changes: list[AuthorFieldChangeOut] = Field(default_factory=list)


class AuthorArticleOut(BaseModel):
    id: int
    wing: str
    journal_id: Optional[int] = None
    journal_name: Optional[str] = None
    owner_id: Optional[int] = None
    ojs_number: str = ""
    title: str = ""
    author_names: str = ""
    author_emails: str = ""
    email_sent: bool = False
    plagiarism: str = ""
    orcid_id: str = ""
    received_date: Optional[str] = None
    review_date: Optional[str] = None
    accepted_date: Optional[str] = None
    publish_date: Optional[str] = None
    repeat_done: bool = False
    doi_in_pdf: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    modifications: list[AuthorModificationOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class AuthorImportResult(BaseModel):
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = Field(default_factory=list)
    articles: list[AuthorArticleOut] = Field(default_factory=list)
