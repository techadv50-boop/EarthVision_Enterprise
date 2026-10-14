"""Tool plugin catalog, privilege filtering, and admin zip install."""

from __future__ import annotations

import io
import json
import zipfile
import pytest
from httpx import AsyncClient

from app.plugins.service import plugin_dir


def _plugin_zip(
    plugin_id: str = "sample-tool",
    *,
    name: str = "Sample tool",
    service: str = "open",
    html: str = "<html><body>Sample tool</body></html>",
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "id": plugin_id,
                    "name": name,
                    "description": "Uploaded desk",
                    "version": "2.0.0",
                    "service": service,
                    "icon": "puzzle",
                    "entry": "index.html",
                }
            ),
        )
        archive.writestr("index.html", html)
    return buffer.getvalue()


async def _auth(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "citation@xdgen.com", "password": "pak123"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.asyncio
async def test_builtin_plugins_are_listed_for_operator(client: AsyncClient):
    headers = await _auth(client)
    listed = await client.get("/api/v1/plugins", headers=headers)
    assert listed.status_code == 200, listed.text
    ids = {row["id"] for row in listed.json()["plugins"]}
    assert ids >= {
        "citation-assistant",
        "article-review",
        "author-database",
        "galley-composition",
    }
    citation = next(row for row in listed.json()["plugins"] if row["id"] == "citation-assistant")
    assert citation["kind"] == "builtin"
    assert citation["route"] == "/journals"
    assert citation["enabled"] is True


@pytest.mark.asyncio
async def test_operator_uploads_and_opens_plugin_zip(client: AsyncClient):
    headers = await _auth(client)
    uploaded = await client.post(
        "/api/v1/plugins/upload",
        headers=headers,
        files=[("file", ("sample-tool.zip", _plugin_zip(), "application/zip"))],
    )
    assert uploaded.status_code == 200, uploaded.text
    body = uploaded.json()
    assert body["id"] == "sample-tool"
    assert body["kind"] == "uploaded"
    assert body["route"] == "/tools/sample-tool"
    listed = await client.get("/api/v1/plugins", headers=headers)
    ids = {row["id"] for row in listed.json()["plugins"]}
    assert "sample-tool" in ids
    html_path = plugin_dir("sample-tool") / "index.html"
    assert html_path.is_file()
    page = await client.get("/plugin-assets/sample-tool/index.html")
    assert page.status_code == 200
    assert b"Sample tool" in page.content
    disabled = await client.patch(
        "/api/v1/plugins/sample-tool",
        headers=headers,
        json={"enabled": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    removed = await client.delete("/api/v1/plugins/sample-tool", headers=headers)
    assert removed.status_code == 200
    assert not plugin_dir("sample-tool").exists()


@pytest.mark.asyncio
async def test_upload_with_builtin_id_overrides_only_that_tool(client: AsyncClient):
    headers = await _auth(client)
    uploaded = await client.post(
        "/api/v1/plugins/upload",
        headers=headers,
        files=[
            (
                "file",
                (
                    "galley.zip",
                    _plugin_zip("galley-composition", name="Galley overlay"),
                    "application/zip",
                ),
            )
        ],
    )
    assert uploaded.status_code == 200, uploaded.text
    body = uploaded.json()
    assert body["id"] == "galley-composition"
    assert body["kind"] == "uploaded"
    assert body["overridden"] is True
    assert body["route"] == "/tools/galley-composition"
    listed = await client.get("/api/v1/plugins", headers=headers)
    ids = [row["id"] for row in listed.json()["plugins"]]
    assert ids.count("galley-composition") == 1
    assert "citation-assistant" in ids
    restored = await client.delete("/api/v1/plugins/galley-composition", headers=headers)
    assert restored.status_code == 200
    assert restored.json()["kind"] == "builtin"
    assert restored.json()["route"] == "/galley"


@pytest.mark.asyncio
async def test_non_operator_cannot_upload_plugin(client: AsyncClient):
    headers = await _auth(client)
    created = await client.post(
        "/api/v1/admin/users",
        headers=headers,
        json={
            "email": "plugin-user@example.com",
            "username": "plugin-user",
            "password": "pluginpass1",
            "role": "user",
            "privileges": {
                "services": ["citation"],
                "review_branches": [],
                "author_wings": [],
                "all_journals": True,
            },
            "access_status": "approved",
        },
    )
    assert created.status_code in (200, 201), created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "plugin-user", "password": "pluginpass1"},
    )
    assert login.status_code == 200, login.text
    user_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    forbidden = await client.post(
        "/api/v1/plugins/upload",
        headers=user_headers,
        files=[("file", ("sample-tool.zip", _plugin_zip(), "application/zip"))],
    )
    assert forbidden.status_code == 403
    listed = await client.get("/api/v1/plugins", headers=user_headers)
    assert listed.status_code == 200
    ids = {row["id"] for row in listed.json()["plugins"]}
    assert "citation-assistant" in ids
    assert "galley-composition" not in ids


def test_plugin_zip_rejects_path_traversal():
    from app.plugins.service import _unzip_plugin

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps({"id": "evil", "name": "Evil", "entry": "index.html"}),
        )
        archive.writestr("../evil.html", "<html></html>")
        archive.writestr("index.html", "<html></html>")
    with pytest.raises(ValueError):
        _unzip_plugin(buffer.getvalue())
