"""Local academic English checker used by the English review wing."""

from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape

from app.services.language_review import apply_gpt_settings, resolve_gpt, review_document, review_local, tool_catalog


def _docx(*texts: str) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p>" for text in texts)
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("word/document.xml", document)
    return buf.getvalue()


def test_local_checker_flags_slang_broken_and_filler():
    paragraphs = [
        "Introduction",
        "This paper gonna show that the kids used a lot of stuff in the field.",
        "Because the sensors failed and",
        "In order to estimate yield we used Sentinel-2.",
        "This is unclear.",
        "References",
        "[1] Smith, J. (2020). Groundwater mapping with sensors. IJIST.",
    ]
    issues = review_local(paragraphs)
    cats = {item["category"] for item in issues}
    quotes = " ".join(item["quote"].lower() for item in issues)
    assert "slang" in cats
    assert "gonna" in quotes or "kids" in quotes or "stuff" in quotes or "a lot of" in quotes
    assert "broken_sentence" in cats or "sentence_structure" in cats
    assert "conciseness" in cats or "irrelevant_word" in cats
    assert not any(item["paragraph_index"] == 6 for item in issues)


def test_local_checker_flags_spelling_and_article():
    issues = review_local(
        [
            "The recieve of an sample was seperate from the control.",
        ]
    )
    cats = {item["category"] for item in issues}
    quotes = " ".join(item["quote"].lower() for item in issues)
    assert "spelling" in cats
    assert "recieve" in quotes or "seperate" in quotes
    assert "grammar" in cats


def test_local_checker_flags_requested_academic_tools():
    issues = review_local(
        [
            "The stupid method was used and the results was wrong.",
            "It seems that the past history of the site is known.",
            "There is many plots in the trial.",
            "You should utilize the data more then the baseline.",
            "This paper believes the outcome proves that the model always works.",
            "After analyzing the samples, the results were cool.",
            "In this day and age mankind used well known sensors!",
        ]
    )
    cats = {item["category"] for item in issues}
    quotes = " ".join(item["quote"].lower() for item in issues)
    assert "abusive" in cats
    assert "stupid" in quotes
    assert "agreement" in cats
    assert "hedging" in cats or "redundancy" in cats
    assert "second_person" in cats
    assert "word_choice" in cats or "confused_words" in cats
    assert "anthropomorphism" in cats
    assert "overclaiming" in cats
    assert "exclamation" in cats
    assert "cliche" in cats or "bias_language" in cats or "hyphenation" in cats
    abusive = [item for item in issues if item["category"] == "abusive"]
    assert abusive and abusive[0]["severity"] == "high"
    assert any(item.get("rewrite") for item in issues)


def test_tool_catalog_lists_requested_checks():
    catalog = tool_catalog()
    ids = {item["id"] for item in catalog["tools"]}
    required = {
        "grammar",
        "sentence_structure",
        "broken_sentence",
        "run_on",
        "slang",
        "formality",
        "conciseness",
        "ambiguity",
        "word_choice",
        "repetition",
        "passive_voice",
        "abusive",
        "agreement",
        "hedging",
        "dangling_modifier",
        "confused_words",
    }
    assert required <= ids
    assert len(catalog["tools"]) >= 20
    assert catalog["gpt"]["available"] in {True, False}
    assert catalog["groups"]
    assert catalog["gpt"]["can_configure"] is True


class _FakeUser:
    def __init__(self):
        self.openai_api_key = ""
        self.openai_model = "gpt-4o-mini"
        self.gpt_review_enabled = None


async def test_apply_gpt_settings_saves_key_and_can_turn_off(monkeypatch):
    async def _ok(key: str, base: str):
        assert key.startswith("sk-")
        return None

    monkeypatch.setattr("app.services.language_review.verify_openai_key", _ok)
    user = _FakeUser()
    off = resolve_gpt(user)
    assert off.available is False
    runtime = await apply_gpt_settings(
        user,
        enabled=True,
        api_key="sk-test-abcdefghijklmnopqrstuvwxyz012345",
        model="gpt-4o-mini",
    )
    assert runtime.available is True
    assert user.gpt_review_enabled is True
    assert runtime.key_hint.endswith("2345")
    stopped = await apply_gpt_settings(user, enabled=False)
    assert stopped.available is False
    assert stopped.configured is True
    resumed = await apply_gpt_settings(user, enabled=True)
    assert resumed.available is True


async def test_review_document_returns_highlighted_payload():
    data = _docx(
        "Introduction",
        "The team kinda measured runoff and the results were cool.",
        "Materials and Methods",
        "Plots were irrigated twice each week.",
    )
    result = await review_document(data, "draft.docx")
    assert result["filename"] == "draft.docx"
    assert result["engine"] in {"local", "openai"}
    assert result["paragraphs"]
    assert result["summary"]["issue_count"] == len(result["issues"])
    assert any(issue["category"] == "slang" for issue in result["issues"])
    assert result["tools"]
    assert result["gpt"]["available"] in {True, False}
    flagged = [p for p in result["paragraphs"] if p["issue_ids"]]
    assert flagged
    assert all(isinstance(i, int) for p in flagged for i in p["issue_ids"])
