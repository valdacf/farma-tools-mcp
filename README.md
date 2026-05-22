# farma-tools-mcp

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Model Context Protocol (MCP) server exposing five **Czech-domain lookup tools** —
business registry, cadastre, protected areas, weather/climate, and nearby OSM POIs —
purpose-built for brainstorming a hobby farm or any project that needs to combine
ARES, ČÚZK and Open-Meteo data in one conversation.

Designed to plug into **Claude.ai cowork** as a remote MCP, while also running
locally over stdio for Claude Desktop or other MCP clients.

## Tools

| Tool             | What it does                                                                                          |
| ---------------- | ----------------------------------------------------------------------------------------------------- |
| `ares_lookup`    | Fetch a company from ARES by IČO (name, registered office, NACE, registrations).                      |
| `cuzk_parcela`   | Identify the cadastral parcel at given WGS84 coordinates (parcel number, k.ú., obec, land-use, area). |
| `cuzk_areas`     | Check whether coordinates lie in any large-area protected zone (NP, CHKO, NPR, NPP, PR, PP, Natura 2000). |
| `open_meteo`     | Either a 1–14 day forecast or a 10-year ERA5 climate average (monthly Tmax/Tmin, precipitation, frost days). |
| `osm_nearby`     | Find OSM features (farms, roads, water, accommodation, shops, tourism, …) in a radius around a point. |

All tool responses are **Czech-language Markdown** ready to be inserted into a chat
or report.

## Quick start (local, stdio)

```bash
git clone https://github.com/cloudfield/farma-tools-mcp.git
cd farma-tools-mcp
uv sync
uv run farma-tools-mcp --transport stdio
```

Hook it into Claude Desktop by adding to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "farma-tools": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/farma-tools-mcp", "run", "farma-tools-mcp", "--transport", "stdio"]
    }
  }
}
```

## Quick start (remote HTTP, Docker)

```bash
# Generate a token (32 bytes hex)
export MCP_BEARER_TOKEN="$(openssl rand -hex 32)"

# Build & run
docker build -t farma-tools-mcp .
docker run --rm -p 14000:14000 -e MCP_BEARER_TOKEN farma-tools-mcp
```

The server now listens on `http://localhost:14000/mcp` (Streamable HTTP transport — the
modern MCP HTTP protocol; SSE is still available with `--transport sse` on `/sse`).

Verify with `curl`:

```bash
# Missing/wrong token → 401
curl -i http://localhost:14000/mcp

# Correct token → MCP responds (POST a JSON-RPC initialize request, or use mcp-cli)
curl -i -H "Authorization: Bearer $MCP_BEARER_TOKEN" http://localhost:14000/mcp
```

### Connecting Claude.ai cowork

Claude.ai's cowork UI does **not** accept a raw Bearer header — it speaks OAuth 2.1
(Client ID / Client Secret in *Advanced settings*). This server ships with a minimal
OAuth shim: set both env vars and Claude.ai can negotiate a token automatically.

```bash
export MCP_BEARER_TOKEN="$(openssl rand -hex 32)"
export OAUTH_CLIENT_ID="$(openssl rand -hex 16)"
export OAUTH_CLIENT_SECRET="$(openssl rand -hex 32)"

docker run --rm -p 14000:14000 \
  -e MCP_BEARER_TOKEN -e OAUTH_CLIENT_ID -e OAUTH_CLIENT_SECRET \
  farma-tools-mcp
```

In Claude.ai under *Settings → Integrations → Add MCP server*:

| Field                          | Value                                                       |
| ------------------------------ | ----------------------------------------------------------- |
| Name                           | `farma-tools`                                               |
| URL                            | `https://your-host.example.com/mcp`                         |
| Client ID (Advanced settings)  | value from `OAUTH_CLIENT_ID`                                |
| Client Secret (Advanced settings) | value from `OAUTH_CLIENT_SECRET`                         |

The shim auto-approves the OAuth flow (no human login prompt) and hands Claude.ai a
Bearer token equal to `MCP_BEARER_TOKEN`. **Always front this with HTTPS and a
network boundary** (Cloudflare Access, VPN, IP allowlist) — `/authorize` accepts
anyone who knows the URL, so the only effective secret is `OAUTH_CLIENT_SECRET` at
the token exchange.

Both `OAUTH_CLIENT_ID` and `OAUTH_CLIENT_SECRET` must be set together (or both
unset, in which case only raw-Bearer auth is enabled).

## Compose integration (existing stack)

Copy `docker-compose.snippet.yml` into your top-level `docker-compose.yml` under
`services:`. Make sure `MCP_BEARER_TOKEN` is set in your `.env` file alongside the
compose file, and that the `ai-net` network exists (or rename it to match yours).

```bash
echo "MCP_BEARER_TOKEN=$(openssl rand -hex 32)" >> .env
docker compose up -d farma-tools-mcp
```

## CLI

```
farma-tools-mcp [--transport {stdio,sse,streamable-http}] [--host HOST] [--port PORT] [--log-level LEVEL]
```

All flags also read from environment variables:
`MCP_TRANSPORT`, `MCP_HOST`, `MCP_PORT`, `MCP_BEARER_TOKEN`,
`OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`, `LOG_LEVEL`.

For HTTP transports, `MCP_BEARER_TOKEN` is **required** — the process exits with
status 2 at startup if it is missing. `OAUTH_CLIENT_ID` and `OAUTH_CLIENT_SECRET`
are optional but must be set together; presence of both enables the OAuth shim
on `/authorize`, `/token`, `/register`, and the two `/.well-known/oauth-*`
discovery endpoints.

## Development

```bash
uv sync                    # install everything including dev deps
uv run pytest              # all tests, fully offline (respx-mocked HTTP)
uv run farma-tools-mcp --help
```

All tests run with **no real network access** — every external API
(`ares.gov.cz`, `ags.cuzk.cz`, `api.open-meteo.com`, Overpass mirrors) is mocked
via `respx`. JSON fixtures live in `tests/fixtures/` so they can be inspected
and refreshed from real API responses when upstream contracts change.

### Project layout

```
src/farma_tools_mcp/
  cli.py            # argparse entry-point, transport dispatch
  server.py         # FastMCP instance, tool registration, descriptions
  auth.py           # Bearer-token Starlette middleware
  oauth.py          # Minimal OAuth 2.1 shim for Claude.ai cowork
  http_utils.py     # shared httpx.AsyncClient defaults
  tools/
    ares.py
    cuzk_parcela.py
    cuzk_areas.py
    open_meteo.py
    osm_nearby.py
tests/
  fixtures/         # captured/curated JSON payloads per tool
  test_*.py         # respx-mocked tests + auth middleware tests
```

## Troubleshooting

| Symptom                                                  | Probable cause / fix                                                                |
| -------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| Container exits immediately with `FATAL: MCP_BEARER_TOKEN` | The env var is unset. Set it on the container (and in `.env` if using compose).     |
| Container exits with `FATAL: OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET` | Only one of the pair is set. Either set both or neither.                  |
| Claude.ai cowork keeps showing 401 (raw Bearer)          | Cowork UI doesn't support raw Bearer — enable the OAuth shim (set `OAUTH_CLIENT_ID`/`SECRET`) and configure them under Advanced settings. |
| Claude.ai cowork OAuth flow fails at `/token`            | Client ID or Secret in Advanced settings doesn't match server env vars.             |
| Tool returns `Všechny Overpass mirrors selhaly`          | All three OSM mirrors are temporarily down. Retry; consider hosting your own.       |
| `Open-Meteo vrátil HTTP 503`                             | Open-Meteo rate-limit — back off and retry; no API key needed but quotas exist.     |
| `Chyba: leží mimo ČR`                                    | Coordinates outside the ČR bounding box (lat 48–51.5, lon 12–19). All ČÚZK tools enforce this. |
| Stdio mode "hangs"                                       | Expected — stdio servers wait for newline-delimited JSON-RPC on stdin from the client. |

## Notes

- **No caching, no rate-limiting, no persistent state.** Stateless tool calls only.
- **Modern transports.** `streamable-http` (endpoint `/mcp`) is the default; SSE
  (`--transport sse`, endpoint `/sse`) is kept as a fallback for older clients.
- **Czech bounding box** for ČÚZK tools is hard-coded (lat 48–51.5, lon 12–19) —
  outside the box, the tool short-circuits with a friendly message.

## Upstream data sources

- ARES — <https://ares.gov.cz/swagger-ui/>
- ČÚZK ArcGIS — <https://ags.cuzk.cz/arcgis/rest/services/RUIAN/MapServer>
- Open-Meteo — <https://open-meteo.com/en/docs>
- Overpass API — <https://wiki.openstreetmap.org/wiki/Overpass_API>
- MCP Python SDK — <https://github.com/modelcontextprotocol/python-sdk>

## License

[MIT](LICENSE)
