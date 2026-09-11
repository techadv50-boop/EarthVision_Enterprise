"""SatPass satellite / TLE lookup tests."""

from unittest.mock import AsyncMock, patch

import pytest

from app.routers.satellites import _is_placeholder_name, _norad_from_line1, _parse_tle_text

CARTOSAT_2A_L1 = "1 32783U 08021A   26253.95111561  .00000270  00000+0  42947-4 0  9999"
CARTOSAT_2A_L2 = "2 32783  97.7565 299.7008 0011387 185.6591 174.4494 14.79323197991484"


def test_norad_from_line1():
    assert _norad_from_line1(CARTOSAT_2A_L1) == 32783


def test_placeholder_names():
    assert _is_placeholder_name("Custom satellite")
    assert _is_placeholder_name("custom sat")
    assert _is_placeholder_name("NORAD 32783")
    assert not _is_placeholder_name("CARTOSAT-2A")


def test_parse_tle_text_uses_name_line():
    text = f"CARTOSAT-2A\n{CARTOSAT_2A_L1}\n{CARTOSAT_2A_L2}\n"
    results = _parse_tle_text(text)
    assert len(results) == 1
    assert results[0].name == "CARTOSAT-2A"
    assert results[0].norad_id == 32783


@pytest.mark.asyncio
async def test_add_placeholder_name_resolves_from_celestrak(client, auth_headers):
    with patch(
        "app.routers.satellites._celestrak_name_for_norad",
        new_callable=AsyncMock,
        return_value="CARTOSAT-2A",
    ) as lookup:
        resp = await client.post(
            "/api/v1/satellites",
            headers=auth_headers,
            json={
                "name": "Custom satellite",
                "line1": CARTOSAT_2A_L1,
                "line2": CARTOSAT_2A_L2,
            },
        )
    assert resp.status_code == 201, resp.text
    assert resp.json()["name"] == "CARTOSAT-2A"
    assert resp.json()["norad_id"] == 32783
    lookup.assert_awaited_once_with(32783)


@pytest.mark.asyncio
async def test_add_keeps_explicit_catalog_name(client, auth_headers):
    with patch(
        "app.routers.satellites._celestrak_name_for_norad",
        new_callable=AsyncMock,
        return_value="SHOULD-NOT-USE",
    ) as lookup:
        resp = await client.post(
            "/api/v1/satellites",
            headers=auth_headers,
            json={
                "name": "CARTOSAT-2A",
                "line1": CARTOSAT_2A_L1,
                "line2": CARTOSAT_2A_L2,
            },
        )
    assert resp.status_code == 201, resp.text
    assert resp.json()["name"] == "CARTOSAT-2A"
    lookup.assert_not_awaited()
