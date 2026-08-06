"""HTML parsing with BeautifulSoup."""

from __future__ import annotations

from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup

from webcrawler.extractors.email import extract_emails_from_text
from webcrawler.extractors.phone import extract_phones_from_text, region_from_url
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
        phone_region: str | None = None,
    ) -> ParsedPage:
        raw_html = html or ""
        soup = BeautifulSoup(raw_html, "lxml")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        title = (soup.title.string or "").strip() if soup.title else ""
        text = soup.get_text("\n", strip=True)

        internal: list[str] = []
        documents: list[str] = []
        images: list[str] = []
        seen: set[str] = set()
        emails: set[str] = set()
        phones: set[str] = set()
        region = phone_region or region_from_url(root_url or page_url)

        for tag in soup.find_all(["a", "area"]):
            href = (tag.get("href") or "").strip()
            if not href:
                continue
            lower = href.lower()
            if lower.startswith("mailto:"):
                addr = unquote(href.split(":", 1)[1].split("?", 1)[0])
                emails |= extract_emails_from_text(addr)
                continue
            if lower.startswith("tel:"):
                phones |= extract_phones_from_text(href, default_region=region)
                continue
            if lower.startswith(("javascript:", "data:", "#")):
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

        # Emails: scan visible text + raw HTML (obfuscation / attributes / JSON).
        # Phones: scan visible text only (raw HTML/CSS creates many false positives).
        emails |= extract_emails_from_text(text) | extract_emails_from_text(raw_html)
        phones |= extract_phones_from_text(text, default_region=region)

        return ParsedPage(
            url=page_url,
            title=title,
            internal_links=internal,
            document_links=documents,
            image_links=images,
            emails=emails,
            phones=phones,
            text=text,
            html=raw_html,
        )
