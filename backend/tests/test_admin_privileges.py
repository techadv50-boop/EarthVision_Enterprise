"""Admin grants service privileges instead of five admin-desk cards."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


def _bearer(login) -> dict[str, str]:
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_operator_me_lists_every_service(client: AsyncClient):
    operator = await client.post(
        "/api/v1/auth/login",
        json={"username": "citation@xdgen.com", "password": "pak123"},
    )
    me = await client.get("/api/v1/auth/me", headers=_bearer(operator))
    assert me.status_code == 200
    body = me.json()
    assert body["can_manage_users"] is True
    assert set(body["privileges"]["services"]) == {"citation", "authors", "review", "galley"}
    assert set(body["privileges"]["review_branches"]) == {"references", "language"}
    assert set(body["privileges"]["author_wings"]) == {"in_process", "published"}
    assert body["privileges"]["all_journals"] is True


@pytest.mark.asyncio
async def test_admin_grants_nested_service_privileges(client: AsyncClient):
    operator = await client.post(
        "/api/v1/auth/login",
        json={"username": "citation@xdgen.com", "password": "pak123"},
    )
    admin = _bearer(operator)
    journal = await client.post(
        "/api/v1/journals",
        headers=admin,
        json={"name": "Privilege Journal", "abbreviation": "PJ"},
    )
    assert journal.status_code in (200, 201), journal.text
    journal_id = journal.json()["id"]

    created = await client.post(
        "/api/v1/admin/users",
        headers=admin,
        json={
            "email": "partial@example.com",
            "username": "partialuser",
            "password": "PartialUser@123456",
            "role": "user",
            "privileges": {
                "services": ["citation", "review"],
                "review_branches": ["language"],
                "author_wings": [],
                "all_journals": False,
            },
            "assigned_journal_ids": [journal_id],
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["is_superuser"] is False
    assert set(body["privileges"]["services"]) == {"citation", "review"}
    assert body["privileges"]["review_branches"] == ["language"]
    assert body["privileges"]["all_journals"] is False
    assert body["assigned_journal_ids"] == [journal_id]
    assert body["can_manage_users"] is False

    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "partialuser", "password": "PartialUser@123456"},
    )
    headers = _bearer(login)
    listed = await client.get("/api/v1/journals", headers=headers)
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [journal_id]
    assert (await client.post("/api/v1/journals", headers=headers, json={"name": "Nope"})).status_code == 403
    assert (await client.get("/api/v1/admin/users", headers=headers)).status_code == 403
    assert (await client.get("/api/v1/galley/journals", headers=headers)).status_code == 403
    assert (await client.get("/api/v1/author-articles", headers=headers)).status_code == 403
    tools = await client.get("/api/v1/review/language/tools", headers=headers)
    assert tools.status_code == 200, tools.text
    refs = await client.post(
        "/api/v1/review/reference-integrity",
        headers=headers,
        files={
            "original": ("a.docx", b"not-docx", "application/octet-stream"),
            "returned": ("b.docx", b"not-docx", "application/octet-stream"),
        },
    )
    assert refs.status_code == 403

    galley_only = await client.post(
        "/api/v1/admin/users",
        headers=admin,
        json={
            "email": "galley.only@example.com",
            "username": "galleyonly",
            "password": "GalleyOnly@123456",
            "role": "user",
            "privileges": {"services": ["galley"], "review_branches": [], "author_wings": [], "all_journals": False},
        },
    )
    assert galley_only.status_code == 201, galley_only.text
    galley_login = await client.post(
        "/api/v1/auth/login",
        json={"username": "galleyonly", "password": "GalleyOnly@123456"},
    )
    gheaders = _bearer(galley_login)
    listed_g = await client.get("/api/v1/galley/journals", headers=gheaders)
    assert listed_g.status_code == 200
    blocked_shelf = await client.post(
        "/api/v1/galley/journals",
        headers=gheaders,
        json={"id": "blocked", "name": "No", "abbreviation": "NO", "issnP": "", "issnE": "", "topIcons": [], "partnerIcons": []},
    )
    assert blocked_shelf.status_code == 403

    authors_only = await client.post(
        "/api/v1/admin/users",
        headers=admin,
        json={
            "email": "authors.only@example.com",
            "username": "authorsonly",
            "password": "AuthorsOnly@123456",
            "role": "user",
            "privileges": {
                "services": ["authors"],
                "review_branches": [],
                "author_wings": ["in_process"],
                "all_journals": False,
            },
        },
    )
    assert authors_only.status_code == 201, authors_only.text
    author_login = await client.post(
        "/api/v1/auth/login",
        json={"username": "authorsonly", "password": "AuthorsOnly@123456"},
    )
    aheaders = _bearer(author_login)
    article = await client.post(
        "/api/v1/author-articles",
        headers=aheaders,
        json={"ojs_number": "PRIV-1", "title": "Under process only"},
    )
    assert article.status_code == 201, article.text
    published = await client.patch(
        f"/api/v1/author-articles/{article.json()['id']}",
        headers=aheaders,
        json={"wing": "published"},
    )
    assert published.status_code == 403
    listed_pub = await client.get("/api/v1/author-articles", headers=aheaders, params={"wing": "published"})
    assert listed_pub.status_code == 403

    uid = created.json()["id"]
    full = await client.patch(
        f"/api/v1/admin/users/{uid}",
        headers=admin,
        json={"approval": "full"},
    )
    assert full.status_code == 200, full.text
    assert set(full.json()["privileges"]["services"]) == {"citation", "review", "authors", "galley"}
    assert full.json()["privileges"]["all_journals"] is True
    assert full.json()["access_status"] == "approved"

    restricted = await client.patch(
        f"/api/v1/admin/users/{uid}",
        headers=admin,
        json={"approval": "restrict"},
    )
    assert restricted.status_code == 200
    assert restricted.json()["access_status"] == "restricted"
    blocked_login = await client.post(
        "/api/v1/auth/login",
        json={"username": "partialuser", "password": "PartialUser@123456"},
    )
    assert blocked_login.status_code == 403
