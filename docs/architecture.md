# Architecture

Internal design notes for `farma-tools-mcp`. Pair with [README.md](../README.md) for usage.

## Big picture

```
            ┌────────────────────────────────────────────────┐
            │           FastMCP("farma-tools")               │
            │   build_server() in src/farma_tools_mcp/server │
            └───────────────┬────────────────────────────────┘
                            │ registers 5 @mcp.tool functions
                            ▼
        ┌───────────┬──────────────┬──────────────┬───────────┬────────────┐
        │  ares     │ cuzk_parcela │ cuzk_areas   │ open_meteo│ osm_nearby │
        └───────────┴──────────────┴──────────────┴───────────┴────────────┘
                            │ shared httpx.AsyncClient (http_utils.py)
                            ▼
            ARES   ·   ČÚZK ArcGIS   ·   Open-Meteo   ·   Overpass mirrors
```

The CLI ([cli.py](../src/farma_tools_mcp/cli.py)) picks the transport and either:

- runs the FastMCP instance over **stdio** (Claude Desktop), or
- wraps it in a Starlette app with [`BearerAuthMiddleware`](../src/farma_tools_mcp/auth.py),
  optionally mounts the [`OAuthShim`](../src/farma_tools_mcp/oauth.py) routes,
  and serves it over **streamable-http** (default) or **SSE**.

## Transports

| Transport         | Endpoint  | Use case                              | Auth                    |
| ----------------- | --------- | ------------------------------------- | ----------------------- |
| `stdio`           | —         | Local Claude Desktop, MCP CLI         | none (process boundary) |
| `streamable-http` | `/mcp`    | Default — modern MCP HTTP transport   | Bearer token, required  |
| `sse`             | `/sse`    | Fallback for older clients            | Bearer token, required  |

For HTTP transports, `MCP_BEARER_TOKEN` is mandatory at startup. The process
exits with status 2 on a missing token before any port is bound — this is the
fail-fast behavior tested in [test_auth.py](../tests/test_auth.py).

## OAuth shim

Claude.ai cowork's UI doesn't accept a raw Bearer header — it speaks OAuth 2.1
(Client ID / Secret in *Advanced settings*). [oauth.py](../src/farma_tools_mcp/oauth.py)
implements the minimum surface that satisfies the cowork client:

| Endpoint                                       | Behavior                                                                 |
| ---------------------------------------------- | ------------------------------------------------------------------------ |
| `GET /.well-known/oauth-protected-resource`    | RFC 9728 metadata — points at the authorization server (self).           |
| `GET /.well-known/oauth-authorization-server`  | RFC 8414 metadata — declares `/authorize`, `/token`, `/register`, PKCE.  |
| `POST /register`                               | RFC 7591 DCR — always returns the fixed `OAUTH_CLIENT_ID/SECRET`.        |
| `GET /authorize`                               | Auto-approves; redirects back with a short-lived code (no login UI).     |
| `POST /token`                                  | Validates `client_secret` + code (+ PKCE if used); returns `MCP_BEARER_TOKEN` as `access_token`. |

The shim is **enabled only when both** `OAUTH_CLIENT_ID` and `OAUTH_CLIENT_SECRET`
are set; otherwise the server runs raw-Bearer only. When enabled, the five OAuth
paths are added to the Starlette app and the Bearer middleware skips them via
`exempt_paths`.

The discovery responses honor `X-Forwarded-Proto`/`X-Forwarded-Host` so that
when running behind nginx / Cloudflare the issuer URL matches the public domain.

**Trust model:** anyone who reaches `/authorize` gets a redirect with a fresh
code, so security relies on `client_secret` at the `/token` exchange plus the
network boundary in front of the server. Single-tenant by design — no user
accounts, no scopes, no refresh tokens.

## Tool design

Every tool is an `async` function in `src/farma_tools_mcp/tools/` that returns a
**Czech-language Markdown string** — the LLM inserts it verbatim into the
conversation. Tools never raise on upstream errors; they return a Czech error
sentence so the user model can react gracefully.

Tool signatures use `param: T = Field(description=…)` rather than
`Annotated[T, Field(…)]`. FastMCP unpacks both forms into JSON schema, but the
plain-default form is shorter and verified to round-trip correctly through
`mcp.list_tools()`. Don't refactor without re-checking the generated schema.

## External-API quirks worth knowing

- **ARES** returns **HTTP 404** (not a 200 with an error envelope) for unknown
  IČOs. Both code paths exist in [ares.py](../src/farma_tools_mcp/tools/ares.py).
- **ČÚZK** rejects points outside ČR with a generic error. To save a round-trip
  we short-circuit on a hard-coded bounding box (lat 48–51.5, lon 12–19) in both
  `cuzk_parcela` and `cuzk_areas`.
- **Overpass** mirror `overpass-api.de` returns 406 from time to time
  (server-side, not us). The tool tries mirrors in order:
  1. `overpass.openstreetmap.fr` (most reliable lately)
  2. `overpass-api.de`
  3. `overpass.kumi.systems`

  If all three fail, we return a Czech "všechny Overpass mirrors selhaly" message.
- **Open-Meteo** has no API key but enforces a soft daily quota; the tool
  returns the raw HTTP status in a Czech message and lets the caller retry.

## Testing

- `pytest-asyncio` in `asyncio_mode = "auto"` — plain `async def test_*` is
  awaited automatically.
- All HTTP is mocked via [`respx`](https://lundberg.github.io/respx/), pulling
  payloads from `tests/fixtures/`. No test ever hits the network.
- Fixtures are **real captured responses** from live APIs (date stamped in
  [tests/fixtures/README.md](../tests/fixtures/README.md)). Refresh them when an
  upstream contract changes — curl one-liners are documented there.

## Things that are deliberately out of scope

- No caching layer. Tools are stateless single-shot lookups.
- No rate-limiting. Upstream APIs throttle us if needed.
- No metrics / Prometheus. Logs to stdout, JSON if `LOG_LEVEL=DEBUG`.
- No persistence. The container is restart-safe with zero state.

If any of these change, update this doc and `README.md` together.
