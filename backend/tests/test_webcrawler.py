"""Web crawler tab: v1.4.2 engine available to admin and ordinary users."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


def _bearer(login) -> dict[str, str]:
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_admin_and_user_can_open_webcrawler(client: AsyncClient):
    operator = await client.post(
        "/api/v1/auth/login",
        json={"username": "citation@xdgen.com", "password": "pak123"},
    )
    admin = _bearer(operator)
    status = await client.get("/api/v1/webcrawler/status", headers=admin)
    assert status.status_code == 200, status.text
    body = status.json()
    assert body["version"] == "1.4.2"
    assert body["busy"] is False
    assert body["progress"]["status"]
    sites = await client.get("/api/v1/webcrawler/sites", headers=admin)
    assert sites.status_code == 200
    assert sites.json() == []

    empty = await client.post(
        "/api/v1/webcrawler/start",
        headers=admin,
        json={"urls": "", "light_mode": True},
    )
    assert empty.status_code == 400

    created = await client.post(
        "/api/v1/admin/users",
        headers=admin,
        json={
            "email": "crawler.user@example.com",
            "username": "crawleruser",
            "password": "CrawlerUser@123456",
            "role": "user",
            "privileges": {
                "services": ["authors"],
                "review_branches": [],
                "author_wings": ["in_process"],
                "all_journals": False,
            },
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "crawleruser", "password": "CrawlerUser@123456"},
    )
    user = _bearer(login)
    user_status = await client.get("/api/v1/webcrawler/status", headers=user)
    assert user_status.status_code == 200, user_status.text
    assert user_status.json()["version"] == "1.4.2"
    missing = await client.get("/api/v1/webcrawler/status")
    assert missing.status_code == 401
