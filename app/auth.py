"""Bearer-token guard for /api/* and /upload.

Single shared secret (``settings.api_token``) per deployment — same trust
boundary as the .env file. The iframe widget is served the token at render
time and forwards it on every fetch via Authorization: Bearer.

CORS preflight (OPTIONS) is always allowed so the browser can negotiate.
"""

from __future__ import annotations

import hmac
import logging

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from config import settings

logger = logging.getLogger(__name__)

PROTECTED_PREFIXES: tuple[str, ...] = ("/api/", "/upload")
EXEMPT_PATHS: frozenset[str] = frozenset({"/health"})


def _matches_protected(path: str) -> bool:
    if path in EXEMPT_PATHS:
        return False
    return any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in PROTECTED_PREFIXES)


class APITokenMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)
        if not _matches_protected(request.url.path):
            return await call_next(request)

        token = settings.api_token
        if not token:
            logger.error(
                "BUILDCONTROL_API_TOKEN not configured — denying %s %s",
                request.method,
                request.url.path,
            )
            return JSONResponse(
                {"detail": "Server misconfigured: BUILDCONTROL_API_TOKEN missing"},
                status_code=500,
            )

        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            return JSONResponse(
                {"detail": "Missing bearer token"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        provided = header[7:].strip()
        if not provided or not hmac.compare_digest(provided, token):
            return JSONResponse(
                {"detail": "Invalid token"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

        return await call_next(request)
