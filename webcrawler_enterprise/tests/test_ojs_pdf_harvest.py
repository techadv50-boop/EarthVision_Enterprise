"""OJS PDF button → download URL harvest (Hamdard-style)."""

from pathlib import Path

from webcrawler.parser.html_parser import HtmlParser
from webcrawler.utils.url import download_url_from_galley_view, galley_view_from_download_url


ARTICLE_HTML = """
<html><head>
<meta name="citation_pdf_url" content="https://hamdardislamicus.com.pk/index.php/hi/article/download/101/113"/>
</head><body>
<a class="obj_galley_link pdf" href="https://hamdardislamicus.com.pk/index.php/hi/article/view/101/113">PDF</a>
</body></html>
"""

GALLEY_HTML = """
<html><body>
<a href="https://hamdardislamicus.com.pk/index.php/hi/article/download/101/113/182" class="download" download>Download PDF</a>
<script>
var pdfUrl = "https:\\/\\/hamdardislamicus.com.pk\\/index.php\\/hi\\/article\\/download\\/101\\/113\\/182";
</script>
</body></html>
"""

ISSUE_HTML = """
<html><body>
<a href="https://hamdardislamicus.com.pk/index.php/hi/article/view/101">Article</a>
<a class="obj_galley_link pdf" href="https://hamdardislamicus.com.pk/index.php/hi/article/view/101/113">PDF</a>
</body></html>
"""


def test_galley_view_maps_to_download():
    assert (
        download_url_from_galley_view(
            "https://hamdardislamicus.com.pk/index.php/hi/article/view/101/113"
        )
        == "https://hamdardislamicus.com.pk/index.php/hi/article/download/101/113"
    )
    assert (
        galley_view_from_download_url(
            "https://hamdardislamicus.com.pk/index.php/hi/article/download/101/113/182"
        )
        == "https://hamdardislamicus.com.pk/index.php/hi/article/view/101/113"
    )


def test_article_page_finds_pdf_download_and_galley():
    parsed = HtmlParser().parse(
        ARTICLE_HTML,
        "https://hamdardislamicus.com.pk/index.php/hi/article/view/101/",
        "https://hamdardislamicus.com.pk/",
    )
    assert any(
        u.rstrip("/").endswith("/article/download/101/113") for u in parsed.document_links
    )
    assert any(
        u.rstrip("/").endswith("/article/view/101/113") for u in parsed.internal_links
    )


def test_galley_page_finds_pdf_in_js_and_download_link():
    parsed = HtmlParser().parse(
        GALLEY_HTML,
        "https://hamdardislamicus.com.pk/index.php/hi/article/view/101/113",
        "https://hamdardislamicus.com.pk/",
    )
    assert any("/article/download/101/113" in u for u in parsed.document_links)


def test_issue_toc_pdf_button_synthesizes_download():
    parsed = HtmlParser().parse(
        ISSUE_HTML,
        "https://hamdardislamicus.com.pk/index.php/hi/issue/view/15",
        "https://hamdardislamicus.com.pk/",
    )
    assert any(
        u.rstrip("/").endswith("/article/view/101/113") for u in parsed.internal_links
    )
    assert any(
        u.rstrip("/").endswith("/article/download/101/113") for u in parsed.document_links
    )


def test_live_hamdard_fixture_if_present():
    fixture = Path("/tmp/hi101.html")
    if not fixture.exists():
        return
    parsed = HtmlParser().parse(
        fixture.read_text(encoding="utf-8", errors="ignore"),
        "https://hamdardislamicus.com.pk/index.php/hi/article/view/101/",
        "https://hamdardislamicus.com.pk/",
    )
    assert any("/article/download/101/113" in u for u in parsed.document_links)
    assert any("/article/view/101/113" in u for u in parsed.internal_links)
