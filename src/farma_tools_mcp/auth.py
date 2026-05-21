"""Bearer-token auth middleware for HTTP transports."""

from __future__ import annotations

import json
import logging
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

logger = logging.getLogger("farma_tools_mcp.auth")


class BearerAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, expected_token: str) -> None:
        super().__init__(app)
        if not expected_token:
            raise ValueError("BearerAuthMiddleware requires a non-empty expected_token")
        self._expected_token = expected_token

    async def dispatch(self, request: Request, call_next):
        header = request.headers.get("authorization", "")
        scheme, _, presented = header.partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(presented, self._expected_token):
            client_host = request.client.host if request.client else None
            logger.warning("auth_rejected path=%s client=%s", request.url.path, client_host)
            body = json.dumps({"error": "unauthorized"})
            return Response(body, status_code=401, media_type="application/json", headers={"WWW-Authenticate": "Bearer"})
        return await call_next(request)
