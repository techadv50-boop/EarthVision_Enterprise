"""HTTP tests for Reference check and English review wings."""

from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape

import pytest
from httpx import AsyncClient


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


@pytest.mark.asyncio
async def test_reference_integrity_and_language_review_endpoints(
    client: AsyncClient, auth_headers: dict[str, str]
):
    original = _docx(
        "Introduction",
        "Body text.",
        "References",
        "[1] Smith, J. (2020). Groundwater mapping with sensors. IJIST.",
        "[2] Khan, A. (2021). Urban heat islands in arid basins. IJIST.",
    )
    shuffled = _docx(
        "Introduction",
        "Body text.",
        "References",
        "[2] Khan, A. (2021). Urban heat islands in arid basins. IJIST.",
        "[1] Smith, J. (2020). Groundwater mapping with sensors. IJIST.",
    )
    missing = _docx(
        "Introduction",
        "References",
        "[1] Smith, J. (2020). Groundwater mapping with sensors. IJIST.",
    )
    ok = await client.post(
        "/api/v1/review/reference-integrity",
        headers=auth_headers,
        files={
            "original": (
                "original.docx",
                original,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
            "returned": (
                "returned.docx",
                shuffled,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        },
    )
    assert ok.status_code == 200, ok.text
    payload = ok.json()
    assert payload["status"] in {"pass", "warn"}
    assert payload["order_changed"] is True
    assert payload["removed"] == []
    assert payload.get("overall")

    fail = await client.post(
        "/api/v1/review/reference-integrity",
        headers=auth_headers,
        files={
            "original": (
                "original.docx",
                original,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
            "returned": (
                "returned.docx",
                missing,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        },
    )
    assert fail.status_code == 200, fail.text
    assert fail.json()["status"] == "fail"
    assert fail.json()["removed"]

    unauth = await client.post(
        "/api/v1/review/reference-integrity",
        files={
            "original": (
                "original.docx",
                original,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
            "returned": (
                "returned.docx",
                shuffled,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        },
    )
    assert unauth.status_code == 401

    language = await client.post(
        "/api/v1/review/language",
        headers=auth_headers,
        files={
            "file": (
                "draft.docx",
                _docx(
                    "Introduction",
                    "This paper gonna show that the kids used a lot of stuff.",
                ),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert language.status_code == 200, language.text
    review = language.json()
    assert review["issues"]
    assert review["paragraphs"]
    assert any(item["category"] == "slang" for item in review["issues"])
    assert review["tools"]
    assert any(item["id"] == "abusive" for item in review["tools"])

    tools = await client.get("/api/v1/review/language/tools", headers=auth_headers)
    assert tools.status_code == 200, tools.text
    catalog = tools.json()
    ids = {item["id"] for item in catalog["tools"]}
    assert "grammar" in ids and "abusive" in ids and "run_on" in ids
    assert "gpt" in catalog

    unauth_tools = await client.get("/api/v1/review/language/tools")
    assert unauth_tools.status_code == 401


@pytest.mark.asyncio
async def test_language_review_gpt_toggle(client: AsyncClient, auth_headers: dict[str, str], monkeypatch):
    async def _ok(key: str, base: str):
        return None

    monkeypatch.setattr("app.services.language_review.verify_openai_key", _ok)

    bad = await client.put(
        "/api/v1/review/language/gpt",
        headers=auth_headers,
        json={"enabled": True, "api_key": "short"},
    )
    assert bad.status_code == 400

    empty = await client.put(
        "/api/v1/review/language/gpt",
        headers=auth_headers,
        json={"enabled": True},
    )
    assert empty.status_code == 400

    on = await client.put(
        "/api/v1/review/language/gpt",
        headers=auth_headers,
        json={
            "enabled": True,
            "api_key": "sk-test-abcdefghijklmnopqrstuvwxyz012345",
            "model": "gpt-4o-mini",
        },
    )
    assert on.status_code == 200, on.text
    gpt = on.json()["gpt"]
    assert gpt["available"] is True
    assert gpt["model"] == "gpt-4o-mini"
    assert gpt["key_hint"]
    assert "sk-" not in (gpt["key_hint"] or "") or "…" in gpt["key_hint"]

    tools = await client.get("/api/v1/review/language/tools", headers=auth_headers)
    assert tools.json()["gpt"]["available"] is True

    off = await client.put(
        "/api/v1/review/language/gpt",
        headers=auth_headers,
        json={"enabled": False},
    )
    assert off.status_code == 200, off.text
    assert off.json()["gpt"]["available"] is False
    assert off.json()["gpt"]["configured"] is True

    resume = await client.put(
        "/api/v1/review/language/gpt",
        headers=auth_headers,
        json={"enabled": True},
    )
    assert resume.status_code == 200, resume.text
    assert resume.json()["gpt"]["available"] is True
