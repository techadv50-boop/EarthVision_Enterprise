from app.crawler import (
    extract_article_urls_from_html,
    extract_urls_from_sitemap_xml,
    is_article_html_url,
    is_pdf_or_galley_url,
)


def test_filters_pdf_and_galley_links():
    assert is_article_html_url("https://journal.50sea.com/index.php/IJIST/article/view/2028")
    assert not is_article_html_url("https://journal.50sea.com/index.php/IJIST/article/view/2028/3639")
    assert is_pdf_or_galley_url("https://journal.50sea.com/index.php/IJIST/article/view/2028/3639")
    assert is_pdf_or_galley_url("https://example.com/paper.pdf")
    assert is_pdf_or_galley_url("https://journal.50sea.com/index.php/IJIST/article/download/2028/3639")


def test_extract_article_urls_excludes_pdf_galleys():
    html = """
    <div class="obj_article_summary">
      <h3 class="title"><a href="/index.php/IJIST/article/view/2028">Title A</a></h3>
      <a class="obj_galley_link pdf" href="/index.php/IJIST/article/view/2028/3639">PDF</a>
    </div>
    <div class="obj_article_summary">
      <h3 class="title"><a href="/index.php/IJIST/article/view/2039">Title B</a></h3>
      <a class="obj_galley_link pdf" href="/index.php/IJIST/article/view/2039/3641">PDF</a>
    </div>
    """
    urls = extract_article_urls_from_html(html, "https://journal.50sea.com/index.php/IJIST/issue/view/97")
    assert urls == [
        "https://journal.50sea.com/index.php/IJIST/article/view/2028",
        "https://journal.50sea.com/index.php/IJIST/article/view/2039",
    ]


def test_sitemap_parser_keeps_articles_excludes_galleys():
    xml = """<?xml version="1.0" encoding="utf-8"?>
    <urlset>
      <url><loc>https://journal.50sea.com/index.php/IJIST/article/view/2028</loc></url>
      <url><loc>https://journal.50sea.com/index.php/IJIST/article/view/2028/3639</loc></url>
      <url><loc>https://journal.50sea.com/index.php/IJIST/issue/view/97</loc></url>
      <url><loc>https://journal.50sea.com/index.php/IJIST/article/view/urban-heat-island-3</loc></url>
    </urlset>
    """
    arts, issues = extract_urls_from_sitemap_xml(xml)
    assert arts == [
        "https://journal.50sea.com/index.php/IJIST/article/view/2028",
        "https://journal.50sea.com/index.php/IJIST/article/view/urban-heat-island-3",
    ]
    assert issues == ["https://journal.50sea.com/index.php/IJIST/issue/view/97"]
