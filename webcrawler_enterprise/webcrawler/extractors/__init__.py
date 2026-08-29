"""Contact extractors."""

from webcrawler.extractors.email import extract_emails_from_file, extract_emails_from_text
from webcrawler.extractors.phone import extract_phones_from_file, extract_phones_from_text

__all__ = [
    "extract_emails_from_file",
    "extract_emails_from_text",
    "extract_phones_from_file",
    "extract_phones_from_text",
]
