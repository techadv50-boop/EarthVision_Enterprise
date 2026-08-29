"""Backend test suite."""

import pytest


@pytest.mark.asyncio
async def test_health_check(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "EarthVision" in data["app"]


@pytest.mark.asyncio
async def test_login(client):
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "demo", "password": "Demo@123456"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data


@pytest.mark.asyncio
async def test_operator_login_and_master_reset(client):
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "citation@xdgen.com", "password": "pak123"},
    )
    assert login.status_code == 200, login.text
    assert "access_token" in login.json()

    bad = await client.post(
        "/api/v1/auth/reset-password",
        json={
            "email": "citation@xdgen.com",
            "master_password": "wrong",
            "new_password": "newpass1",
        },
    )
    assert bad.status_code == 401

    reset = await client.post(
        "/api/v1/auth/reset-password",
        json={
            "email": "citation@xdgen.com",
            "master_password": "NTZHSS",
            "new_password": "newpass1",
        },
    )
    assert reset.status_code == 200, reset.text

    old = await client.post(
        "/api/v1/auth/login",
        json={"username": "citation@xdgen.com", "password": "pak123"},
    )
    assert old.status_code == 401

    fresh = await client.post(
        "/api/v1/auth/login",
        json={"username": "citation@xdgen.com", "password": "newpass1"},
    )
    assert fresh.status_code == 200

    restore = await client.post(
        "/api/v1/auth/reset-password",
        json={
            "email": "citation@xdgen.com",
            "master_password": "NTZHSS",
            "new_password": "pak123",
        },
    )
    assert restore.status_code == 200


def _bearer(response) -> dict[str, str]:
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.asyncio
async def test_user_role_cannot_list_journals_but_can_open_manuscripts(client):
    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "writer@example.com",
            "username": "writer",
            "password": "Writer@123456",
            "full_name": "Manuscript Writer",
        },
    )
    assert registered.status_code == 201, registered.text
    assert registered.json()["roles"] == ["user"]
    assert registered.json()["is_superuser"] is False

    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "writer", "password": "Writer@123456"},
    )
    headers = _bearer(login)
    journals = await client.get("/api/v1/journals", headers=headers)
    assert journals.status_code == 403
    search = await client.get("/api/v1/archive/search", headers=headers)
    assert search.status_code == 403
    manuscripts = await client.get("/api/v1/manuscripts", headers=headers)
    assert manuscripts.status_code == 200
    users = await client.get("/api/v1/admin/users", headers=headers)
    assert users.status_code == 403


@pytest.mark.asyncio
async def test_admin_assigns_user_and_admin_roles(client):
    operator = await client.post(
        "/api/v1/auth/login",
        json={"username": "citation@xdgen.com", "password": "pak123"},
    )
    admin_headers = _bearer(operator)
    journals = await client.get("/api/v1/journals", headers=admin_headers)
    assert journals.status_code == 200, journals.text

    created = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "promote@example.com",
            "username": "promote",
            "password": "Promote@123456",
        },
    )
    uid = created.json()["id"]
    listing = await client.get("/api/v1/admin/users", headers=admin_headers)
    assert listing.status_code == 200
    assert any(row["username"] == "promote" for row in listing.json())

    promoted = await client.patch(
        f"/api/v1/admin/users/{uid}",
        headers=admin_headers,
        json={"role": "admin"},
    )
    assert promoted.status_code == 200, promoted.text
    assert "admin" in promoted.json()["roles"]

    as_admin = await client.post(
        "/api/v1/auth/login",
        json={"username": "promote", "password": "Promote@123456"},
    )
    assert (await client.get("/api/v1/journals", headers=_bearer(as_admin))).status_code == 200

    demoted = await client.patch(
        f"/api/v1/admin/users/{uid}",
        headers=admin_headers,
        json={"role": "user"},
    )
    assert demoted.status_code == 200
    assert demoted.json()["roles"] == ["user"]

    as_user = await client.post(
        "/api/v1/auth/login",
        json={"username": "promote", "password": "Promote@123456"},
    )
    assert (await client.get("/api/v1/journals", headers=_bearer(as_user))).status_code == 403

    me = await client.get("/api/v1/auth/me", headers=admin_headers)
    self_id = me.json()["id"]
    blocked = await client.patch(
        f"/api/v1/admin/users/{self_id}",
        headers=admin_headers,
        json={"role": "user"},
    )
    assert blocked.status_code == 400

