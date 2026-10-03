"""Schemas for the author database management system."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


WINGS = ("in_process", "published")

AUTHOR_DB_JOURNALS = [
    ("IJIST", "International Journal of Innovations in Science & Technology"),
    ("MCCSS", "Magna Carta: Contemporary Social Science"),
    ("IJASD", "International Journal of Agriculture and Sustainable Development"),
    ("FCSI", "Frontiers in Computational Spatial Intelligence"),
    ("JIRSD", "Journal of International Relations and Social Dynamics"),
    ("IJNTD", "International Journal of NT Diseases"),
]

FIELD_LABELS = {
    "wing": "Wing",
    "journal_id": "Journal",
    "journal_title": "Journal",
    "ojs_number": "OJS number",
    "title": "Title",
    "author_names": "Author names",
    "author_emails": "Email addresses of authors",
    "email_sent": "Email sent",
    "email_sent_date": "Email sent date",
    "plagiarism": "Plagiarism",
    "orcid_id": "ORCID ID",
    "received_date": "Receive date",
    "review_date": "Review date",
    "review_rounds": "Review rounds",
    "accepted_date": "Acceptance date",
    "galley_sent_date": "Galley sent date",
    "galley_received_date": "Galley received date",
    "publish_date": "Publish date",
    "editorial_status": "Status",
    "repeat_done": "Repeat done",
    "doi_in_pdf": "DOI in PDF",
}

EDITORIAL_STATUSES = [
    "Submission",
    "Waiting for reviewer to be assigned",
    "Request for revisions",
    "Revisions have been submitted",
    "Sent for copy editing",
]


class ReviewRound(BaseModel):
    round: int = 1
    sent_date: Optional[str] = None
    received_date: Optional[str] = None


class AuthorArticleIn(BaseModel):
    wing: str = Field(default="in_process")
    journal_id: Optional[int] = None
    journal_title: str = ""
    ojs_number: str = ""
    title: str = ""
    author_names: str = ""
    author_emails: str = ""
    email_sent: bool = False
    email_sent_date: Optional[str] = None
    plagiarism: str = ""
    orcid_id: str = ""
    received_date: Optional[str] = None
    review_date: Optional[str] = None
    review_rounds: list[ReviewRound] = Field(default_factory=list)
    accepted_date: Optional[str] = None
    galley_sent_date: Optional[str] = None
    galley_received_date: Optional[str] = None
    publish_date: Optional[str] = None
    editorial_status: str = "Submission"
    repeat_done: bool = False
    doi_in_pdf: str = ""


class AuthorArticlePatch(BaseModel):
    wing: Optional[str] = None
    journal_id: Optional[int] = None
    journal_title: Optional[str] = None
    ojs_number: Optional[str] = None
    title: Optional[str] = None
    author_names: Optional[str] = None
    author_emails: Optional[str] = None
    email_sent: Optional[bool] = None
    email_sent_date: Optional[str] = None
    plagiarism: Optional[str] = None
    orcid_id: Optional[str] = None
    received_date: Optional[str] = None
    review_date: Optional[str] = None
    review_rounds: Optional[list[ReviewRound]] = None
    accepted_date: Optional[str] = None
    galley_sent_date: Optional[str] = None
    galley_received_date: Optional[str] = None
    publish_date: Optional[str] = None
    editorial_status: Optional[str] = None
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
    snapshot: dict = Field(default_factory=dict)


class AuthorArticleOut(BaseModel):
    id: int
    wing: str
    journal_id: Optional[int] = None
    journal_name: Optional[str] = None
    journal_title: str = ""
    owner_id: Optional[int] = None
    ojs_number: str = ""
    title: str = ""
    author_names: str = ""
    author_emails: str = ""
    email_sent: bool = False
    email_sent_date: Optional[str] = None
    plagiarism: str = ""
    orcid_id: str = ""
    received_date: Optional[str] = None
    review_date: Optional[str] = None
    review_rounds: list[ReviewRound] = Field(default_factory=list)
    accepted_date: Optional[str] = None
    galley_sent_date: Optional[str] = None
    galley_received_date: Optional[str] = None
    publish_date: Optional[str] = None
    editorial_status: str = "Submission"
    repeat_done: bool = False
    doi_in_pdf: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    original_snapshot: dict = Field(default_factory=dict)
    modifications: list[AuthorModificationOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class AuthorArticleDeleteIn(BaseModel):
    password: str = ""


class AuthorJournalIn(BaseModel):
    name: str
    abbreviation: str = ""


class AuthorJournalOut(BaseModel):
    id: Optional[int] = None
    name: str
    abbreviation: Optional[str] = None


class AuthorImportResult(BaseModel):
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = Field(default_factory=list)
    articles: list[AuthorArticleOut] = Field(default_factory=list)
