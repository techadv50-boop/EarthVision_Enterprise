"""Tests for email and phone extractors."""

from webcrawler.extractors.email import extract_emails_from_text
from webcrawler.extractors.phone import extract_phones_from_text, region_from_url
from webcrawler.parser.html_parser import HtmlParser


def test_extract_emails():
    text = "Contact info@company.org or research@university.edu and ignore image@cdn.com.png"
    emails = extract_emails_from_text(text)
    assert "info@company.org" in emails
    assert "research@university.edu" in emails
    assert "image@cdn.com.png" not in emails


def test_extract_obfuscated_emails():
    text = "Write to admissions [at] qau [dot] edu [dot] pk for help"
    emails = extract_emails_from_text(text)
    assert "admissions@qau.edu.pk" in emails


def test_extract_phones_international():
    text = "Call +1 (617) 495-1000 or +44 20 7946 0958"
    phones = extract_phones_from_text(text, default_region="US")
    assert phones  # at least one valid number


def test_extract_pakistan_phones():
    text = "Phone: +92-51 9064-4082 and local 051-90642020 also mobile 0300-1234567"
    phones = extract_phones_from_text(text, default_region="PK")
    assert any("90644082" in p.replace(" ", "") for p in phones)
    assert any("90642020" in p.replace(" ", "") for p in phones)
    assert any(p.replace(" ", "").endswith("3001234567") for p in phones)


def test_region_from_url_pk():
    assert region_from_url("https://qau.edu.pk/contact-list/") == "PK"


def test_qau_like_html_extraction():
    html = """
    <html><body>
      <p>Email: info@qau.edu.pk</p>
      <p>Phone: +92-51 9064 0000</p>
      <a href="mailto:admissions@qau.edu.pk">Admissions</a>
      <a href="tel:+92-51-90643265">Call</a>
    </body></html>
    """
    parsed = HtmlParser().parse(
        html,
        "https://qau.edu.pk/",
        "https://qau.edu.pk/",
        phone_region="PK",
    )
    assert "info@qau.edu.pk" in parsed.emails
    assert "admissions@qau.edu.pk" in parsed.emails
    assert parsed.phones
