"""Schemas for the author database management system."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


WINGS = ("in_process", "published")


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

    model_config = {"from_attributes": True}
