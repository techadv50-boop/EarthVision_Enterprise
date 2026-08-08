"""HTTP file downloader with SHA-256 duplicate detection."""

from __future__ import annotations

from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlparse

import httpx

from webcrawler.db.duplicates import DuplicateManager
from webcrawler.extractors.email import extract_emails_from_file
from webcrawler.extractors.phone import extract_phones_from_file
from webcrawler.logger.crawl_logger import CrawlLogger
from webcrawler.settings.manager import AppSettings
from webcrawler.utils.folders import destination_path, folder_for_extension
from webcrawler.utils.hashing import sha256_file
from webcrawler.utils.url import extension_of


class FileDownloader:
    def __init__(
        self,
        site_dir: Path,
        settings: AppSettings,
        duplicates: DuplicateManager,
        logger: CrawlLogger,
        on_download: Callable[[str, str], None] | None = None,
        phone_region: str | None = None,
    ) -> None:
        self.site_dir = site_dir
        self.settings = settings
        self.duplicates = duplicates
        self.logger = logger
        self.on_download = on_download
        self.phone_region = phone_region or "US"
        self.stats = {
            "documents": 0,
            "pdfs": 0,
            "word": 0,
            "excel": 0,
            "powerpoint": 0,
            "images": 0,
        }

    def download(self, url: str, is_image: bool = False) -> Path | None:
        if not url or any(ch in url for ch in ('"', "'", "`")):
            self.logger.skipped(url or "", "invalid URL")
            return None
        if not self.duplicates.should_download(url):
            self.logger.skipped(url, "duplicate URL")
            return None

        headers = {"User-Agent": self.settings.user_agent}
        timeout = httpx.Timeout(self.settings.download_timeout)
        last_error: Exception | None = None
        max_bytes = max(1_000_000, self.settings.max_download_bytes)

        for attempt in range(1, self.settings.retry_attempts + 1):
            try:
                with httpx.Client(
                    headers=headers,
                    timeout=timeout,
                    follow_redirects=self.settings.follow_redirects,
                    verify=False,
                    limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
                ) as client:
                    with client.stream("GET", url) as response:
                        if response.status_code in {404, 410}:
                            self.logger.skipped(url, f"HTTP {response.status_code}")
                            self.duplicates.mark_download(url, None, "", "missing")
                            return None
                        if response.status_code in {429, 503}:
                            raise httpx.HTTPStatusError(
                                f"HTTP {response.status_code}",
                                request=response.request,
                                response=response,
                            )
                        response.raise_for_status()
                        filename = self._filename_from_response(url, response)
                        dest = destination_path(self.site_dir, url, filename)
                        written = 0
                        with open(dest, "wb") as fh:
                            for chunk in response.iter_bytes():
                                written += len(chunk)
                                if written > max_bytes:
                                    fh.close()
                                    dest.unlink(missing_ok=True)
                                    self.logger.skipped(url, f"file larger than {max_bytes} bytes")
                                    self.duplicates.mark_download(url, None, "", "too_large")
                                    return None
                                fh.write(chunk)

                digest = sha256_file(dest)
                if self.duplicates.has_hash(digest):
                    dest.unlink(missing_ok=True)
                    self.logger.skipped(url, "duplicate SHA-256")
                    self.duplicates.mark_download(url, digest, "", "duplicate")
                    return None

                ext = dest.suffix.lower() or extension_of(url)
                file_type = folder_for_extension(ext)
                if not self.duplicates.mark_download(url, digest, str(dest), file_type):
                    dest.unlink(missing_ok=True)
                    return None

                self._bump_stats(file_type, is_image=is_image or file_type == "Images")
                self.logger.downloaded(url, str(dest))
                if self.on_download:
                    self.on_download(url, str(dest))

                for email in extract_emails_from_file(dest):
                    self.duplicates.add_email(email)
                for phone in extract_phones_from_file(
                    dest, default_region=self.phone_region
                ):
                    self.duplicates.add_phone(phone)
                return dest
            except Exception as exc:
                last_error = exc
                msg = str(exc).lower()
                # Do not burn retries on hard client errors except rate limits.
                if "404" in msg or "410" in msg:
                    self.duplicates.mark_download(url, None, "", "missing")
                    break
                self.logger.warning(f"Download attempt {attempt} failed for {url}: {exc}")
                time_sleep = min(0.4 * attempt, 3.0)
                import time

                time.sleep(time_sleep)

        self.logger.error(f"Failed to download {url}: {last_error}")
        return None

    def _bump_stats(self, file_type: str, is_image: bool = False) -> None:
        if is_image or file_type == "Images":
            self.stats["images"] += 1
            return
        self.stats["documents"] += 1
        mapping = {
            "PDF": "pdfs",
            "Word": "word",
            "Excel": "excel",
            "PowerPoint": "powerpoint",
        }
        key = mapping.get(file_type)
        if key:
            self.stats[key] += 1

    @staticmethod
    def _filename_from_response(url: str, response: httpx.Response) -> str:
        cd = response.headers.get("content-disposition", "")
        if "filename=" in cd:
            part = cd.split("filename=", 1)[1].strip().strip("\"'")
            if part:
                return Path(part).name
        name = unquote(Path(urlparse(url).path).name)
        if name:
            return name
        ext = extension_of(url) or ".bin"
        return f"download{ext}"
