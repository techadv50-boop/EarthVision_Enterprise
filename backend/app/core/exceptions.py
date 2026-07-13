"""Application-specific exceptions and handlers."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from loguru import logger


class EarthVisionError(Exception):
    """Base application exception."""

    def __init__(self, message: str, status_code: int = 400, details: Any = None) -> None:
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)


class NotFoundError(EarthVisionError):
    def __init__(self, message: str = "Resource not found", details: Any = None) -> None:
        super().__init__(message, status_code=404, details=details)


class UnauthorizedError(EarthVisionError):
    def __init__(self, message: str = "Unauthorized", details: Any = None) -> None:
        super().__init__(message, status_code=401, details=details)


class ForbiddenError(EarthVisionError):
    def __init__(self, message: str = "Forbidden", details: Any = None) -> None:
        super().__init__(message, status_code=403, details=details)


class ConflictError(EarthVisionError):
    def __init__(self, message: str = "Conflict", details: Any = None) -> None:
        super().__init__(message, status_code=409, details=details)


class ValidationError(EarthVisionError):
    def __init__(self, message: str = "Validation error", details: Any = None) -> None:
        super().__init__(message, status_code=422, details=details)


class ExternalServiceError(EarthVisionError):
    def __init__(self, message: str = "External service error", details: Any = None) -> None:
        super().__init__(message, status_code=502, details=details)


def register_exception_handlers(app: FastAPI) -> None:
    """Register global exception handlers."""

    @app.exception_handler(EarthVisionError)
    async def earthvision_error_handler(_: Request, exc: EarthVisionError) -> JSONResponse:
        logger.warning("Application error: {} | details={}", exc.message, exc.details)
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message, "details": exc.details},
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception: {}", exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )
