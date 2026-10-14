"""Security headers including SPA Content-Security-Policy (RC).

Does not weaken CORS. Plugin iframes use opaque srcdoc CSP separately.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


# Tight default for HTML/SPA; API JSON responses also get nosniff + frame deny.
_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "frame-src 'self' blob:; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'self'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=()",
        )
        # Apply CSP to document navigations; keep API JSON free of conflicting CSP
        path = request.url.path or ""
        if not path.startswith("/api/") and not path.startswith("/docs") and not path.startswith("/redoc"):
            response.headers.setdefault("Content-Security-Policy", _CSP)
        return response
