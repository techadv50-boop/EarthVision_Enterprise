"""Galley composition uses Citation Assistant accounts, not a second login."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


def _bearer(login) -> dict[str, str]:
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


JOURNAL = {
    "id": "ijist-test",
    "name": "International Journal of Innovations in Science & Technology",
    "abbreviation": "IJIST",
    "issnP": "2618-1630",
    "issnE": "2618-1630",
    "topIcons": [],
    "partnerIcons": [],
}

PROOF = {
    "id": "proof-one",
    "journalId": "ijist-test",
    "title": "Heart Disease Prediction",
    "authors": [],
    "volume": "7",
    "issue": "4",
    "startPage": "2705",
    "received": "",
    "revised": "",
    "accepted": "",
    "published": "",
    "doi": "",
    "abstract": "A short abstract.",
    "keywords": "heart",
    "topIcons": [],
    "partnerIcons": [],
    "blocks": [{"id": "s1", "type": "section", "heading": "Introduction:", "text": "See [1]."}],
    "references": [],
    "referenceSource": "",
    "referenceStyle": "ieee",
    "updatedAt": 1,
}


@pytest.mark.asyncio
async def test_galley_desk_shares_citation_login(client: AsyncClient):
    operator = await client.post(
        "/api/v1/auth/login",
        json={"username": "citation@xdgen.com", "password": "pak123"},
    )
    admin = _bearer(operator)
    denied = await client.get("/api/v1/galley/journals")
    assert denied.status_code == 401

    created = await client.post("/api/v1/galley/journals", headers=admin, json=JOURNAL)
    assert created.status_code == 200, created.text
    assert created.json()["abbreviation"] == "IJIST"

    listed = await client.get("/api/v1/galley/journals", headers=admin)
    assert listed.status_code == 200
    assert any(row["id"] == "ijist-test" for row in listed.json())

    proof = await client.post("/api/v1/galley/galleys", headers=admin, json=PROOF)
    assert proof.status_code == 200, proof.text
    assert proof.json()["title"] == "Heart Disease Prediction"
    galley_id = proof.json()["id"]

    updated = await client.put(
        f"/api/v1/galley/galleys/{galley_id}",
        headers=admin,
        json={**PROOF, "title": "Heart Disease Prediction revised"},
    )
    assert updated.status_code == 200
    assert updated.json()["title"].endswith("revised")

    archive = await client.get("/api/v1/galley/galleys", headers=admin)
    assert archive.status_code == 200
    assert archive.json()[0]["ownerEmail"]
    assert archive.json()[0]["galley"]["title"].endswith("revised")


@pytest.mark.asyncio
async def test_galley_user_owns_proofs_and_cannot_delete(client: AsyncClient):
    operator = await client.post(
        "/api/v1/auth/login",
        json={"username": "citation@xdgen.com", "password": "pak123"},
    )
    admin = _bearer(operator)
    journal = await client.post("/api/v1/galley/journals", headers=admin, json={**JOURNAL, "id": "ijasd-test"})
    assert journal.status_code == 200

    created_user = await client.post(
        "/api/v1/admin/users",
        headers=admin,
        json={
            "email": "galleyeditor@example.com",
            "username": "galleyeditor",
            "password": "EditorPass@123456",
            "role": "user",
            "privileges": {
                "services": ["galley"],
                "review_branches": [],
                "author_wings": [],
                "all_journals": False,
            },
        },
    )
    assert created_user.status_code == 201, created_user.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "galleyeditor", "password": "EditorPass@123456"},
    )
    user = _bearer(login)

    blocked_journal = await client.post(
        "/api/v1/galley/journals",
        headers=user,
        json={**JOURNAL, "id": "secret"},
    )
    assert blocked_journal.status_code == 403

    own = await client.post(
        "/api/v1/galley/galleys",
        headers=user,
        json={**PROOF, "id": "mine", "journalId": "ijasd-test", "title": "My galley"},
    )
    assert own.status_code == 200, own.text
    other = await client.post(
        "/api/v1/galley/galleys",
        headers=admin,
        json={**PROOF, "id": "admin-proof", "journalId": "ijasd-test", "title": "Admin galley"},
    )
    assert other.status_code == 200

    mine = await client.get("/api/v1/galley/galleys", headers=user)
    titles = {row["galley"]["title"] for row in mine.json()}
    assert "My galley" in titles
    assert "Admin galley" not in titles

    steal = await client.put(
        "/api/v1/galley/galleys/admin-proof",
        headers=user,
        json={**PROOF, "id": "admin-proof", "title": "Stolen"},
    )
    assert steal.status_code == 403

    deleted = await client.delete("/api/v1/galley/galleys/mine", headers=user)
    assert deleted.status_code == 403
    still = await client.get("/api/v1/galley/galleys", headers=user)
    assert any(row["galley"]["id"] == "mine" for row in still.json())

    admin_sees = await client.get("/api/v1/galley/galleys", headers=admin)
    admin_titles = {row["galley"]["title"] for row in admin_sees.json()}
    assert "My galley" in admin_titles
    assert "Admin galley" in admin_titles

    removed = await client.delete("/api/v1/galley/galleys/mine", headers=admin)
    assert removed.status_code == 200
    gone = await client.get("/api/v1/galley/galleys", headers=user)
    assert gone.json() == []
