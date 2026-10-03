"""Author database: under-process records scoped to assigned journals."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


def _bearer(login) -> dict[str, str]:
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_admin_adds_under_process_article(client: AsyncClient):
    operator = await client.post(
        "/api/v1/auth/login",
        json={"username": "citation@xdgen.com", "password": "pak123"},
    )
    headers = _bearer(operator)
    created = await client.post(
        "/api/v1/author-articles",
        headers=headers,
        json={
            "ojs_number": "IJIST-2024-118",
            "title": "EdDSA watermarking for documents",
            "author_names": "Ali Khan; Sara Ahmed",
            "author_emails": "ali@example.com; sara@example.com",
            "email_sent": True,
            "plagiarism": "9%",
            "orcid_id": "0000-0002-1825-0097",
            "received_date": "2024-01-12",
            "review_date": "2024-02-01",
            "accepted_date": "2024-03-10",
            "publish_date": "",
            "repeat_done": False,
            "doi_in_pdf": "10.33411/IJIST/20240101118",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["wing"] == "in_process"
    assert body["ojs_number"] == "IJIST-2024-118"
    assert body["email_sent"] is True
    assert body["plagiarism"] == "9%"
    assert body["repeat_done"] is False
    assert body["doi_in_pdf"].startswith("10.33411")

    listed = await client.get("/api/v1/author-articles", headers=headers, params={"wing": "in_process"})
    assert listed.status_code == 200
    assert any(row["id"] == body["id"] for row in listed.json())

    published = await client.get("/api/v1/author-articles", headers=headers, params={"wing": "published"})
    assert published.status_code == 200
    assert published.json() == []

    moved = await client.patch(
        f"/api/v1/author-articles/{body['id']}",
        headers=headers,
        json={"wing": "published", "repeat_done": True},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["wing"] == "published"
    assert moved.json()["repeat_done"] is True

    still_open = await client.get("/api/v1/author-articles", headers=headers, params={"wing": "in_process"})
    assert all(row["id"] != body["id"] for row in still_open.json())
    now_pub = await client.get("/api/v1/author-articles", headers=headers, params={"wing": "published"})
    assert any(row["id"] == body["id"] for row in now_pub.json())


@pytest.mark.asyncio
async def test_assigned_user_only_sees_own_journal_author_records(client: AsyncClient):
    operator = await client.post(
        "/api/v1/auth/login",
        json={"username": "citation@xdgen.com", "password": "pak123"},
    )
    admin = _bearer(operator)
    journal_a = await client.post(
        "/api/v1/journals",
        headers=admin,
        json={"name": "Author DB Alpha", "abbreviation": "ADA"},
    )
    journal_b = await client.post(
        "/api/v1/journals",
        headers=admin,
        json={"name": "Author DB Beta", "abbreviation": "ADB"},
    )
    id_a = journal_a.json()["id"]
    id_b = journal_b.json()["id"]
    created_user = await client.post(
        "/api/v1/admin/users",
        headers=admin,
        json={
            "email": "adbeditor@example.com",
            "username": "adbeditor",
            "password": "EditorPass@123456",
            "role": "user",
            "assigned_journal_ids": [id_a],
        },
    )
    assert created_user.status_code == 201, created_user.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "adbeditor", "password": "EditorPass@123456"},
    )
    user = _bearer(login)

    own = await client.post(
        "/api/v1/author-articles",
        headers=user,
        json={"journal_id": id_a, "ojs_number": "ADA-1", "title": "Alpha paper"},
    )
    assert own.status_code == 201, own.text
    blocked = await client.post(
        "/api/v1/author-articles",
        headers=user,
        json={"journal_id": id_b, "ojs_number": "ADB-1", "title": "Beta paper"},
    )
    assert blocked.status_code == 404

    other = await client.post(
        "/api/v1/author-articles",
        headers=admin,
        json={"journal_id": id_b, "ojs_number": "ADB-9", "title": "Hidden beta"},
    )
    assert other.status_code == 201
    listed = await client.get("/api/v1/author-articles", headers=user, params={"wing": "in_process"})
    ids = {row["id"] for row in listed.json()}
    assert own.json()["id"] in ids
    assert other.json()["id"] not in ids
