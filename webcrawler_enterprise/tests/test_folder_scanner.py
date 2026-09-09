"""Local folder contact scanner tests."""

from pathlib import Path

from webcrawler.scanner.folder_scanner import FolderScanner, _eml_text, _build_report_lines, FolderScanResult, FailedFile


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
    report = (tmp_path / "folder_scan_report.txt").read_text(encoding="utf-8")
    assert "2 files in the folder" in report
    assert "2 scanned successfully" in report


def test_folder_scanner_skips_corrupt_files_and_reports_titles(tmp_path: Path):
    (tmp_path / "good.txt").write_text(
        "Reach us at good@acme-test.org\n",
        encoding="utf-8",
    )
    # Corrupt PDF / DOCX-like garbage that cannot be opened as a real document.
    (tmp_path / "broken invoice.pdf").write_bytes(b"%PDF-1.4\nthis is not a real pdf%%%%")
    (tmp_path / "corrupt notes.docx").write_bytes(b"PK\x03\x04not-a-real-docx")

    done = {"ok": False}
    logs: list[str] = []

    def _finished() -> None:
        done["ok"] = True

    scanner = FolderScanner(
        on_finished=_finished,
        on_log=logs.append,
        default_region="US",
    )
    scanner.start(tmp_path, recursive=False, use_ocr=False)
    scanner._thread.join(timeout=30)
    assert done["ok"] is True

    emails = (tmp_path / "emails.txt").read_text(encoding="utf-8")
    assert "good@acme-test.org" in emails

    report = (tmp_path / "folder_scan_report.txt").read_text(encoding="utf-8")
    assert "3 files in the folder" in report
    assert "1 scanned successfully" in report
    assert "could not be scanned" in report
    assert "broken invoice.pdf" in report
    assert "corrupt notes.docx" in report

    summary = (tmp_path / "folder_scan_summary.txt").read_text(encoding="utf-8")
    assert "Could not be scanned: 2" in summary
    assert "broken invoice.pdf" in summary

    # Scan must continue past corrupt files (contacts from good file still saved).
    assert any("Skipped corrupt" in line or "could not be scanned" in line for line in logs)


def test_build_report_lines_lists_failed_titles():
    result = FolderScanResult(
        folder="/tmp/docs",
        files_total=5,
        files_scanned=3,
        files_failed=2,
        failed_files=[
            FailedFile(title="a.pdf", relative_path="a.pdf", reason="corrupt"),
            FailedFile(title="b.docx", relative_path="sub/b.docx", reason="bad zip"),
        ],
    )
    lines = _build_report_lines(result)
    joined = "\n".join(lines)
    assert "There were 5 files in the folder out of which 3 scanned successfully." in joined
    assert "The following 2 file(s) could not be scanned:" in joined
    assert "- a.pdf" in joined
    assert "- b.docx" in joined
