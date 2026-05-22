"""Minimal OAuth 2.1 shim — fixed client_id/secret, issues the MCP bearer token.

Claude.ai cowork requires OAuth (client_id + secret in Advanced settings); it
won't accept a raw Bearer header. This module implements just enough of the
OAuth 2.1 authorization_code flow (with PKCE) to satisfy that UI:

  * Discovery (RFC 8414 + RFC 9728)
  * Dynamic Client Registration (RFC 7591) — returns our fixed creds regardless
  * Authorize — auto-approves (no human login UI), redirects back with a code
  * Token — validates client_secret + code, returns the MCP bearer token

Single-tenant by design. Anyone who can reach /authorize gets redirected with
an auth code; real security comes from (1) keeping client_secret out of public
clients and (2) putting the whole server behind a network boundary (Cloudflare
Access / VPN / IP allowlist).
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any

from starlette.datastructures import FormData
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route

logger = logging.getLogger("farma_tools_mcp.oauth")

_CODE_TTL_SECONDS = 600
_PENDING_GC_THRESHOLD = 100


@dataclass
class _PendingCode:
    redirect_uri: str
    code_challenge: str | None
    code_challenge_method: str | None
    issued_at: float


class OAuthShim:
    """OAuth endpoints that issue a fixed bearer token after client_secret check."""

    def __init__(self, *, client_id: str, client_secret: str, access_token: str) -> None:
        if not client_id or not client_secret or not access_token:
            raise ValueError("OAuthShim requires non-empty client_id, client_secret, and access_token")
        self._client_id = client_id
        self._client_secret = client_secret
        self._access_token = access_token
        self._pending: dict[str, _PendingCode] = {}

    def routes(self) -> list[Route]:
        return [
            Route(
                "/.well-known/oauth-protected-resource",
                self._protected_resource_metadata,
                methods=["GET"],
            ),
            Route(
                "/.well-known/oauth-authorization-server",
                self._authorization_server_metadata,
                methods=["GET"],
            ),
            Route("/register", self._register, methods=["POST"]),
            Route("/authorize", self._authorize, methods=["GET"]),
            Route("/token", self._token, methods=["POST"]),
        ]

    def paths(self) -> set[str]:
        return {r.path for r in self.routes()}

    @staticmethod
    def _issuer(request: Request) -> str:
        # Honor X-Forwarded-Proto/Host so discovery returns the public URL
        # when running behind nginx / Cloudflare.
        scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
        host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
        return f"{scheme}://{host}"

    async def _protected_resource_metadata(self, request: Request) -> JSONResponse:
        issuer = self._issuer(request)
        return JSONResponse(
            {
                "resource": issuer,
                "authorization_servers": [issuer],
                "bearer_methods_supported": ["header"],
            }
        )

    async def _authorization_server_metadata(self, request: Request) -> JSONResponse:
        issuer = self._issuer(request)
        return JSONResponse(
            {
                "issuer": issuer,
                "authorization_endpoint": f"{issuer}/authorize",
                "token_endpoint": f"{issuer}/token",
                "registration_endpoint": f"{issuer}/register",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code"],
                "code_challenge_methods_supported": ["S256", "plain"],
                "token_endpoint_auth_methods_supported": [
                    "client_secret_post",
                    "client_secret_basic",
                ],
            }
        )

    async def _register(self, request: Request) -> JSONResponse:
        body: dict[str, Any] = {}
        if request.headers.get("content-type", "").lower().startswith("application/json"):
            try:
                body = await request.json()
            except Exception:
                body = {}
        return JSONResponse(
            {
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "redirect_uris": body.get("redirect_uris", []),
                "token_endpoint_auth_method": "client_secret_post",
                "grant_types": ["authorization_code"],
                "response_types": ["code"],
            }
        )

    async def _authorize(self, request: Request) -> Response:
        params = request.query_params
        response_type = params.get("response_type", "")
        client_id = params.get("client_id", "")
        redirect_uri = params.get("redirect_uri", "")
        state = params.get("state", "")
        code_challenge = params.get("code_challenge")
        code_challenge_method = params.get("code_challenge_method")

        if response_type != "code":
            return JSONResponse({"error": "unsupported_response_type"}, status_code=400)
        if not secrets.compare_digest(client_id, self._client_id):
            logger.warning("oauth_authorize_bad_client client_id=%r", client_id)
            return JSONResponse({"error": "invalid_client"}, status_code=400)
        if not redirect_uri:
            return JSONResponse(
                {"error": "invalid_request", "error_description": "missing redirect_uri"},
                status_code=400,
            )

        code = secrets.token_urlsafe(32)
        self._pending[code] = _PendingCode(
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            issued_at=time.monotonic(),
        )
        self._gc_pending()

        sep = "&" if "?" in redirect_uri else "?"
        location = f"{redirect_uri}{sep}code={code}"
        if state:
            location += f"&state={state}"
        return RedirectResponse(location, status_code=302)

    async def _token(self, request: Request) -> JSONResponse:
        form = await request.form()
        client_id, client_secret = self._extract_client_creds(request, form)
        if not secrets.compare_digest(client_id, self._client_id) or not secrets.compare_digest(
            client_secret, self._client_secret
        ):
            logger.warning("oauth_token_bad_creds client_id=%r", client_id)
            return JSONResponse({"error": "invalid_client"}, status_code=401)

        grant_type = form.get("grant_type", "")
        if grant_type != "authorization_code":
            return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)

        code = form.get("code", "")
        pending = self._pending.pop(code, None)
        if pending is None or (time.monotonic() - pending.issued_at) > _CODE_TTL_SECONDS:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)

        if pending.code_challenge:
            verifier = form.get("code_verifier", "")
            if not self._verify_pkce(verifier, pending.code_challenge, pending.code_challenge_method or "plain"):
                return JSONResponse(
                    {"error": "invalid_grant", "error_description": "PKCE verification failed"},
                    status_code=400,
                )

        # Effectively non-expiring; Claude.ai will re-run the flow if needed.
        return JSONResponse(
            {
                "access_token": self._access_token,
                "token_type": "Bearer",
                "expires_in": 365 * 24 * 3600,
            }
        )

    @staticmethod
    def _extract_client_creds(request: Request, form: FormData) -> tuple[str, str]:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("basic "):
            try:
                decoded = base64.b64decode(auth.split(" ", 1)[1]).decode("utf-8")
                cid, _, csec = decoded.partition(":")
                return cid, csec
            except Exception:
                return "", ""
        return str(form.get("client_id", "")), str(form.get("client_secret", ""))

    @staticmethod
    def _verify_pkce(verifier: str, challenge: str, method: str) -> bool:
        if not verifier:
            return False
        if method == "plain":
            return secrets.compare_digest(verifier, challenge)
        if method == "S256":
            digest = hashlib.sha256(verifier.encode("ascii")).digest()
            computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
            return secrets.compare_digest(computed, challenge)
        return False

    def _gc_pending(self) -> None:
        if len(self._pending) < _PENDING_GC_THRESHOLD:
            return
        now = time.monotonic()
        expired = [c for c, p in self._pending.items() if (now - p.issued_at) > _CODE_TTL_SECONDS]
        for c in expired:
            self._pending.pop(c, None)
