"""OJS / journal PDF discovery and email cleanup."""

from webcrawler.extractors.email import extract_emails_from_text
from webcrawler.parser.html_parser import HtmlParser
from webcrawler.utils.url import is_document_url, looks_like_document_path


OJS_ARTICLE = """
<html><head>
<meta name="citation_pdf_url" content="https://hamdardislamicus.com.pk/index.php/hi/article/download/80/99"/>
<meta name="citation_abstract_html_url" content="https://hamdardislamicus.com.pk/index.php/hi/article/view/80"/>
<title>Sample</title>
</head>
<body>
<a href="https://hamdardislamicus.com.pk/index.php/hi/article/view/80/99">PDF</a>
<a href="/index.php/hi/issue/archive">Archive</a>
<p>Contact thameem@iium.edu.my</p>
</body></html>
"""


def test_ojs_download_path_is_document():
    url = "https://hamdardislamicus.com.pk/index.php/hi/article/download/80/99"
    assert looks_like_document_path(url)
    assert is_document_url(url, ["pdf", "doc", "docx"])


def test_parser_extracts_citation_pdf_url():
    parsed = HtmlParser().parse(
        OJS_ARTICLE,
        "https://hamdardislamicus.com.pk/index.php/hi/article/view/80",
        "https://hamdardislamicus.com.pk/",
        allowed_doc_types=["pdf", "doc", "docx"],
    )
    assert any("article/download/80/99" in u for u in parsed.document_links)
    assert "thameem@iium.edu.my" in parsed.emails
    assert any("issue/archive" in u for u in parsed.internal_links)


def test_rejects_pdf_layout_false_positive_emails():
    text = "2017@milliman.https 235-262@237-241.also also@risk.modern real.person@uop.edu.pk"
    emails = extract_emails_from_text(text)
    assert "real.person@uop.edu.pk" in emails
    assert "2017@milliman.https" not in emails
    assert "235-262@237-241.also" not in emails
    assert "also@risk.modern" not in emails
