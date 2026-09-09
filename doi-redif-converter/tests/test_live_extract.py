import pytest

from app.extractor import extract_doi
from app.redif import build_filename, to_redif


@pytest.mark.asyncio
async def test_live_extract_sample_doi():
    meta = await extract_doi("https://doi.org/10.33411/IJIST/1936")
    assert meta.ok, meta.error
    assert meta.title.startswith("No Smoke:")
    assert meta.volume == "8"
    assert meta.issue == "3"
    assert meta.pages == "1429-1448"
    assert meta.year == "2026"
    assert meta.month == "June"
    assert len(meta.authors) >= 6
    assert build_filename(meta) == "V8i3p1429-1448.redif"
    text = to_redif(meta)
    assert "Handle: RePEc:abq:IJIST1:v:8:y:2026:i:3:p:1429-1448" in text
