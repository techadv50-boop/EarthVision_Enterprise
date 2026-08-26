"""Scan a local folder of documents for emails and phone numbers."""

from __future__ import annotations

import email
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email import policy
from pathlib import Path
from typing import Callable

from webcrawler.extractors.email import (
    _docx_text,
    _pdf_text,
    _xlsx_text,
    extract_emails_from_text,
)
from webcrawler.extractors.phone import extract_phones_from_text

SUPPORTED_SUFFIXES = {
    ".pdf",
    ".docx",
    ".doc",
    ".xlsx",
    ".xlsm",
    ".xls",
    ".html",
    ".htm",
    ".txt",
    ".csv",
    ".xml",
    ".eml",
    ".msg",
    ".rtf",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".webp",
    ".bmp",
}

# Skip writing into our own output names while scanning.
OUTPUT_NAMES = {
    "emails.txt",
    "phone_numbers.txt",
    "phones.txt",
    "folder_scan_log.txt",
    "folder_scan_summary.txt",
}


ProgressCallback = Callable[[dict], None]
LogCallback = Callable[[str], None]
FinishedCallback = Callable[[], None]
ControlFlag = Callable[[], str]


@dataclass
class FolderScanResult:
    folder: str
    files_scanned: int = 0
    files_failed: int = 0
    emails: set[str] = field(default_factory=set)
    phones: set[str] = field(default_factory=set)
    ocr_used: int = 0
    status: str = "Completed"
    error: str | None = None
    emails_path: str = ""
    phones_path: str = ""


class FolderScanner:
    """Walk a folder, extract contacts from each supported file, write txt outputs."""

    def __init__(
        self,
        on_progress: ProgressCallback | None = None,
        on_log: LogCallback | None = None,
        on_finished: FinishedCallback | None = None,
        control_state: ControlFlag | None = None,
        default_region: str = "US",
    ) -> None:
        self.on_progress = on_progress
        self.on_log = on_log
        self.on_finished = on_finished
        self.control_state = control_state or (lambda: "running")
        self.default_region = default_region
        self._thread: threading.Thread | None = None
        self._state = "idle"
        self._lock = threading.Lock()

    def is_busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def stop(self) -> None:
        with self._lock:
            self._state = "stopped"

    def _ctrl(self) -> str:
        with self._lock:
            if self._state == "stopped":
                return "stopped"
        return self.control_state()

    def start(
        self,
        folder: str | Path,
        *,
        recursive: bool = True,
        use_ocr: bool = True,
    ) -> None:
        if self.is_busy():
            raise RuntimeError("Folder scan already in progress")
        root = Path(folder).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"Folder does not exist: {root}")
        with self._lock:
            self._state = "running"
        self._thread = threading.Thread(
            target=self._run,
            kwargs={"root": root, "recursive": recursive, "use_ocr": use_ocr},
            name="FolderScanner",
            daemon=True,
        )
        self._thread.start()

    def _log(self, message: str) -> None:
        if self.on_log:
            try:
                self.on_log(message)
            except Exception:
                pass

    def _emit(self, **kwargs) -> None:
        if self.on_progress:
            try:
                self.on_progress(kwargs)
            except Exception:
                pass

    def _run(self, root: Path, recursive: bool, use_ocr: bool) -> None:
        result = FolderScanResult(folder=str(root))
        started = time.monotonic()
        try:
            files = self._list_files(root, recursive=recursive)
            total = len(files)
            self._log(f"Local folder scan: {total} file(s) in {root}")
            self._emit(
                status="Scanning folder",
                current_website=str(root),
                websites_total=1,
                websites_remaining=0,
                pages_crawled=0,
                documents_downloaded=0,
                emails_found=0,
                phone_numbers_found=0,
            )
            for index, path in enumerate(files, start=1):
                if self._ctrl() == "stopped":
                    result.status = "Cancelled"
                    result.error = "Folder scan stopped by user"
                    self._log("Folder scan stopped by user")
                    break
                self._emit(
                    status="Scanning folder",
                    current_website=str(root),
                    current_page=str(path),
                    current_download=path.name,
                    pages_crawled=index,
                    documents_downloaded=index,
                    websites_completed=0,
                    websites_remaining=max(total - index, 0),
                    emails_found=len(result.emails),
                    phone_numbers_found=len(result.phones),
                    elapsed_seconds=time.monotonic() - started,
                )
                try:
                    text, used_ocr = self._file_text(path, use_ocr=use_ocr)
                    if used_ocr:
                        result.ocr_used += 1
                    emails = extract_emails_from_text(text)
                    phones = extract_phones_from_text(
                        text, default_region=self.default_region
                    )
                    result.emails |= emails
                    result.phones |= phones
                    result.files_scanned += 1
                    if emails or phones:
                        self._log(
                            f"Contacts in {path.name}: "
                            f"+{len(emails)} emails, +{len(phones)} phones"
                        )
                except Exception as exc:
                    result.files_failed += 1
                    self._log(f"Failed reading {path.name}: {exc}")

            emails_path, phones_path, summary_path = self._write_outputs(root, result)
            result.emails_path = str(emails_path)
            result.phones_path = str(phones_path)
            self._log(
                f"Folder scan finished ({result.status}): "
                f"files={result.files_scanned}, failed={result.files_failed}, "
                f"emails={len(result.emails)}, phones={len(result.phones)}, "
                f"ocr_files={result.ocr_used}"
            )
            self._log(f"Saved: {emails_path.name}, {phones_path.name}, {summary_path.name}")
            self._emit(
                status=result.status,
                current_website=str(root),
                current_page="",
                current_download="",
                pages_crawled=result.files_scanned,
                documents_downloaded=result.files_scanned,
                emails_found=len(result.emails),
                phone_numbers_found=len(result.phones),
                elapsed_seconds=time.monotonic() - started,
                message=f"Saved contacts into {root}",
            )
        except Exception as exc:
            result.status = "Failed"
            result.error = str(exc)
            self._log(f"Folder scan failed: {exc}")
        finally:
            with self._lock:
                self._state = "idle"
            if self.on_finished:
                try:
                    self.on_finished()
                except Exception:
                    pass

    def _list_files(self, root: Path, recursive: bool) -> list[Path]:
        files: list[Path] = []
        iterator = root.rglob("*") if recursive else root.glob("*")
        for path in iterator:
            if not path.is_file():
                continue
            if path.name.lower() in OUTPUT_NAMES:
                continue
            if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            # Skip huge files (>250 MB) to avoid memory blowups.
            try:
                if path.stat().st_size > 250 * 1024 * 1024:
                    self._log(f"Skipping large file (>250MB): {path.name}")
                    continue
            except OSError:
                continue
            files.append(path)
        files.sort(key=lambda p: str(p).lower())
        return files

    def _file_text(self, path: Path, use_ocr: bool) -> tuple[str, bool]:
        suffix = path.suffix.lower()
        used_ocr = False
        text = ""

        if suffix == ".eml":
            text = _eml_text(path)
        elif suffix == ".msg":
            text = _msg_text(path)
        elif suffix in {".html", ".htm", ".txt", ".csv", ".xml", ".rtf"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
        elif suffix == ".pdf":
            text = _pdf_text(path)
            if use_ocr and _looks_thin_text(text):
                ocr_text = _pdf_ocr_text(path)
                if ocr_text.strip():
                    text = f"{text}\n{ocr_text}".strip()
                    used_ocr = True
        elif suffix == ".docx":
            text = _docx_text(path)
        elif suffix in {".xlsx", ".xlsm"}:
            text = _xlsx_text(path)
        elif suffix == ".doc":
            # Best-effort: many .doc files still contain readable ASCII/UTF-8 strings.
            raw = path.read_bytes()
            text = raw.decode("utf-8", errors="ignore")
            if _looks_thin_text(text):
                text = raw.decode("latin-1", errors="ignore")
        elif suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp"}:
            if use_ocr:
                text = _image_ocr_text(path)
                used_ocr = bool(text.strip())
            else:
                text = ""
        else:
            text = path.read_text(encoding="utf-8", errors="ignore")

        return text or "", used_ocr

    def _write_outputs(
        self, root: Path, result: FolderScanResult
    ) -> tuple[Path, Path, Path]:
        emails_path = root / "emails.txt"
        phones_path = root / "phone_numbers.txt"
        summary_path = root / "folder_scan_summary.txt"
        log_path = root / "folder_scan_log.txt"

        emails_sorted = sorted(result.emails)
        phones_sorted = sorted(result.phones)
        emails_path.write_text("\n".join(emails_sorted) + ("\n" if emails_sorted else ""), encoding="utf-8")
        phones_path.write_text("\n".join(phones_sorted) + ("\n" if phones_sorted else ""), encoding="utf-8")

        summary = [
            "WebCrawler Enterprise — Local Folder Scan",
            f"Time (UTC): {datetime.now(timezone.utc).isoformat()}",
            f"Folder: {result.folder}",
            f"Status: {result.status}",
            f"Files scanned: {result.files_scanned}",
            f"Files failed: {result.files_failed}",
            f"OCR used on: {result.ocr_used} file(s)",
            f"Unique emails: {len(result.emails)}",
            f"Unique phones: {len(result.phones)}",
            "",
            f"emails.txt → {emails_path}",
            f"phone_numbers.txt → {phones_path}",
        ]
        if result.error:
            summary.append(f"Error: {result.error}")
        summary_path.write_text("\n".join(summary) + "\n", encoding="utf-8")

        # Append a short stamp to the log file (do not wipe user notes).
        stamp = (
            f"\n[{datetime.now(timezone.utc).isoformat()}] "
            f"scanned={result.files_scanned} emails={len(result.emails)} "
            f"phones={len(result.phones)} status={result.status}\n"
        )
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(stamp)

        return emails_path, phones_path, summary_path


def _looks_thin_text(text: str) -> bool:
    cleaned = " ".join((text or "").split())
    return len(cleaned) < 40


def _eml_text(path: Path) -> str:
    data = path.read_bytes()
    msg = email.message_from_bytes(data, policy=policy.default)
    parts: list[str] = []
    for header in ("From", "To", "Cc", "Bcc", "Reply-To", "Sender", "Subject"):
        value = msg.get(header)
        if value:
            parts.append(f"{header}: {value}")
    if msg.is_multipart():
        for part in msg.walk():
            ctype = (part.get_content_type() or "").lower()
            if ctype in {"text/plain", "text/html"}:
                try:
                    parts.append(part.get_content())
                except Exception:
                    payload = part.get_payload(decode=True) or b""
                    parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="ignore"))
    else:
        try:
            parts.append(msg.get_content())
        except Exception:
            payload = msg.get_payload(decode=True) or b""
            parts.append(payload.decode(msg.get_content_charset() or "utf-8", errors="ignore"))
    return "\n".join(str(p) for p in parts if p)


def _msg_text(path: Path) -> str:
    """Best-effort Outlook .msg scrape without extra dependencies."""
    raw = path.read_bytes()
    # Extract readable ASCII/UTF-8 runs that often include headers and bodies.
    text = raw.decode("utf-8", errors="ignore")
    if _looks_thin_text(text):
        text = raw.decode("latin-1", errors="ignore")
    return text


def _pdf_ocr_text(path: Path) -> str:
    """OCR a PDF when native text is missing (needs Tesseract if using PyMuPDF OCR)."""
    chunks: list[str] = []
    try:
        import fitz

        doc = fitz.open(path)
        try:
            for page in doc:
                page_text = ""
                try:
                    # PyMuPDF OCR path (Tesseract must be installed on the machine).
                    tp = page.get_textpage_ocr(dpi=200, full=True)
                    page_text = page.get_text(textpage=tp) or ""
                except Exception:
                    page_text = ""
                if not page_text.strip():
                    # Fallback: rasterize page and OCR via pytesseract if available.
                    try:
                        pix = page.get_pixmap(dpi=200)
                        page_text = _ocr_pixmap_bytes(pix.tobytes("png"))
                    except Exception:
                        page_text = ""
                if page_text:
                    chunks.append(page_text)
        finally:
            doc.close()
    except Exception:
        return ""
    return "\n".join(chunks)


def _image_ocr_text(path: Path) -> str:
    try:
        data = path.read_bytes()
        return _ocr_pixmap_bytes(data)
    except Exception:
        return ""


def _ocr_pixmap_bytes(png_or_image_bytes: bytes) -> str:
    """OCR image bytes with pytesseract when installed; otherwise return empty."""
    try:
        import pytesseract
        from PIL import Image
        import io

        image = Image.open(io.BytesIO(png_or_image_bytes))
        return pytesseract.image_to_string(image) or ""
    except Exception:
        return ""
