"""Tests for the OAuth 2.1 shim used by Claude.ai cowork."""

from __future__ import annotations

import base64
import hashlib
import secrets

import httpx
import pytest
from starlette.applications import Starlette

from farma_tools_mcp.oauth import OAuthShim


@pytest.fixture
def shim() -> OAuthShim:
    return OAuthShim(client_id="cid-abc", client_secret="sec-xyz", access_token="bearer-token-123")


@pytest.fixture
def app(shim: OAuthShim) -> Starlette:
    return Starlette(routes=shim.routes())


@pytest.fixture
async def client(app: Starlette):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def test_constructor_rejects_empty_args() -> None:
    with pytest.raises(ValueError):
        OAuthShim(client_id="", client_secret="s", access_token="t")
    with pytest.raises(ValueError):
        OAuthShim(client_id="c", client_secret="", access_token="t")
    with pytest.raises(ValueError):
        OAuthShim(client_id="c", client_secret="s", access_token="")


async def test_protected_resource_metadata(client: httpx.AsyncClient) -> None:
    r = await client.get("/.well-known/oauth-protected-resource")
    assert r.status_code == 200
    data = r.json()
    assert data["resource"] == "http://test"
    assert data["authorization_servers"] == ["http://test"]


async def test_authorization_server_metadata(client: httpx.AsyncClient) -> None:
    r = await client.get("/.well-known/oauth-authorization-server")
    assert r.status_code == 200
    data = r.json()
    assert data["issuer"] == "http://test"
    assert data["authorization_endpoint"] == "http://test/authorize"
    assert data["token_endpoint"] == "http://test/token"
    assert data["registration_endpoint"] == "http://test/register"
    assert "code" in data["response_types_supported"]
    assert "authorization_code" in data["grant_types_supported"]
    assert "S256" in data["code_challenge_methods_supported"]


async def test_metadata_honors_forwarded_proto_and_host(client: httpx.AsyncClient) -> None:
    r = await client.get(
        "/.well-known/oauth-authorization-server",
        headers={"x-forwarded-proto": "https", "x-forwarded-host": "farma.example.com"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["issuer"] == "https://farma.example.com"
    assert data["authorization_endpoint"] == "https://farma.example.com/authorize"


async def test_register_returns_fixed_credentials(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/register",
        json={"redirect_uris": ["https://claude.ai/cb"], "client_name": "Claude"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["client_id"] == "cid-abc"
    assert data["client_secret"] == "sec-xyz"
    assert data["redirect_uris"] == ["https://claude.ai/cb"]


async def test_register_works_with_empty_body(client: httpx.AsyncClient) -> None:
    r = await client.post("/register")
    assert r.status_code == 200
    assert r.json()["client_id"] == "cid-abc"


async def test_authorize_redirects_with_code_and_state(client: httpx.AsyncClient) -> None:
    r = await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": "cid-abc",
            "redirect_uri": "https://claude.ai/cb",
            "state": "rnd-state",
        },
        follow_redirects=False,
    )
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("https://claude.ai/cb?code=")
    assert "state=rnd-state" in loc


async def test_authorize_preserves_existing_query_in_redirect_uri(client: httpx.AsyncClient) -> None:
    r = await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": "cid-abc",
            "redirect_uri": "https://claude.ai/cb?foo=bar",
        },
        follow_redirects=False,
    )
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("https://claude.ai/cb?foo=bar&code=")


async def test_authorize_rejects_wrong_client(client: httpx.AsyncClient) -> None:
    r = await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": "evil",
            "redirect_uri": "https://x/cb",
        },
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_client"


async def test_authorize_rejects_unsupported_response_type(client: httpx.AsyncClient) -> None:
    r = await client.get(
        "/authorize",
        params={
            "response_type": "token",
            "client_id": "cid-abc",
            "redirect_uri": "https://claude.ai/cb",
        },
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert r.json()["error"] == "unsupported_response_type"


async def _get_code(client: httpx.AsyncClient, **extra_params: str) -> str:
    params = {
        "response_type": "code",
        "client_id": "cid-abc",
        "redirect_uri": "https://claude.ai/cb",
    }
    params.update(extra_params)
    r = await client.get("/authorize", params=params, follow_redirects=False)
    assert r.status_code == 302, r.text
    return r.headers["location"].split("code=")[1].split("&")[0]


async def test_token_exchanges_code_for_bearer(client: httpx.AsyncClient) -> None:
    code = await _get_code(client)
    r = await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": "cid-abc",
            "client_secret": "sec-xyz",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["access_token"] == "bearer-token-123"
    assert data["token_type"] == "Bearer"
    assert data["expires_in"] > 0


async def test_token_rejects_wrong_client_secret(client: httpx.AsyncClient) -> None:
    code = await _get_code(client)
    r = await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": "cid-abc",
            "client_secret": "WRONG",
        },
    )
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_client"


async def test_token_accepts_basic_auth(client: httpx.AsyncClient) -> None:
    code = await _get_code(client)
    basic = base64.b64encode(b"cid-abc:sec-xyz").decode()
    r = await client.post(
        "/token",
        data={"grant_type": "authorization_code", "code": code},
        headers={"Authorization": f"Basic {basic}"},
    )
    assert r.status_code == 200
    assert r.json()["access_token"] == "bearer-token-123"


async def test_token_rejects_unknown_code(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": "never-issued",
            "client_id": "cid-abc",
            "client_secret": "sec-xyz",
        },
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_grant"


async def test_token_rejects_unsupported_grant(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "cid-abc",
            "client_secret": "sec-xyz",
        },
    )
    assert r.status_code == 400
    assert r.json()["error"] == "unsupported_grant_type"


async def test_token_consumes_code_on_first_use(client: httpx.AsyncClient) -> None:
    code = await _get_code(client)
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": "cid-abc",
        "client_secret": "sec-xyz",
    }
    r1 = await client.post("/token", data=data)
    r2 = await client.post("/token", data=data)
    assert r1.status_code == 200
    assert r2.status_code == 400
    assert r2.json()["error"] == "invalid_grant"


async def test_token_pkce_s256_success(client: httpx.AsyncClient) -> None:
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    code = await _get_code(client, code_challenge=challenge, code_challenge_method="S256")
    r = await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": "cid-abc",
            "client_secret": "sec-xyz",
            "code_verifier": verifier,
        },
    )
    assert r.status_code == 200


async def test_token_pkce_wrong_verifier_rejected(client: httpx.AsyncClient) -> None:
    verifier = "correct-verifier-value"
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    code = await _get_code(client, code_challenge=challenge, code_challenge_method="S256")
    r = await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": "cid-abc",
            "client_secret": "sec-xyz",
            "code_verifier": "WRONG",
        },
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_grant"


async def test_token_pkce_missing_verifier_when_challenge_set(client: httpx.AsyncClient) -> None:
    code = await _get_code(client, code_challenge="anything", code_challenge_method="plain")
    r = await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": "cid-abc",
            "client_secret": "sec-xyz",
        },
    )
    assert r.status_code == 400
