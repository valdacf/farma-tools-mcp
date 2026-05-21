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
- wraps it in a Starlette app with [`BearerAuthMiddleware`](../src/farma_tools_mcp/auth.py)
  and serves it over **SSE** or **streamable-http** (Claude.ai cowork).

## Transports

| Transport         | Use case                              | Auth                    |
| ----------------- | ------------------------------------- | ----------------------- |
| `stdio`           | Local Claude Desktop, MCP CLI         | none (process boundary) |
| `sse`             | Claude.ai cowork (current default)    | Bearer token, required  |
| `streamable-http` | Newer MCP transport, forward-looking  | Bearer token, required  |

For HTTP transports, `MCP_BEARER_TOKEN` is mandatory at startup. The process
exits with status 2 on a missing token before any port is bound — this is the
fail-fast behavior tested in [test_auth.py](../tests/test_auth.py).

`sse` is the default today because that's what Claude.ai cowork connects to in
production. When cowork prefers streamable-http, change the default in
[cli.py](../src/farma_tools_mcp/cli.py).

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
