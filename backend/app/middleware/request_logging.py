"""HTTP request logging middleware using Loguru."""

from __future__ import annotations

import time
import uuid

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log method, path, status, duration, and a correlation request id."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        start = time.perf_counter()

        client = request.client.host if request.client else "-"
        logger.bind(request_id=request_id).info(
            f"→ {request.method} {request.url.path} client={client}"
        )

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.bind(request_id=request_id).exception(
                f"✗ {request.method} {request.url.path} failed after {duration_ms:.1f}ms"
            )
            raise

        duration_ms = (time.perf_counter() - start) * 1000
        level = "warning" if response.status_code >= 400 else "info"
        getattr(logger.bind(request_id=request_id), level)(
            f"← {request.method} {request.url.path} "
            f"status={response.status_code} duration={duration_ms:.1f}ms"
        )
        response.headers["X-Request-ID"] = request_id
        return response
