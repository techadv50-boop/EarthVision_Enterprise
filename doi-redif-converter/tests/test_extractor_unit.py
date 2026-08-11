from app.extractor import clean_doi, parse_doi_list


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
