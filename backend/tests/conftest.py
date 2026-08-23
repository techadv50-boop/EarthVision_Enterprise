"""Pytest fixtures for EarthVision backend tests."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.database.session import AsyncSessionLocal, init_db
from app.services.auth_service import AuthService


@pytest.fixture
async def client():
    """ASGI client with database initialized (httpx 0.28 has no lifespan=)."""
    await init_db()
    async with AsyncSessionLocal() as session:
        await AuthService(session).seed_default_data()
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "demo", "password": "Demo@123456"},
    )
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
