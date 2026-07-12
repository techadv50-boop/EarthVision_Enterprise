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
