"""Local folder contact scanner tests."""

from pathlib import Path

from webcrawler.scanner.folder_scanner import FolderScanner, _eml_text


def test_eml_extracts_header_emails(tmp_path: Path):
    eml = tmp_path / "note.eml"
    eml.write_text(
        "From: Alice <alice@example.com>\n"
        "To: Bob <bob@example.org>\n"
        "Subject: Hello\n"
        "Content-Type: text/plain; charset=utf-8\n"
        "\n"
        "Please call me. Also cc carol@example.net\n",
        encoding="utf-8",
    )
    text = _eml_text(eml)
    assert "alice@example.com" in text.lower()
    assert "bob@example.org" in text.lower()
    assert "carol@example.net" in text.lower()


def test_folder_scanner_writes_emails_and_phones(tmp_path: Path):
    (tmp_path / "a.txt").write_text(
        "Contact support@acme-test.org or +1 617-555-0100\n",
        encoding="utf-8",
    )
    (tmp_path / "mail.eml").write_text(
        "From: dave@acme-test.org\nTo: eve@acme-test.org\nSubject: Hi\n\nThanks\n",
        encoding="utf-8",
    )

    done = {"ok": False}

    def _finished() -> None:
        done["ok"] = True

    scanner = FolderScanner(on_finished=_finished, default_region="US")
    scanner.start(tmp_path, recursive=False, use_ocr=False)
    scanner._thread.join(timeout=30)
    assert done["ok"] is True

    emails = (tmp_path / "emails.txt").read_text(encoding="utf-8")
    phones = (tmp_path / "phone_numbers.txt").read_text(encoding="utf-8")
    assert "support@acme-test.org" in emails
    assert "dave@acme-test.org" in emails
    assert "eve@acme-test.org" in emails
    assert "+1" in phones or "617" in phones
    assert (tmp_path / "folder_scan_summary.txt").exists()
