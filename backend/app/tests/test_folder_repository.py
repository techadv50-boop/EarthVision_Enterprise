"""Folder repository helpers (relay.xdgen.com)."""

from __future__ import annotations

import pytest

from app.schemas.folder_repository import validate_relay_repository_url
from app.services.folder_repository_service import _extract_dates, _extract_files


def test_validate_relay_repository_url_ok():
    url = validate_relay_repository_url(
        "https://relay.xdgen.com/api/v1/archives/Raza_uploads/"
    )
    assert url == "https://relay.xdgen.com/api/v1/archives/Raza_uploads"


def test_validate_relay_repository_url_rejects_non_relay():
    with pytest.raises(ValueError, match="relay.xdgen.com"):
        validate_relay_repository_url("https://catalogue.dataspace.copernicus.eu/odata/v1")


def test_extract_dates_from_list_and_objects():
    assert _extract_dates(["2024-01-02", "2024-01-03"]) == ["2024-01-02", "2024-01-03"]
    assert _extract_dates({"dates": [{"date": "2024-05-01"}, "2024-05-02"]}) == [
        "2024-05-01",
        "2024-05-02",
    ]


def test_extract_files_prefers_path_relative_path_name():
    files = _extract_files(
        {
            "files": [
                {"path": "a/b.tif", "size": 10},
                {"relative_path": "c/d.jp2"},
                {"name": "only-name.bin"},
            ]
        }
    )
    assert [f.path for f in files] == ["a/b.tif", "c/d.jp2", "only-name.bin"]
