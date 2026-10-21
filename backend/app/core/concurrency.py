"""Helpers to keep FastAPI's event loop responsive under heavy EO work."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import partial
from typing import ParamSpec, TypeVar

from starlette.concurrency import run_in_threadpool

from app.core.exceptions import GatewayTimeoutError

P = ParamSpec("P")
R = TypeVar("R")

# Stay under Cloudflare's ~100s origin proxy limit and the FE axios budget.
DEFAULT_SYNC_TIMEOUT_S = 55.0


async def run_sync(func: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
    """Run blocking raster/CPU work off the asyncio event loop.

    Imagery composites/indices/classification use sync GDAL/rasterio. Calling
    them directly inside ``async def`` routes freezes *all* requests (including
    /health and /login) when uvicorn runs a single worker — Cloudflare then
    reports 502/520 origin errors.
    """
    if kwargs:
        return await run_in_threadpool(partial(func, *args, **kwargs))
    return await run_in_threadpool(func, *args)


async def run_sync_timeout(
    func: Callable[P, R],
    *args: P.args,
    timeout: float | None = None,
    timeout_s: float | None = None,
    label: str | None = None,
    **kwargs: P.kwargs,
) -> R:
    """Like ``run_sync`` but fail with 504 before the client/Cloudflare gives up."""
    budget = timeout_s if timeout_s is not None else timeout
    if budget is None:
        budget = DEFAULT_SYNC_TIMEOUT_S
    what = (label or "Imagery render").strip() or "Imagery render"
    try:
        return await asyncio.wait_for(
            run_sync(func, *args, **kwargs),
            timeout=max(0.05, float(budget)),
        )
    except TimeoutError as exc:
        raise GatewayTimeoutError(
            f"{what} timed out — zoom in or retry. "
            "Previews stay small on slow links to avoid Cloudflare/origin failures."
        ) from exc
