"""Duplicate tracking for pages, downloads, emails, and phones."""

from __future__ import annotations

from webcrawler.db.database import Database
from webcrawler.utils.url import normalize_url


class DuplicateManager:
    def __init__(self, db: Database, site_id: int) -> None:
        self.db = db
        self.site_id = site_id
        self._visited: set[str] = set()
        self._download_urls: set[str] = set()
        self._download_hashes: set[str] = set()
        self._emails: set[str] = set()
        self._phones: set[str] = set()
        self._load()

    def _load(self) -> None:
        for row in self.db.fetchall(
            "SELECT normalized_url FROM visited_pages WHERE site_id = ?",
            (self.site_id,),
        ):
            self._visited.add(row["normalized_url"])
        for row in self.db.fetchall(
            "SELECT normalized_url, sha256 FROM downloads WHERE site_id = ?",
            (self.site_id,),
        ):
            self._download_urls.add(row["normalized_url"])
            if row["sha256"]:
                self._download_hashes.add(row["sha256"])
        for row in self.db.fetchall(
            "SELECT email FROM emails WHERE site_id = ?",
            (self.site_id,),
        ):
            self._emails.add(row["email"])
        for row in self.db.fetchall(
            "SELECT phone FROM phones WHERE site_id = ?",
            (self.site_id,),
        ):
            self._phones.add(row["phone"])

    def has_visited(self, url: str) -> bool:
        return normalize_url(url) in self._visited

    def mark_visited(self, url: str, status_code: int | None = None) -> bool:
        normalized = normalize_url(url)
        if normalized in self._visited:
            return False
        self._visited.add(normalized)
        try:
            self.db.execute(
                "INSERT OR IGNORE INTO visited_pages (site_id, url, normalized_url, status_code) "
                "VALUES (?, ?, ?, ?)",
                (self.site_id, url, normalized, status_code),
            )
        except Exception:
            pass
        return True

    def should_download(self, url: str) -> bool:
        return normalize_url(url) not in self._download_urls

    def has_hash(self, sha256: str) -> bool:
        return sha256 in self._download_hashes

    def mark_download(
        self,
        url: str,
        sha256: str | None,
        file_path: str,
        file_type: str,
    ) -> bool:
        normalized = normalize_url(url)
        if normalized in self._download_urls:
            return False
        if sha256 and sha256 in self._download_hashes:
            return False
        self._download_urls.add(normalized)
        if sha256:
            self._download_hashes.add(sha256)
        self.db.execute(
            "INSERT OR IGNORE INTO downloads "
            "(site_id, url, normalized_url, sha256, file_path, file_type) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (self.site_id, url, normalized, sha256, file_path, file_type),
        )
        return True

    def add_email(self, email: str) -> bool:
        email = email.strip().lower()
        if not email or email in self._emails:
            return False
        self._emails.add(email)
        self.db.execute(
            "INSERT OR IGNORE INTO emails (site_id, email) VALUES (?, ?)",
            (self.site_id, email),
        )
        return True

    def add_phone(self, phone: str) -> bool:
        phone = phone.strip()
        if not phone or phone in self._phones:
            return False
        self._phones.add(phone)
        self.db.execute(
            "INSERT OR IGNORE INTO phones (site_id, phone) VALUES (?, ?)",
            (self.site_id, phone),
        )
        return True

    def clear_crawl_state(self, *, clear_contacts: bool = True) -> None:
        """Reset visited/download history so a site can be fully re-downloaded."""
        self.db.execute("DELETE FROM visited_pages WHERE site_id = ?", (self.site_id,))
        self.db.execute("DELETE FROM downloads WHERE site_id = ?", (self.site_id,))
        self.db.execute("DELETE FROM frontier WHERE site_id = ?", (self.site_id,))
        self._visited.clear()
        self._download_urls.clear()
        self._download_hashes.clear()
        if clear_contacts:
            self.db.execute("DELETE FROM emails WHERE site_id = ?", (self.site_id,))
            self.db.execute("DELETE FROM phones WHERE site_id = ?", (self.site_id,))
            self._emails.clear()
            self._phones.clear()

    @property
    def emails(self) -> set[str]:
        return set(self._emails)

    @property
    def phones(self) -> set[str]:
        return set(self._phones)

    @property
    def visited_count(self) -> int:
        return len(self._visited)

    @property
    def download_count(self) -> int:
        return len(self._download_urls)
