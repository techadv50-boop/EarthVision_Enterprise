"""Extract text from PDFs (pdfplumber, OCR fallback)."""

from __future__ import annotations

import io
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def extract_pdf_text(data: bytes) -> tuple[str, str]:
    """Return (text, ocr_status) where status is extracted|ocr|empty."""
    text = _pdfplumber_text(data)
    if text and len(text.strip()) >= 80:
        return text, "extracted"
    ocr_text = _ocr_text(data)
    if ocr_text and len(ocr_text.strip()) >= 40:
        return ocr_text, "ocr"
    return text or ocr_text or "", "empty"


def _pdfplumber_text(data: bytes) -> str:
    try:
        import pdfplumber
    except ImportError:
        logger.warning("pdfplumber not installed; PDF text extraction unavailable")
        return ""
    parts: list[str] = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                parts.append(page.extract_text() or "")
    except Exception:
        logger.exception("pdfplumber failed")
        return ""
    return "\n".join(parts)


def _ocr_text(data: bytes) -> str:
    try:
        from pdf2image import convert_from_bytes
        import pytesseract
    except ImportError:
        return ""
    try:
        images = convert_from_bytes(data, dpi=200, first_page=1, last_page=3)
    except Exception:
        logger.exception("pdf2image failed")
        return ""
    chunks = []
    for img in images:
        try:
            chunks.append(pytesseract.image_to_string(img) or "")
        except Exception:
            logger.exception("tesseract failed")
    return "\n".join(chunks)


extract_pdf_text = extract_pdf_text
