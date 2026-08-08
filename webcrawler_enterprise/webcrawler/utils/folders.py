"""Folder layout helpers for website output."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

from webcrawler.utils.url import extension_of, get_registrable_domain

SUBFOLDERS = (
    "PDF",
    "Word",
    "Excel",
    "PowerPoint",
    "Images",
    "HTML",
    "Reports",
    "Logs",
)

EXT_TO_FOLDER = {
    ".pdf": "PDF",
    ".doc": "Word",
    ".docx": "Word",
    ".xls": "Excel",
    ".xlsx": "Excel",
    ".csv": "Excel",
    ".ppt": "PowerPoint",
    ".pptx": "PowerPoint",
    ".jpg": "Images",
    ".jpeg": "Images",
    ".png": "Images",
    ".gif": "Images",
    ".webp": "Images",
    ".svg": "Images",
    ".bmp": "Images",
    ".ico": "Images",
    ".tif": "Images",
    ".tiff": "Images",
    ".html": "HTML",
    ".htm": "HTML",
    ".txt": "Reports",
    ".zip": "Reports",
}

# Stay safely under Windows MAX_PATH issues for nested site mirrors.
MAX_PATH_LEN = 230


def site_folder(output_root: Path | str, website_url: str) -> Path:
    domain = get_registrable_domain(website_url)
    path = Path(output_root) / domain
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_site_structure(site_dir: Path) -> Path:
    for name in SUBFOLDERS:
        (site_dir / name).mkdir(parents=True, exist_ok=True)
    return site_dir


def folder_for_extension(ext: str) -> str:
    return EXT_TO_FOLDER.get(ext.lower(), "Reports")


def destination_path(site_dir: Path, url: str, filename: str | None = None) -> Path:
    ext = extension_of(url) or (Path(filename).suffix if filename else "")
    folder = folder_for_extension(ext)
    if not filename:
        name = unquote(Path(urlparse(url).path).name) or f"download{ext or '.bin'}"
        filename = name
    filename = _safe_segment(filename)
    if len(filename) > 80:
        stem = Path(filename).stem[:40]
        suffix = Path(filename).suffix
        digest = hashlib.sha1(filename.encode("utf-8", errors="ignore")).hexdigest()[:10]
        filename = f"{stem}_{digest}{suffix}"
    dest_dir = site_dir / folder
    dest_dir.mkdir(parents=True, exist_ok=True)
    return unique_path(dest_dir / filename)


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    parent = path.parent
    i = 1
    while True:
        candidate = parent / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def _safe_segment(segment: str) -> str:
    segment = unquote(segment).strip().replace("\\", "_").replace("/", "_")
    segment = re.sub(r"[<>:\"|?*\x00-\x1f]", "_", segment)
    segment = segment.strip(" .")
    return segment[:80] or "_"


def html_mirror_path(site_dir: Path, page_url: str) -> Path:
    """Build a readable on-disk path under HTML/, with hash fallback for long paths."""
    parsed = urlparse(page_url)
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        rel = Path("index.html")
    else:
        last = parts[-1]
        if "." in last and not last.lower().endswith((".html", ".htm")):
            parts[-1] = f"{last}.html"
            rel = Path(*[_safe_segment(p) for p in parts])
        elif last.lower().endswith((".html", ".htm")):
            rel = Path(*[_safe_segment(p) for p in parts])
        else:
            rel = Path(*[_safe_segment(p) for p in parts]) / "index.html"

    if parsed.query:
        q = _safe_segment(parsed.query)[:30]
        rel = rel.with_name(f"{rel.stem}_{q}{rel.suffix}")

    dest = site_dir / "HTML" / rel
    # Windows path-length safety: fall back to hashed filename
    if len(str(dest)) > MAX_PATH_LEN:
        digest = hashlib.sha1(page_url.encode("utf-8", errors="ignore")).hexdigest()
        dest = site_dir / "HTML" / "_hashed" / f"{digest}.html"
    dest.parent.mkdir(parents=True, exist_ok=True)
    return unique_path(dest)
