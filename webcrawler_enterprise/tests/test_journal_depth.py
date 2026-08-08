"""Ensure OJS galley/deep article URLs are prioritized and not skipped."""

from webcrawler.crawler.site_crawler import (
    _galley_view_from_download,
    _is_priority_url,
    _should_skip_crawl_url,
)


def test_galley_view_urls_are_priority():
    assert _is_priority_url(
        "https://hamdardislamicus.com.pk/index.php/hi/article/view/101/113"
    )
    assert _is_priority_url(
        "https://hamdardislamicus.com.pk/index.php/hi/article/download/101/113"
    )


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
