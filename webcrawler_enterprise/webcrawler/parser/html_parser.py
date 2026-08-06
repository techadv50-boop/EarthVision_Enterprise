"""HTML parsing with BeautifulSoup."""

from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from webcrawler.extractors.email import extract_emails_from_text
from webcrawler.extractors.phone import extract_phones_from_text
from webcrawler.utils.url import (
    DOCUMENT_EXTENSIONS,
    IMAGE_EXTENSIONS,
    extension_of,
    is_document_url,
    is_image_url,
    normalize_url,
    same_site,
)


class ParsedPage:
    def __init__(
        self,
        url: str,
        title: str,
        internal_links: list[str],
        document_links: list[str],
        image_links: list[str],
        emails: set[str],
        phones: set[str],
        text: str,
        html: str,
    ) -> None:
        self.url = url
        self.title = title
        self.internal_links = internal_links
        self.document_links = document_links
        self.image_links = image_links
        self.emails = emails
        self.phones = phones
        self.text = text
        self.html = html


class HtmlParser:
    def parse(
        self,
        html: str,
        page_url: str,
        root_url: str,
        allowed_doc_types: list[str] | None = None,
    ) -> ParsedPage:
        soup = BeautifulSoup(html or "", "lxml")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        title = (soup.title.string or "").strip() if soup.title else ""
        text = soup.get_text("\n", strip=True)

        internal: list[str] = []
        documents: list[str] = []
        images: list[str] = []
        seen: set[str] = set()

        for tag in soup.find_all(["a", "area"]):
            href = tag.get("href")
            if not href:
                continue
            href = href.strip()
            if href.startswith(("mailto:", "tel:", "javascript:", "data:", "#")):
                continue
            absolute = urljoin(page_url, href)
            try:
                normalized = normalize_url(absolute)
            except Exception:
                continue
            if normalized in seen:
                continue
            seen.add(normalized)

            ext = extension_of(normalized)
            if is_document_url(normalized, allowed_doc_types):
                documents.append(normalized)
            elif is_image_url(normalized) or ext in IMAGE_EXTENSIONS:
                images.append(normalized)
            elif same_site(normalized, root_url) and ext not in DOCUMENT_EXTENSIONS:
                internal.append(normalized)

        for tag in soup.find_all("img"):
            src = tag.get("src")
            if not src:
                continue
            absolute = normalize_url(urljoin(page_url, src))
            if absolute not in seen and is_image_url(absolute):
                images.append(absolute)
                seen.add(absolute)

        emails = extract_emails_from_text(html) | extract_emails_from_text(text)
        phones = extract_phones_from_text(text)

        # Also mailto: links
        for tag in BeautifulSoup(html or "", "lxml").find_all("a", href=True):
            href = tag["href"]
            if href.lower().startswith("mailto:"):
                addr = href.split(":", 1)[1].split("?", 1)[0]
                emails |= extract_emails_from_text(addr)

        return ParsedPage(
            url=page_url,
            title=title,
            internal_links=internal,
            document_links=documents,
            image_links=images,
            emails=emails,
            phones=phones,
            text=text,
            html=html,
        )
