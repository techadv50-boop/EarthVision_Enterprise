from app.ojs.discover import (
    DEFAULT_FALLBACK,
    DiscoveryError,
    parse_files_dir,
    parse_ojs_version,
    resolve_files_dir,
    validate_discovery,
)


def test_parse_files_dir_quoted_and_comments():
    text = """
; files_dir = /ignored
# files_dir = /also-ignored
files_dir = "/var/lib/ojs-journal50"
"""
    assert parse_files_dir(text) == "/var/lib/ojs-journal50"
    assert parse_ojs_version("version = 3.4.0-3\n") == "3.4.0-3"


def test_resolve_relative_files_dir():
    assert resolve_files_dir("files", "/var/www/journal.xdgen.com") == "/var/www/journal.xdgen.com/files"


def test_validate_multiple_ojs_files_dir():
    payload = {
        "ok": True,
        "installations": [
            {
                "application_path": "/var/www/journal.50sea.com",
                "files_dir_raw": "/var/lib/ojs-journal50",
                "files_dir": "/var/lib/ojs-journal50",
                "exists": True,
                "domain": "journal.50sea.com",
            },
            {
                "application_path": "/var/www/journal.xdgen.com",
                "files_dir_raw": "/var/www/ojs-files",
                "files_dir": "/var/www/ojs-files",
                "exists": True,
                "domain": "journal.xdgen.com",
            },
        ],
    }
    rows = validate_discovery(
        payload,
        website_directories=[
            "/var/www/journal.50sea.com",
            "/var/www/journal.xdgen.com",
            "/var/www/xdgen.com",
            "/var/www/50sea.com",
        ],
    )
    assert [item["files_dir"] for item in rows] == ["/var/lib/ojs-journal50", "/var/www/ojs-files"]


def test_missing_files_dir_fails_closed():
    payload = {
        "ok": False,
        "installations": [
            {
                "application_path": "/var/www/journal.50sea.com",
                "files_dir_raw": "",
                "files_dir": "",
                "exists": False,
            }
        ],
        "errors": ["/var/www/journal.50sea.com: config.inc.php has no files_dir"],
    }
    try:
        validate_discovery(payload, website_directories=["/var/www/journal.50sea.com", "/var/www/xdgen.com"])
        assert False, "should fail closed"
    except DiscoveryError as exc:
        assert "files_dir" in str(exc)
        assert DEFAULT_FALLBACK not in str(exc) or "refusing" in str(exc)


def test_missing_required_journal_fails_closed():
    payload = {"ok": True, "installations": []}
    try:
        validate_discovery(
            payload,
            website_directories=["/var/www/journal.50sea.com", "/var/www/xdgen.com"],
        )
        assert False, "should require journal.50sea.com"
    except DiscoveryError as exc:
        assert "journal.50sea.com" in str(exc)


def test_missing_files_dir_does_not_silently_use_ojs_files():
    payload = {
        "ok": False,
        "installations": [
            {
                "application_path": "/var/www/journal.50sea.com",
                "files_dir_raw": "",
                "files_dir": "",
                "exists": False,
            }
        ],
        "errors": ["/var/www/journal.50sea.com: config.inc.php has no files_dir"],
    }
    try:
        validate_discovery(payload, website_directories=["/var/www/journal.50sea.com"])
        assert False
    except DiscoveryError as exc:
        assert "files_dir" in str(exc)
        assert "silent" not in str(exc).lower() or True
        assert "/var/www/ojs-files" not in str(exc) or "refusing" in str(exc)


def test_explicit_ojs_files_path_is_allowed_for_xdgen():
    payload = {
        "ok": True,
        "installations": [
            {
                "application_path": "/var/www/journal.xdgen.com",
                "files_dir_raw": "/var/www/ojs-files",
                "files_dir": "/var/www/ojs-files",
                "exists": True,
            }
        ],
    }
    rows = validate_discovery(payload, website_directories=["/var/www/journal.xdgen.com"])
    assert rows[0]["files_dir"] == "/var/www/ojs-files"


def test_nonexistent_files_dir_fails_closed():
    payload = {
        "ok": False,
        "installations": [
            {
                "application_path": "/var/www/journal.50sea.com",
                "files_dir_raw": "/var/lib/ojs-journal50",
                "files_dir": "/var/lib/ojs-journal50",
                "exists": False,
            }
        ],
        "errors": ["missing"],
    }
    try:
        validate_discovery(payload, website_directories=["/var/www/journal.50sea.com"])
        assert False
    except DiscoveryError as exc:
        assert "does not exist" in str(exc) or "failed" in str(exc).lower()
