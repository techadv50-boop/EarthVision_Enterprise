"""URL normalization and validation helpers."""

from __future__ import annotations

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


def is_document_url(url: str, allowed_types: list[str] | None = None) -> bool:
    ext = extension_of(url).lstrip(".")
    if not ext:
        return False
    allowed = allowed_types or [e.lstrip(".") for e in DOCUMENT_EXTENSIONS]
    return ext in {t.lower().lstrip(".") for t in allowed}


def is_image_url(url: str) -> bool:
    return extension_of(url) in IMAGE_EXTENSIONS
