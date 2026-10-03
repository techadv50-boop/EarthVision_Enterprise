"""Article store upload and admin-password download."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


def _bearer(login) -> dict[str, str]:
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_article_store_lists_six_journals_and_downloads_with_admin_password(client: AsyncClient):
    operator = await client.post(
        "/api/v1/auth/login",
        json={"username": "citation@xdgen.com", "password": "pak123"},
    )
    headers = _bearer(operator)
    journals = await client.get("/api/v1/author-articles/store/journals", headers=headers)
    assert journals.status_code == 200, journals.text
    names = {row["name"] for row in journals.json()}
    assert "International Journal of Innovations in Science & Technology" in names
    assert "Magna Carta: Contemporary Social Science" in names
    assert "International Journal of Agriculture and Sustainable Development" in names
    assert "Frontiers in Computational Spatial Intelligence" in names
    assert "Journal of International Relations and Social Dynamics" in names
    assert "International Journal of NT Diseases" in names
    assert len(journals.json()) >= 6

    uploaded = await client.post(
        "/api/v1/author-articles/store/IJIST/files",
        headers=headers,
        files={"file": ("next-issue.txt", b"Stored for later download.", "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text
    file_id = uploaded.json()["id"]
    assert uploaded.json()["original_name"] == "next-issue.txt"

    listing = await client.get("/api/v1/author-articles/store/IJIST/files", headers=headers)
    assert listing.status_code == 200
    assert any(row["id"] == file_id for row in listing.json())

    missing = await client.post(
        f"/api/v1/author-articles/store/files/{file_id}/download",
        headers=headers,
        json={"password": ""},
    )
    assert missing.status_code == 403
    wrong = await client.post(
        f"/api/v1/author-articles/store/files/{file_id}/download",
        headers=headers,
        json={"password": "not-the-admin-password"},
    )
    assert wrong.status_code == 403
    downloaded = await client.post(
        f"/api/v1/author-articles/store/files/{file_id}/download",
        headers=headers,
        json={"password": "pak123"},
    )
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.content == b"Stored for later download."

    other = await client.post(
        "/api/v1/author-articles/store/FCSI/files",
        headers=headers,
        files={"file": ("fcsi-paper.txt", b"FCSI file", "text/plain")},
    )
    assert other.status_code == 201, other.text
    ijist = await client.get("/api/v1/author-articles/store/IJIST/files", headers=headers)
    fcsi = await client.get("/api/v1/author-articles/store/FCSI/files", headers=headers)
    assert any(row["original_name"] == "next-issue.txt" for row in ijist.json())
    assert any(row["original_name"] == "fcsi-paper.txt" for row in fcsi.json())
    assert all(row["original_name"] != "fcsi-paper.txt" for row in ijist.json())
