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
