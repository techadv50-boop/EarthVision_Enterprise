"""Tests for email and phone extractors."""

from webcrawler.extractors.email import extract_emails_from_text
from webcrawler.extractors.phone import extract_phones_from_text


def test_extract_emails():
    text = "Contact info@company.org or research@university.edu and ignore image@cdn.com.png"
    emails = extract_emails_from_text(text)
    assert "info@company.org" in emails
    assert "research@university.edu" in emails
    assert "image@cdn.com.png" not in emails


def test_extract_phones_international():
    text = "Call +1 (617) 495-1000 or +44 20 7946 0958"
    phones = extract_phones_from_text(text, default_region="US")
    assert phones  # at least one valid number
