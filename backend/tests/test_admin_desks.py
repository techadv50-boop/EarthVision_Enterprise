"""Each workspace desk can have its own admin account."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


def _bearer(login) -> dict[str, str]:
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_operator_me_lists_every_desk(client: AsyncClient):
    operator = await client.post(
        "/api/v1/auth/login",
        json={"username": "citation@xdgen.com", "password": "pak123"},
    )
    me = await client.get("/api/v1/auth/me", headers=_bearer(operator))
    assert me.status_code == 200
    desks = me.json()["desks"]
    assert set(desks) == {"citation", "authors", "review", "users", "galley"}


@pytest.mark.asyncio
async def test_separate_desk_admins_cannot_run_other_desks(client: AsyncClient):
    operator = await client.post(
        "/api/v1/auth/login",
        json={"username": "citation@xdgen.com", "password": "pak123"},
    )
    admin = _bearer(operator)

    galley = await client.post(
        "/api/v1/admin/users",
        headers=admin,
        json={
            "email": "galley.admin@example.com",
            "username": "galleyadmin",
            "password": "GalleyAdmin@123456",
            "full_name": "Galley Admin",
            "role": "user",
            "desks": ["galley"],
        },
    )
    assert galley.status_code == 201, galley.text
    assert "admin_galley" in galley.json()["roles"]
    assert galley.json()["desks"] == ["galley"]
    assert galley.json()["is_superuser"] is False

    authors = await client.post(
        "/api/v1/admin/users",
        headers=admin,
        json={
            "email": "authors.admin@example.com",
            "username": "authorsadmin",
            "password": "AuthorsAdmin@123456",
            "role": "user",
            "desks": ["authors"],
        },
    )
    assert authors.status_code == 201, authors.text
    users_admin = await client.post(
        "/api/v1/admin/users",
        headers=admin,
        json={
            "email": "users.admin@example.com",
            "username": "usersadmin",
            "password": "UsersAdmin@123456",
            "role": "user",
            "desks": ["users"],
        },
    )
    assert users_admin.status_code == 201, users_admin.text
    citation = await client.post(
        "/api/v1/admin/users",
        headers=admin,
        json={
            "email": "cite.admin@example.com",
            "username": "citeadmin",
            "password": "CiteAdmin@123456",
            "role": "user",
            "desks": ["citation"],
        },
    )
    assert citation.status_code == 201, citation.text

    galley_login = await client.post(
        "/api/v1/auth/login",
        json={"username": "galleyadmin", "password": "GalleyAdmin@123456"},
    )
    gheaders = _bearer(galley_login)
    saved = await client.post(
        "/api/v1/galley/journals",
        headers=gheaders,
        json={
            "id": "desk-ijist",
            "name": "IJIST",
            "abbreviation": "IJIST",
            "issnP": "",
            "issnE": "",
            "topIcons": [],
            "partnerIcons": [],
        },
    )
    assert saved.status_code == 200, saved.text
    assert (await client.get("/api/v1/admin/users", headers=gheaders)).status_code == 403
    assert (
        await client.post("/api/v1/journals", headers=gheaders, json={"name": "Nope"})
    ).status_code == 403

    cite_login = await client.post(
        "/api/v1/auth/login",
        json={"username": "citeadmin", "password": "CiteAdmin@123456"},
    )
    cheaders = _bearer(cite_login)
    created_journal = await client.post(
        "/api/v1/journals",
        headers=cheaders,
        json={"name": "Desk Journal", "abbreviation": "DJ"},
    )
    assert created_journal.status_code in (200, 201), created_journal.text
    assert (await client.get("/api/v1/admin/users", headers=cheaders)).status_code == 403
    assert (
        await client.post(
            "/api/v1/galley/journals",
            headers=cheaders,
            json={"id": "blocked", "name": "No", "abbreviation": "NO", "issnP": "", "issnE": "", "topIcons": [], "partnerIcons": []},
        )
    ).status_code == 403

    author_login = await client.post(
        "/api/v1/auth/login",
        json={"username": "authorsadmin", "password": "AuthorsAdmin@123456"},
    )
    aheaders = _bearer(author_login)
    article = await client.post(
        "/api/v1/author-articles",
        headers=aheaders,
        json={"ojs_number": "DESK-1", "title": "Author admin paper"},
    )
    assert article.status_code == 201, article.text
    blocked_delete = await client.delete(
        f"/api/v1/author-articles/{article.json()['id']}",
        headers=gheaders,
    )
    assert blocked_delete.status_code == 403
    deleted = await client.delete(
        f"/api/v1/author-articles/{article.json()['id']}",
        headers=aheaders,
    )
    assert deleted.status_code == 204

    users_login = await client.post(
        "/api/v1/auth/login",
        json={"username": "usersadmin", "password": "UsersAdmin@123456"},
    )
    uheaders = _bearer(users_login)
    listed = await client.get("/api/v1/admin/users", headers=uheaders)
    assert listed.status_code == 200
    blocked_full = await client.post(
        "/api/v1/admin/users",
        headers=uheaders,
        json={
            "email": "clone@example.com",
            "username": "cloneop",
            "password": "CloneOp@123456",
            "role": "admin",
        },
    )
    assert blocked_full.status_code == 403
    review_only = await client.post(
        "/api/v1/admin/users",
        headers=uheaders,
        json={
            "email": "review.admin@example.com",
            "username": "reviewadmin",
            "password": "ReviewAdmin@123456",
            "role": "user",
            "desks": ["review"],
        },
    )
    assert review_only.status_code == 201, review_only.text
    assert review_only.json()["desks"] == ["review"]
