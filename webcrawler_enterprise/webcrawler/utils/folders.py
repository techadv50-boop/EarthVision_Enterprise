"""Folder layout helpers for website output."""

from __future__ import annotations

from pathlib import Path

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
        from urllib.parse import unquote, urlparse

        name = unquote(Path(urlparse(url).path).name) or f"download{ext or '.bin'}"
        filename = name
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
