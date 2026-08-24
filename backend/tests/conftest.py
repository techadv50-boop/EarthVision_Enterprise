"""Pytest fixtures for EarthVision backend tests.

Tests use an isolated SQLite file so they never write fake journals
into the live operator archive (earthvision.db).
"""

from __future__ import annotations

import os
from pathlib import Path

_TEST_DB = Path("/tmp/citation-pytest.db")
if _TEST_DB.exists():
    _TEST_DB.unlink()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TEST_DB}"

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings

get_settings.cache_clear()

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
