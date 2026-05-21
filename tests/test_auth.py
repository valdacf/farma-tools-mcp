"""Tests for the Bearer auth middleware and CLI startup contract."""

from __future__ import annotations

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from farma_tools_mcp.auth import BearerAuthMiddleware
from farma_tools_mcp.cli import main


def _build_app(token: str) -> Starlette:
    async def ok(_):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/probe", ok)])
    app.add_middleware(BearerAuthMiddleware, expected_token=token)
    return app


async def test_no_header_returns_401():
    app = _build_app("secret")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/probe")
    assert r.status_code == 401
    assert r.headers.get("www-authenticate") == "Bearer"


async def test_wrong_token_returns_401():
    app = _build_app("secret")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/probe", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


async def test_correct_token_passes_through():
    app = _build_app("secret")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/probe", headers={"Authorization": "Bearer secret"})
    assert r.status_code == 200
    assert r.text == "ok"


def test_empty_token_rejected_at_construction():
    with pytest.raises(ValueError):
        BearerAuthMiddleware(app=None, expected_token="")  # type: ignore[arg-type]


def test_cli_fails_fast_without_token(monkeypatch, capsys):
    monkeypatch.delenv("MCP_BEARER_TOKEN", raising=False)
    rc = main(["--transport", "sse", "--port", "0"])
    assert rc == 2
    captured = capsys.readouterr()
    assert "MCP_BEARER_TOKEN" in captured.err
