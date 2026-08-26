"""Exact-DOI-only Crossref cited-by lookup. No title/bibliographic fallback."""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from urllib.parse import quote

import pytest

from app.services import citation_counts as counts_mod
from app.services.citation_counts import CROSSREF, fetch_crossref, normalize_doi


def _article(**kwargs) -> SimpleNamespace:
    defaults = dict(
        doi="https://doi.org/10.33411/IJIST/20190101011",
        title="Urban Heat Island Intensity in a Dense Asian City",
        authors=["A. Researcher"],
        crossref_citation_count=99,
        crossref_work_url="https://doi.org/10.33411/old-cached",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, handler):
        self._handler = handler
        self.calls: list[tuple[str, dict | None]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def get(self, url, params=None, **_kwargs):
        self.calls.append((url, params))
        return self._handler(url, params)


def _patch_client(monkeypatch, handler) -> _FakeClient:
    fake = _FakeClient(handler)

    def _factory(*_args, **_kwargs):
        return fake

    monkeypatch.setattr(counts_mod.httpx, "AsyncClient", _factory)
    return fake


def test_fetch_crossref_source_has_no_search_fallback():
    source = inspect.getsource(fetch_crossref)
    assert "query.bibliographic" not in source
    assert "query.title" not in source
    assert "OPENALEX" not in source
    assert "openalex" not in source.lower()
    assert "title_overlap" not in source
    assert "crossref_citation_count" not in source


@pytest.mark.asyncio
async def test_fetch_crossref_returns_zero_when_article_has_no_doi(monkeypatch):
    fake = _patch_client(monkeypatch, lambda url, params: (_ for _ in ()).throw(AssertionError("no HTTP")))
    count, doi, url = await fetch_crossref(_article(doi=None))
    assert (count, doi, url) == (0, None, None)
    assert fake.calls == []


@pytest.mark.asyncio
async def test_fetch_crossref_exact_doi_lookup_works(monkeypatch):
    requested = "10.33411/IJIST/20190101011"
    expected_url = f"{CROSSREF}/{quote(requested, safe=':/')}"

    def handler(url, params):
        assert params is None
        assert "openalex" not in url.lower()
        assert url == expected_url
        return _FakeResponse(
            200,
            {
                "message": {
                    "DOI": "https://doi.org/10.33411/IJIST/20190101011",
                    "is-referenced-by-count": 7,
                    "URL": "https://doi.org/10.33411/IJIST/20190101011",
                    "title": ["Some other paper that must not be used for matching"],
                }
            },
        )

    fake = _patch_client(monkeypatch, handler)
    count, doi, work_url = await fetch_crossref(_article())
    assert count == 7
    assert doi == requested
    assert work_url == "https://doi.org/10.33411/IJIST/20190101011"
    assert fake.calls == [(expected_url, None)]


@pytest.mark.asyncio
async def test_fetch_crossref_accepts_case_insensitive_doi_match(monkeypatch):
    requested = "10.33411/IJIST/20190101011"

    def handler(url, params):
        return _FakeResponse(
            200,
            {
                "message": {
                    "DOI": "10.33411/ijist/20190101011",
                    "is-referenced-by-count": 3,
                    "URL": "https://api.crossref.org/works/10.33411/ijist/20190101011",
                }
            },
        )

    _patch_client(monkeypatch, handler)
    count, doi, work_url = await fetch_crossref(_article(doi=requested))
    assert count == 3
    assert doi == "10.33411/ijist/20190101011"
    assert work_url == "https://api.crossref.org/works/10.33411/ijist/20190101011"
    assert doi.lower() == requested.lower()


@pytest.mark.asyncio
async def test_fetch_crossref_rejects_mismatched_crossref_doi(monkeypatch):
    def handler(url, params):
        return _FakeResponse(
            200,
            {
                "message": {
                    "DOI": "10.9999/wrong-paper",
                    "is-referenced-by-count": 400,
                    "URL": "https://doi.org/10.9999/wrong-paper",
                    "title": ["Urban Heat Island Intensity in a Dense Asian City"],
                }
            },
        )

    fake = _patch_client(monkeypatch, handler)
    count, doi, work_url = await fetch_crossref(_article())
    assert (count, doi, work_url) == (0, None, None)
    assert len(fake.calls) == 1
    assert fake.calls[0][1] is None
    assert fake.calls[0][0].startswith(f"{CROSSREF}/")


@pytest.mark.asyncio
async def test_fetch_crossref_non_200_does_not_search_by_title(monkeypatch):
    def handler(url, params):
        assert params is None
        assert "query.bibliographic" not in (url or "")
        assert "query.title" not in (url or "")
        assert "openalex.org" not in url
        assert url.startswith(f"{CROSSREF}/")
        assert url != CROSSREF
        return _FakeResponse(404, {"status": "error"})

    fake = _patch_client(monkeypatch, handler)
    article = _article(
        doi="10.33411/IJIST/missing",
        title="A unique title that would match bibliographic search",
        authors=["Match Me"],
        crossref_citation_count=42,
        crossref_work_url="https://doi.org/cached",
    )
    count, doi, work_url = await fetch_crossref(article)
    assert (count, doi, work_url) == (0, None, None)
    assert [url for url, _params in fake.calls] == [
        f"{CROSSREF}/{quote(normalize_doi(article.doi), safe=':/')}"
    ]


@pytest.mark.asyncio
async def test_fetch_crossref_does_not_reuse_existing_counts_on_failure(monkeypatch):
    def handler(url, params):
        return _FakeResponse(503)

    _patch_client(monkeypatch, handler)
    article = _article(crossref_citation_count=99, crossref_work_url="https://doi.org/stale")
    count, doi, work_url = await fetch_crossref(article)
    assert count == 0
    assert doi is None
    assert work_url is None
    assert article.crossref_citation_count == 99
    assert article.crossref_work_url == "https://doi.org/stale"


@pytest.mark.asyncio
async def test_fetch_crossref_missing_returned_doi_is_rejected(monkeypatch):
    def handler(url, params):
        return _FakeResponse(
            200,
            {"message": {"is-referenced-by-count": 12, "URL": "https://example.test/work"}},
        )

    _patch_client(monkeypatch, handler)
    assert await fetch_crossref(_article()) == (0, None, None)
