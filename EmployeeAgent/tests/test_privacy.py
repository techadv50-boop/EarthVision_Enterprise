from pathlib import Path

from app.privacy import FORBIDDEN_API_NAMES, privacy_statement


def test_privacy_statement_mentions_presence_only():
    text = privacy_statement().lower()
    assert "typed characters" in text
    assert "passwords" in text
    assert "screenshots" in text


def test_source_does_not_call_forbidden_apis():
    root = Path(__file__).resolve().parents[1] / "app"
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        if path.name == "privacy.py":
            continue
        text = path.read_text(encoding="utf-8")
        for name in FORBIDDEN_API_NAMES:
            if name in text:
                offenders.append(f"{path.name}: {name}")
    assert offenders == []


def test_events_do_not_store_private_payloads(tmp_path, clock, platform, password):
    from tests.conftest import build_service

    service = build_service(tmp_path, clock, platform, password)
    service.start()
    platform.emit_session("LOCKED")
    for event in service.engine.events:
        blob = str(event.details)
        assert "password" not in blob.lower()
        assert "keystroke" not in blob.lower()
        assert "clipboard" not in blob.lower()
        assert "x=" not in blob
        assert "screenshot" not in blob.lower()
