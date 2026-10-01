from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Author:
    name: str
    email: str | None = None
    workplace: str | None = None


@dataclass
class FileLink:
    url: str
    format: str


@dataclass
class ArticleMeta:
    doi: str = ""
    title: str = ""
    abstract: str = ""
    keywords: list[str] = field(default_factory=list)
    authors: list[Author] = field(default_factory=list)
    journal: str = ""
    pages: str = ""
    volume: str = ""
    issue: str = ""
    year: str = ""
    month: str = ""
    file_links: list[FileLink] = field(default_factory=list)
    landing_url: str = ""
    input_ref: str = ""  # original DOI or article URL provided by user
    source: str = ""
    error: str | None = None

    @property
    def ok(self) -> bool:
        return not self.error and bool(self.title)
