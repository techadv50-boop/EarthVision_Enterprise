"""HTML parser tests."""

from webcrawler.parser.html_parser import HtmlParser


HTML = """
<html><head><title>Demo</title></head>
<body>
  <a href="/about">About</a>
  <a href="https://external.com/x">External</a>
  <a href="/files/report.pdf">PDF</a>
  <a href="mailto:abc@xyz.com">Email</a>
  <p>Call +1 617-495-1000</p>
  <img src="/logo.png"/>
</body></html>
"""


def test_html_parser_extracts_links_and_contacts():
    parser = HtmlParser()
    parsed = parser.parse(HTML, "https://www.harvard.edu/", "https://www.harvard.edu")
    assert parsed.title == "Demo"
    assert any("about" in u for u in parsed.internal_links)
    assert any(u.endswith(".pdf") for u in parsed.document_links)
    assert any(u.endswith(".png") for u in parsed.image_links)
    assert "abc@xyz.com" in parsed.emails
    assert not any("external.com" in u for u in parsed.internal_links)
