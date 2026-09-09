"""Tests for URL utilities."""

from webcrawler.utils.url import (
    is_valid_url,
    normalize_url,
    parse_url_list,
    same_site,
)


def test_parse_url_list_dedupes_and_skips_blanks():
    text = """
    https://www.harvard.edu
    https://www.harvard.edu/
    https://www.mit.edu

    not-a-url
    https://www.mit.edu
    """
    urls = parse_url_list(text)
    assert len(urls) == 2
    assert urls[0].startswith("https://")
    assert "mit.edu" in urls[1]


def test_normalize_strips_tracking_and_fragment():
    a = normalize_url("https://Example.com/Path/?utm_source=x&b=2&a=1#section")
    b = normalize_url("https://example.com/Path?a=1&b=2")
    assert a == b


def test_same_site():
    assert same_site("https://www.nasa.gov/news", "https://nasa.gov")
    assert not same_site("https://external.com", "https://nasa.gov")


def test_is_valid_url():
    assert is_valid_url("https://stanford.edu")
    assert is_valid_url("stanford.edu")
    assert not is_valid_url("ftp://files.example")
    assert not is_valid_url("")
