"""Author database: under-process records scoped to assigned journals."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


def _bearer(login) -> dict[str, str]:
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_admin_adds_under_process_article(client: AsyncClient):
    operator = await client.post(
        "/api/v1/auth/login",
        json={"username": "citation@xdgen.com", "password": "pak123"},
    )
    headers = _bearer(operator)
    created = await client.post(
        "/api/v1/author-articles",
        headers=headers,
        json={
            "ojs_number": "IJIST-2024-118",
            "title": "EdDSA watermarking for documents",
            "author_names": "Ali Khan; Sara Ahmed",
            "author_emails": "ali@example.com; sara@example.com",
            "email_sent_date": "2024-01-05",
            "plagiarism": "9%",
            "orcid_id": "0000-0002-1825-0097",
            "received_date": "2024-01-12",
            "review_rounds": [
                {"round": 1, "sent_date": "2024-01-20", "received_date": "2024-02-01"},
            ],
            "accepted_date": "2024-03-10",
            "galley_sent_date": "2024-03-12",
            "galley_received_date": "2024-03-18",
            "publish_date": "",
            "editorial_status": "Waiting for reviewer to be assigned",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["wing"] == "in_process"
    assert body["ojs_number"] == "IJIST-2024-118"
    assert body["email_sent_date"] == "2024-01-05"
    assert body["plagiarism"] == "9%"
    assert body["review_rounds"][0]["sent_date"] == "2024-01-20"
    assert body["galley_sent_date"] == "2024-03-12"
    assert body["editorial_status"] == "Waiting for reviewer to be assigned"

    listed = await client.get("/api/v1/author-articles", headers=headers, params={"wing": "in_process"})
    assert listed.status_code == 200
    assert any(row["id"] == body["id"] for row in listed.json())

    published = await client.get("/api/v1/author-articles", headers=headers, params={"wing": "published"})
    assert published.status_code == 200
    assert published.json() == []

    moved = await client.patch(
        f"/api/v1/author-articles/{body['id']}",
        headers=headers,
        json={"wing": "published"},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["wing"] == "published"

    still_open = await client.get("/api/v1/author-articles", headers=headers, params={"wing": "in_process"})
    assert all(row["id"] != body["id"] for row in still_open.json())
    now_pub = await client.get("/api/v1/author-articles", headers=headers, params={"wing": "published"})
    assert any(row["id"] == body["id"] for row in now_pub.json())


@pytest.mark.asyncio
async def test_assigned_user_only_sees_own_journal_author_records(client: AsyncClient):
    operator = await client.post(
        "/api/v1/auth/login",
        json={"username": "citation@xdgen.com", "password": "pak123"},
    )
    admin = _bearer(operator)
    journal_a = await client.post(
        "/api/v1/journals",
        headers=admin,
        json={"name": "Author DB Alpha", "abbreviation": "ADA"},
    )
    journal_b = await client.post(
        "/api/v1/journals",
        headers=admin,
        json={"name": "Author DB Beta", "abbreviation": "ADB"},
    )
    id_a = journal_a.json()["id"]
    id_b = journal_b.json()["id"]
    created_user = await client.post(
        "/api/v1/admin/users",
        headers=admin,
        json={
            "email": "adbeditor@example.com",
            "username": "adbeditor",
            "password": "EditorPass@123456",
            "role": "user",
            "privileges": {
                "services": ["authors"],
                "review_branches": [],
                "author_wings": ["in_process", "published"],
                "all_journals": False,
            },
            "assigned_journal_ids": [id_a],
        },
    )
    assert created_user.status_code == 201, created_user.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "adbeditor", "password": "EditorPass@123456"},
    )
    user = _bearer(login)

    own = await client.post(
        "/api/v1/author-articles",
        headers=user,
        json={"journal_id": id_a, "ojs_number": "ADA-1", "title": "Alpha paper"},
    )
    assert own.status_code == 201, own.text
    blocked = await client.post(
        "/api/v1/author-articles",
        headers=user,
        json={"journal_id": id_b, "ojs_number": "ADB-1", "title": "Beta paper"},
    )
    assert blocked.status_code == 404

    other = await client.post(
        "/api/v1/author-articles",
        headers=admin,
        json={"journal_id": id_b, "ojs_number": "ADB-9", "title": "Hidden beta"},
    )
    assert other.status_code == 201
    listed = await client.get("/api/v1/author-articles", headers=user, params={"wing": "in_process"})
    ids = {row["id"] for row in listed.json()}
    assert own.json()["id"] in ids
    assert other.json()["id"] not in ids

    deleted = await client.delete(f"/api/v1/author-articles/{own.json()['id']}", headers=user)
    assert deleted.status_code == 403
    still = await client.get("/api/v1/author-articles", headers=user, params={"wing": "in_process"})
    assert any(row["id"] == own.json()["id"] for row in still.json())


@pytest.mark.asyncio
async def test_user_modifications_record_previous_and_new_values(client: AsyncClient):
    operator = await client.post(
        "/api/v1/auth/login",
        json={"username": "citation@xdgen.com", "password": "pak123"},
    )
    headers = _bearer(operator)
    created = await client.post(
        "/api/v1/author-articles",
        headers=headers,
        json={"ojs_number": "MOD-1", "title": "History paper", "received_date": "2024-01-01"},
    )
    assert created.status_code == 201, created.text
    article_id = created.json()["id"]
    first = await client.patch(
        f"/api/v1/author-articles/{article_id}",
        headers=headers,
        json={"received_date": "2024-02-15", "plagiarism": "12%"},
    )
    assert first.status_code == 200, first.text
    mods = first.json()["modifications"]
    assert len(mods) == 1
    assert mods[0]["mod_number"] == 1
    assert mods[0]["account"]
    labels = {item["label"]: item for item in mods[0]["changes"]}
    assert labels["Receive date"]["previous"] == "2024-01-01"
    assert labels["Receive date"]["new"] == "2024-02-15"
    assert labels["Plagiarism"]["previous"] == "(empty)"
    assert labels["Plagiarism"]["new"] == "12%"
    assert first.json()["original_snapshot"]["received_date"] == "2024-01-01"
    assert first.json()["modifications"][0]["snapshot"]["received_date"] == "2024-02-15"
    assert first.json()["modifications"][0]["snapshot"]["plagiarism"] == "12%"

    second = await client.patch(
        f"/api/v1/author-articles/{article_id}",
        headers=headers,
        json={"received_date": "2024-03-20"},
    )
    assert second.status_code == 200
    assert [item["mod_number"] for item in second.json()["modifications"]] == [1, 2]
    latest = second.json()["modifications"][1]
    assert latest["changes"][0]["previous"] == "2024-02-15"
    assert latest["changes"][0]["new"] == "2024-03-20"


@pytest.mark.asyncio
async def test_under_process_review_rounds_and_journal_catalog(client: AsyncClient):
    operator = await client.post(
        "/api/v1/auth/login",
        json={"username": "citation@xdgen.com", "password": "pak123"},
    )
    headers = _bearer(operator)
    journals = await client.get("/api/v1/author-articles/journals", headers=headers)
    assert journals.status_code == 200, journals.text
    names = {row["name"] for row in journals.json()}
    assert "International Journal of Innovations in Science & Technology" in names
    assert "Magna Carta: Contemporary Social Science" in names
    assert "International Journal of Agriculture and Sustainable Development" in names
    assert "Frontiers in Computational Spatial Intelligence" in names
    assert "Journal of International Relations and Social Dynamics" in names
    assert "International Journal of NT Diseases" in names
    assert "Demo Extra Journal" not in names
    cite_journals = await client.get("/api/v1/journals", headers=headers)
    assert cite_journals.status_code == 200
    assert "FCSI" not in {row.get("abbreviation") for row in cite_journals.json()}
    created = await client.post(
        "/api/v1/author-articles",
        headers=headers,
        json={
            "journal_title": "IJIST",
            "ojs_number": "RND-1",
            "title": "Round paper",
            "email_sent_date": "2024-06-01",
            "review_rounds": [
                {"sent_date": "2024-06-02", "received_date": "2024-06-10"},
                {"sent_date": "2024-06-12", "received_date": "2024-06-20"},
            ],
            "accepted_date": "2024-07-01",
            "galley_sent_date": "2024-07-02",
            "galley_received_date": "2024-07-08",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["journal_id"] is None
    assert created.json()["journal_name"] == "International Journal of Innovations in Science & Technology"
    rounds = created.json()["review_rounds"]
    assert len(rounds) == 2
    assert rounds[1]["round"] == 2
    assert rounds[1]["sent_date"] == "2024-06-12"
    third = await client.patch(
        f"/api/v1/author-articles/{created.json()['id']}",
        headers=headers,
        json={
            "review_rounds": [
                *rounds,
                {"sent_date": "2024-06-22", "received_date": "2024-06-30"},
            ]
        },
    )
    assert third.status_code == 200, third.text
    assert len(third.json()["review_rounds"]) == 3
    assert "Round 3" in third.json()["modifications"][-1]["changes"][0]["new"]


@pytest.mark.asyncio
async def test_excel_import_creates_and_updates_author_articles(client: AsyncClient):
    from io import BytesIO

    from openpyxl import Workbook

    operator = await client.post(
        "/api/v1/auth/login",
        json={"username": "citation@xdgen.com", "password": "pak123"},
    )
    headers = _bearer(operator)
    template = await client.get("/api/v1/author-articles/template", headers=headers)
    assert template.status_code == 200
    assert "spreadsheet" in template.headers.get("content-type", "")

    book = Workbook()
    sheet = book.active
    sheet.append(
        [
            "OJS number",
            "Title",
            "Author names",
            "Email addresses of authors",
            "Email sent",
            "Plagiarism",
            "ORCID ID",
            "Receive date",
            "Review date",
            "Accepted date",
            "Publish date",
            "Repeat done",
            "DOI in PDF",
        ]
    )
    sheet.append(
        [
            "XL-100",
            "Imported paper",
            "Noor Ali",
            "noor@example.com",
            "Yes",
            "8%",
            "0000-0001-2345-6789",
            "2024-04-01",
            "",
            "",
            "",
            "No",
            "10.1/xl-100",
        ]
    )
    buf = BytesIO()
    book.save(buf)
    imported = await client.post(
        "/api/v1/author-articles/import",
        headers=headers,
        params={"wing": "in_process"},
        files={
            "file": (
                "authors.xlsx",
                buf.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["created"] == 1
    article_id = imported.json()["articles"][0]["id"]

    book2 = Workbook()
    sheet2 = book2.active
    sheet2.append(["OJS number", "Title", "Receive date", "Plagiarism"])
    sheet2.append(["XL-100", "Imported paper revised", "2024-05-09", "10%"])
    buf2 = BytesIO()
    book2.save(buf2)
    updated = await client.post(
        "/api/v1/author-articles/import",
        headers=headers,
        params={"wing": "in_process"},
        files={
            "file": (
                "authors2.xlsx",
                buf2.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["updated"] == 1
    detail = (await client.get("/api/v1/author-articles", headers=headers, params={"wing": "in_process"})).json()
    row = next(item for item in detail if item["id"] == article_id)
    assert row["received_date"] == "2024-05-09"
    assert row["plagiarism"] == "10%"
    assert row["modifications"]
    assert row["modifications"][-1]["account"]
    assert row["original_snapshot"]["received_date"] == "2024-04-01"
    assert row["modifications"][-1]["snapshot"]["received_date"] == "2024-05-09"


@pytest.mark.asyncio
async def test_admin_adds_author_journal_name_users_cannot(client: AsyncClient):
    operator = await client.post(
        "/api/v1/auth/login",
        json={"username": "citation@xdgen.com", "password": "pak123"},
    )
    admin = _bearer(operator)
    added = await client.post(
        "/api/v1/author-articles/journals",
        headers=admin,
        json={"name": "New Author Journal of Testing"},
    )
    assert added.status_code == 201, added.text
    listed = await client.get("/api/v1/author-articles/journals", headers=admin)
    names = {row["name"] for row in listed.json()}
    assert "New Author Journal of Testing" in names
    created_user = await client.post(
        "/api/v1/admin/users",
        headers=admin,
        json={
            "email": "adbplus@example.com",
            "username": "adbplus",
            "password": "EditorPass@123456",
            "role": "user",
            "privileges": {
                "services": ["authors"],
                "review_branches": [],
                "author_wings": ["in_process"],
                "all_journals": True,
            },
        },
    )
    assert created_user.status_code == 201, created_user.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "adbplus", "password": "EditorPass@123456"},
    )
    user = _bearer(login)
    blocked = await client.post(
        "/api/v1/author-articles/journals",
        headers=user,
        json={"name": "Secret Journal"},
    )
    assert blocked.status_code == 403
