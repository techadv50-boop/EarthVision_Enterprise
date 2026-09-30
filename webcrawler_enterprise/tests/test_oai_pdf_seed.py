"""OAI-PMH ListRecords must expose article + galley + download PDF targets."""

import re

from webcrawler.utils.url import download_url_from_galley_view

SAMPLE_OAI = """
<record>
  <dc:identifier>https://hamdardislamicus.com.pk/index.php/hi/article/view/101</dc:identifier>
  <dc:relation>https://hamdardislamicus.com.pk/index.php/hi/article/view/101/113</dc:relation>
</record>
<record>
  <identifier>oai:ojs2.example:article/80</identifier>
  <dc:identifier>https://hamdardislamicus.com.pk/index.php/hi/article/view/80</dc:identifier>
  <dc:relation>https://hamdardislamicus.com.pk/index.php/hi/article/view/80/99</dc:relation>
</record>
"""


def test_oai_listrecords_exposes_galley_and_download():
    articles = re.findall(
        r"https?://[^<\s\"']+/article/view/\d+(?=/?(?:<|\s|$))",
        SAMPLE_OAI,
        re.I,
    )
    galleys = re.findall(
        r"https?://[^<\s\"']+/article/view/\d+/\d+/?",
        SAMPLE_OAI,
        re.I,
    )
    assert any(u.endswith("/article/view/101") for u in articles)
    assert any(u.rstrip("/").endswith("/article/view/101/113") for u in galleys)
    downloads = [download_url_from_galley_view(u) for u in galleys]
    assert (
        "https://hamdardislamicus.com.pk/index.php/hi/article/download/101/113"
        in downloads
    )
    assert (
        "https://hamdardislamicus.com.pk/index.php/hi/article/download/80/99"
        in downloads
    )


def test_oai_article_regex_does_not_swallow_galley():
    galleys = re.findall(
        r"https?://[^<\s\"']+/article/view/\d+/\d+/?",
        SAMPLE_OAI,
        re.I,
    )
    articles = re.findall(
        r"https?://[^<\s\"']+/article/view/\d+(?=/?(?:<|\s|$))",
        SAMPLE_OAI,
        re.I,
    )
    assert all(not re.search(r"/view/\d+/\d+", u) for u in articles)
    assert len(galleys) == 2
