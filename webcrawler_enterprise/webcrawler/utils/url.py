"""URL normalization and validation helpers."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import tldextract


TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
}


def ensure_scheme(url: str) -> str:
    url = url.strip()
    if not url:
        return ""
    if not urlparse(url).scheme:
        return f"https://{url}"
    return url


def is_valid_url(url: str) -> bool:
    try:
        parsed = urlparse(ensure_scheme(url))
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    if not parsed.netloc:
        return False
    host = parsed.hostname or ""
    # Require a dotted hostname (domain.tld) or localhost / IP.
    if host.lower() == "localhost":
        return True
    if all(part.isdigit() for part in host.split(".")) and host.count(".") == 3:
        return True
    extracted = tldextract.extract(host)
    if not extracted.domain or not extracted.suffix:
        return False
    return True


def get_registrable_domain(url: str) -> str:
    parsed = urlparse(ensure_scheme(url))
    extracted = tldextract.extract(parsed.netloc)
    if extracted.domain and extracted.suffix:
        return f"{extracted.domain}.{extracted.suffix}".lower()
    return parsed.netloc.lower().lstrip("www.")


def get_host(url: str) -> str:
    return urlparse(ensure_scheme(url)).netloc.lower()


def normalize_url(url: str, base: str | None = None) -> str:
    """Canonicalize a URL for duplicate detection."""
    if base:
        url = urljoin(base, url)
    url = ensure_scheme(url)
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    if netloc.endswith(":80") and scheme == "http":
        netloc = netloc[:-3]
    if netloc.endswith(":443") and scheme == "https":
        netloc = netloc[:-4]
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS
    ]
    query_pairs.sort()
    query = urlencode(query_pairs, doseq=True)
    return urlunparse((scheme, netloc, path, "", query, ""))


def same_site(url: str, root_url: str) -> bool:
    return get_registrable_domain(url) == get_registrable_domain(root_url)


def parse_url_list(text: str) -> list[str]:
    """Parse multiline URL input: strip blanks, validate, dedupe (order preserved)."""
    seen: set[str] = set()
    result: list[str] = []
    for line in text.splitlines():
        raw = line.strip()
        if not raw:
            continue
        url = ensure_scheme(raw)
        if not is_valid_url(url):
            continue
        key = normalize_url(url)
        if key in seen:
            continue
        seen.add(key)
        result.append(url)
    return result


DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".csv",
    ".txt",
    ".zip",
}

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".svg",
    ".bmp",
    ".ico",
    ".tif",
    ".tiff",
}


def extension_of(url: str) -> str:
    path = urlparse(url).path.lower()
    if "." in path.rsplit("/", 1)[-1]:
        return "." + path.rsplit(".", 1)[-1]
    return ""


# Extension-less CMS/journal download endpoints (Open Journal Systems, etc.).
DOCUMENT_PATH_MARKERS = (
    "/article/download/",
    "/articles/download/",
    "/index.php/article/download/",
    "/download/article/",
    "/bitstream/handle/",
    "/bitstream/",
    "/viewfile/",
    "/getfile/",
    "/file/download/",
    "/pdfviewer/",
)


def looks_like_document_path(url: str) -> bool:
    """True for known PDF/document endpoints that omit .pdf in the URL."""
    path = urlparse(ensure_scheme(url)).path.lower()
    if any(marker in path for marker in DOCUMENT_PATH_MARKERS):
        # Skip citation-style exports (ris/bibtex), keep submission downloads.
        if "citationstylelanguage" in path:
            return False
        return True
    # /galley/.../download or ?file=...&format=pdf
    if "/galley/" in path and "download" in path:
        return True
    query = urlparse(ensure_scheme(url)).query.lower()
    if "format=pdf" in query or "type=pdf" in query or "download=pdf" in query:
        return True
    return False


def download_url_from_galley_view(url: str) -> str | None:
    """Map OJS PDF-button URL /article/view/{id}/{galley} → /article/download/{id}/{galley}."""
    m = re.search(
        r"(https?://[^?#]+/article/)view/(\d+)/(\d+)/?$",
        url or "",
        re.I,
    )
    if not m:
        return None
    return f"{m.group(1)}download/{m.group(2)}/{m.group(3)}"


def galley_view_from_download_url(url: str) -> str | None:
    """Map /article/download/{id}/{galley}[/file] → /article/view/{id}/{galley}."""
    m = re.search(
        r"(https?://[^?#]+/article/)download/(\d+)/(\d+)(?:/\d+)?/?$",
        url or "",
        re.I,
    )
    if not m:
        return None
    return f"{m.group(1)}view/{m.group(2)}/{m.group(3)}"


def is_document_url(url: str, allowed_types: list[str] | None = None) -> bool:
    if looks_like_document_path(url):
        # Path-based PDFs count whenever PDF (or all docs) are allowed.
        allowed = {t.lower().lstrip(".") for t in (allowed_types or ["pdf"])}
        if not allowed or "pdf" in allowed or "*" in allowed:
            return True
    ext = extension_of(url).lstrip(".")
    if not ext:
        return False
    allowed = allowed_types or [e.lstrip(".") for e in DOCUMENT_EXTENSIONS]
    return ext in {t.lower().lstrip(".") for t in allowed}


def is_image_url(url: str) -> bool:
    return extension_of(url) in IMAGE_EXTENSIONS
