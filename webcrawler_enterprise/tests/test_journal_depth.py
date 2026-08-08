"""Ensure OJS galley/deep article URLs are prioritized and not skipped."""

from webcrawler.crawler.site_crawler import (
    _galley_view_from_download,
    _is_priority_url,
    _should_skip_crawl_url,
    _url_priority_rank,
)


def test_galley_view_urls_are_priority():
    assert _is_priority_url(
        "https://hamdardislamicus.com.pk/index.php/hi/article/view/101/113"
    )
    assert _is_priority_url(
        "https://hamdardislamicus.com.pk/index.php/hi/article/download/101/113"
    )


def test_deep_priority_orders_pdf_before_galley_before_abstract():
    pdf = "https://example.com/index.php/hi/article/download/101/113"
    galley = "https://example.com/index.php/hi/article/view/101/113"
    abstract = "https://example.com/index.php/hi/article/view/101"
    chrome = "https://example.com/index.php/hi/about"
    assert _url_priority_rank(pdf) < _url_priority_rank(galley)
    assert _url_priority_rank(galley) < _url_priority_rank(abstract)
    assert _url_priority_rank(abstract) < _url_priority_rank(chrome)


def test_citation_style_urls_are_skipped():
    assert _should_skip_crawl_url(
        "https://hamdardislamicus.com.pk/index.php/hi/citationstylelanguage/get/apa?submissionId=101"
    )
    assert not _should_skip_crawl_url(
        "https://hamdardislamicus.com.pk/index.php/hi/article/view/101/113"
    )


def test_galley_derived_from_download():
    assert (
        _galley_view_from_download(
            "https://hamdardislamicus.com.pk/index.php/hi/article/download/101/113"
        )
        == "https://hamdardislamicus.com.pk/index.php/hi/article/view/101/113"
    )
    assert (
        _galley_view_from_download(
            "https://hamdardislamicus.com.pk/index.php/hi/article/download/101/113/182"
        )
        == "https://hamdardislamicus.com.pk/index.php/hi/article/view/101/113"
    )
