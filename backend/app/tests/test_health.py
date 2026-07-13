import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_health():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_login_and_catalog():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Ensure DB init via lifespan
        async with app.router.lifespan_context(app):
            login = await client.post(
                "/api/v1/auth/login",
                json={
                    "email": "admin@earthvision.io",
                    "password": "EarthVision@Admin2024!",
                },
            )
            assert login.status_code == 200, login.text
            token = login.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            search = await client.post(
                "/api/v1/catalog/search",
                headers=headers,
                json={
                    "collections": ["SENTINEL-2"],
                    "cloud_cover_max": 40,
                    "bbox": [2.0, 48.5, 2.8, 49.1],
                    "max_results": 5,
                },
            )
            assert search.status_code == 200, search.text
            assert search.json()["total"] >= 1

            index = await client.post(
                "/api/v1/analytics/index",
                headers=headers,
                json={"index": "NDVI"},
            )
            assert index.status_code == 200
            assert "mean" in index.json()
