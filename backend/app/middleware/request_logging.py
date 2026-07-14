"""HTTP request logging middleware."""

from __future__ import annotations

import time
import uuid

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        start = time.perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            status = response.status_code if response is not None else 500
            logger.info(
                "{} {} -> {} [{:.1f}ms] id={}",
                request.method,
                request.url.path,
                status,
                duration_ms,
                request_id,
            )
            if response is not None:
                response.headers["X-Request-ID"] = request_id
