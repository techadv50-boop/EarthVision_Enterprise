"""Helpers to keep FastAPI's event loop responsive under heavy EO work."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import ParamSpec, TypeVar

from starlette.concurrency import run_in_threadpool

P = ParamSpec("P")
R = TypeVar("R")


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
