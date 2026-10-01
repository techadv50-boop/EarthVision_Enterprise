from app.extractor import clean_doi, parse_doi_list, parse_input_list


def test_clean_doi():
    assert clean_doi("https://doi.org/10.33411/IJIST/1936") == "10.33411/IJIST/1936"
    assert clean_doi("http://dx.doi.org/10.33411/IJIST/1936/") == "10.33411/IJIST/1936"
    assert clean_doi("10.33411/IJIST/1936") == "10.33411/IJIST/1936"


def test_parse_doi_list_dedupes():
    text = """
    https://doi.org/10.33411/IJIST/1936
    10.33411/IJIST/1936
    10.33411/IJIST/20190101011, https://doi.org/10.33411/IJIST/20190101022
    """
    dois = parse_doi_list(text)
    assert dois == [
        "10.33411/IJIST/1936",
        "10.33411/IJIST/20190101011",
        "10.33411/IJIST/20190101022",
    ]


def test_parse_input_list_accepts_article_urls():
    text = """
    https://doi.org/10.33411/IJIST/1936
    https://journal.50sea.com/index.php/IJIST/article/view/1936
    10.33411/IJIST/20190101011
    """
    items = parse_input_list(text)
    assert items[0] == "10.33411/IJIST/1936"
    assert items[1].startswith("https://journal.50sea.com/")
    assert items[2] == "10.33411/IJIST/20190101011"
