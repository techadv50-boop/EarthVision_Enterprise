"""Author-name matching used to keep the same person off one issue."""

from app.services.author_sanitization import (
    authors_match,
    find_author_overlaps,
    overlap_message,
    split_author_names,
)


def test_split_semicolon_and_newline_authors():
    assert split_author_names("Ali Khan; Sara Ahmed") == ["Ali Khan", "Sara Ahmed"]
    assert split_author_names("Ali Khan\nSara Ahmed") == ["Ali Khan", "Sara Ahmed"]
    assert split_author_names("Khan, Ali") == ["Khan, Ali"]


def test_authors_match_order_and_initials():
    assert authors_match("Ali Khan", "Khan, Ali")
    assert authors_match("Ali Khan", "A. Khan")
    assert authors_match("Ali Khan", "Ali   Khan")
    assert not authors_match("Ali Khan", "Sara Khan")
    assert not authors_match("Ali Khan", "Ali Ahmed")


def test_unique_author_names_keeps_first_spelling():
    from app.services.author_sanitization import unique_author_names

    names = unique_author_names("Ali Khan; Noor Ali", "Khan, Ali\nSara Ahmed")
    assert names == ["Ali Khan", "Noor Ali", "Sara Ahmed"]


def test_find_overlaps_by_name_and_email():
    issue = [
        {
            "id": 11,
            "ojs_number": "IJIST-1",
            "title": "First paper",
            "author_names": "Ali Khan; Noor Ali",
            "author_emails": "ali@example.com",
        }
    ]
    hits = find_author_overlaps("Khan, Ali", "", issue)
    assert hits and hits[0].issue_ojs == "IJIST-1"
    email_hits = find_author_overlaps("Someone Else", "ali@example.com", issue)
    assert email_hits and email_hits[0].reason == "email"
    clean = find_author_overlaps("Sara Ahmed", "sara@example.com", issue)
    assert clean == []
    assert "cannot be published" in overlap_message(hits)
