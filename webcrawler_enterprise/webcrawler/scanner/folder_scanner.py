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
    "folder_scan_report.txt",
}

MAX_FILE_BYTES = 250 * 1024 * 1024

ProgressCallback = Callable[[dict], None]
LogCallback = Callable[[str], None]
FinishedCallback = Callable[[], None]
ControlFlag = Callable[[], str]


@dataclass
class FailedFile:
    """A file that could not be scanned (corrupt, unreadable, too large, etc.)."""

    title: str
    relative_path: str
    reason: str


@dataclass
class FolderScanResult:
    folder: str
    files_total: int = 0
    files_scanned: int = 0
    files_failed: int = 0
    failed_files: list[FailedFile] = field(default_factory=list)
    emails: set[str] = field(default_factory=set)
    phones: set[str] = field(default_factory=set)
    ocr_used: int = 0
    status: str = "Completed"
    error: str | None = None
    emails_path: str = ""
    phones_path: str = ""
    report_path: str = ""


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
            result.files_total = len(files)
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
                title = _file_title(path, root)
                self._emit(
                    status="Scanning folder",
                    current_website=str(root),
                    current_page=str(path),
                    current_download=title,
                    pages_crawled=index,
                    documents_downloaded=result.files_scanned,
                    websites_completed=0,
                    websites_remaining=max(total - index, 0),
                    emails_found=len(result.emails),
                    phone_numbers_found=len(result.phones),
                    elapsed_seconds=time.monotonic() - started,
                )

                # Too-large files: ignore content, record as not scanned.
                try:
                    size = path.stat().st_size
                except OSError as exc:
                    self._record_failure(result, path, root, f"cannot read file: {exc}")
                    continue
                if size > MAX_FILE_BYTES:
                    self._record_failure(
                        result, path, root, "file too large (>250MB) — skipped"
                    )
                    continue

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
                            f"Contacts in {title}: "
                            f"+{len(emails)} emails, +{len(phones)} phones"
                        )
                except Exception as exc:
                    # Corrupt / unreadable document — ignore and continue.
                    reason = _short_reason(exc)
                    self._record_failure(result, path, root, reason)
                    self._log(f"Skipped corrupt/unreadable file: {title} ({reason})")

            emails_path, phones_path, summary_path, report_path = self._write_outputs(
                root, result
            )
            result.emails_path = str(emails_path)
            result.phones_path = str(phones_path)
            result.report_path = str(report_path)

            report_lines = _build_report_lines(result)
            for line in report_lines:
                self._log(line)

            self._log(
                f"Saved: {emails_path.name}, {phones_path.name}, "
                f"{summary_path.name}, {report_path.name}"
            )
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
                message=(
                    f"Scan report: {result.files_total} files, "
                    f"{result.files_scanned} scanned, "
                    f"{result.files_failed} could not be scanned → {report_path.name}"
                ),
            )
        except Exception as exc:
            result.status = "Failed"
            result.error = str(exc)
            self._log(f"Folder scan failed: {exc}")
            try:
                self._write_outputs(root, result)
            except Exception:
                pass
        finally:
            with self._lock:
                self._state = "idle"
            if self.on_finished:
                try:
                    self.on_finished()
                except Exception:
                    pass

    def _record_failure(
        self, result: FolderScanResult, path: Path, root: Path, reason: str
    ) -> None:
        title = _file_title(path, root)
        rel = _relative_display(path, root)
        result.files_failed += 1
        result.failed_files.append(
            FailedFile(title=title, relative_path=rel, reason=reason)
        )

    def _list_files(self, root: Path, recursive: bool) -> list[Path]:
        files: list[Path] = []
        iterator = root.rglob("*") if recursive else root.glob("*")
        for path in iterator:
            try:
                if not path.is_file():
                    continue
            except OSError:
                continue
            if path.name.lower() in OUTPUT_NAMES:
                continue
            if path.suffix.lower() not in SUPPORTED_SUFFIXES:
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
            if not _pdf_can_open(path):
                raise RuntimeError("corrupt or unreadable PDF")
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
    ) -> tuple[Path, Path, Path, Path]:
        emails_path = root / "emails.txt"
        phones_path = root / "phone_numbers.txt"
        summary_path = root / "folder_scan_summary.txt"
        report_path = root / "folder_scan_report.txt"
        log_path = root / "folder_scan_log.txt"

        emails_sorted = sorted(result.emails)
        phones_sorted = sorted(result.phones)
        emails_path.write_text(
            "\n".join(emails_sorted) + ("\n" if emails_sorted else ""),
            encoding="utf-8",
        )
        phones_path.write_text(
            "\n".join(phones_sorted) + ("\n" if phones_sorted else ""),
            encoding="utf-8",
        )

        report_body = "\n".join(_build_report_lines(result)) + "\n"
        if result.failed_files:
            report_body += "\nDetails (file → reason):\n"
            for item in result.failed_files:
                report_body += f"  - {item.relative_path} → {item.reason}\n"
        report_path.write_text(report_body, encoding="utf-8")

        summary = [
            "WebCrawler Enterprise — Local Folder Scan",
            f"Time (UTC): {datetime.now(timezone.utc).isoformat()}",
            f"Folder: {result.folder}",
            f"Status: {result.status}",
            f"Files in folder (supported): {result.files_total}",
            f"Scanned successfully: {result.files_scanned}",
            f"Could not be scanned: {result.files_failed}",
            f"OCR used on: {result.ocr_used} file(s)",
            f"Unique emails: {len(result.emails)}",
            f"Unique phones: {len(result.phones)}",
            "",
            f"emails.txt → {emails_path}",
            f"phone_numbers.txt → {phones_path}",
            f"folder_scan_report.txt → {report_path}",
            "",
        ]
        summary.extend(_build_report_lines(result))
        if result.failed_files:
            summary.append("")
            summary.append("Details (file → reason):")
            for item in result.failed_files:
                summary.append(f"  - {item.relative_path} → {item.reason}")
        if result.error:
            summary.append(f"Error: {result.error}")
        summary_path.write_text("\n".join(summary) + "\n", encoding="utf-8")

        stamp = (
            f"\n[{datetime.now(timezone.utc).isoformat()}] "
            f"total={result.files_total} scanned={result.files_scanned} "
            f"failed={result.files_failed} emails={len(result.emails)} "
            f"phones={len(result.phones)} status={result.status}\n"
        )
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(stamp)

        return emails_path, phones_path, summary_path, report_path


def _build_report_lines(result: FolderScanResult) -> list[str]:
    lines = [
        f"There were {result.files_total} files in the folder out of which "
        f"{result.files_scanned} scanned successfully.",
    ]
    if result.files_failed <= 0:
        lines.append("All supported files were scanned successfully.")
        return lines

    lines.append(
        f"The following {result.files_failed} file(s) could not be scanned:"
    )
    for item in result.failed_files:
        lines.append(f"  - {item.title}")
    return lines


def _file_title(path: Path, root: Path) -> str:
    """Human-readable title for reports (filename; include parent if nested)."""
    try:
        rel = path.relative_to(root)
        return str(rel) if len(rel.parts) > 1 else path.name
    except ValueError:
        return path.name


def _relative_display(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return path.name


def _short_reason(exc: BaseException) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    text = text.replace("\n", " ").strip()
    if len(text) > 180:
        text = text[:177] + "..."
    return text


def _looks_thin_text(text: str) -> bool:
    cleaned = " ".join((text or "").split())
    return len(cleaned) < 40


def _pdf_can_open(path: Path) -> bool:
    """Return True if at least one PDF backend can open the file."""
    try:
        import fitz

        doc = fitz.open(path)
        try:
            _ = int(doc.page_count)
        finally:
            doc.close()
        return True
    except Exception:
        pass
    try:
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            _ = len(pdf.pages)
        return True
    except Exception:
        return False


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
                    parts.append(
                        payload.decode(
                            part.get_content_charset() or "utf-8", errors="ignore"
                        )
                    )
    else:
        try:
            parts.append(msg.get_content())
        except Exception:
            payload = msg.get_payload(decode=True) or b""
            parts.append(
                payload.decode(msg.get_content_charset() or "utf-8", errors="ignore")
            )
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
