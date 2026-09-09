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
    assert payload["status"] == "pass"
    assert payload["order_changed"] is True

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
