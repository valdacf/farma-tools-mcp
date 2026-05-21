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

## Quick start (remote HTTP/SSE, Docker)

```bash
# Generate a token (32 bytes hex)
export MCP_BEARER_TOKEN="$(openssl rand -hex 32)"

# Build & run
docker build -t farma-tools-mcp .
docker run --rm -p 14000:14000 -e MCP_BEARER_TOKEN farma-tools-mcp
```

The server now listens on `http://localhost:14000/sse` (SSE transport).

Connect it to **Claude.ai cowork** under *Settings → Integrations → Add MCP server*:

| Field   | Value                                                                |
| ------- | -------------------------------------------------------------------- |
| Name    | `farma-tools`                                                        |
| URL     | `https://your-host.example.com/sse` (use HTTPS in production)        |
| Auth    | Bearer token — paste the value from `MCP_BEARER_TOKEN`               |

Verify with `curl`:

```bash
# Missing/wrong token → 401
curl -i http://localhost:14000/sse

# Correct token → SSE stream opens
curl -i -N -H "Authorization: Bearer $MCP_BEARER_TOKEN" http://localhost:14000/sse
```

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
`MCP_TRANSPORT`, `MCP_HOST`, `MCP_PORT`, `MCP_BEARER_TOKEN`, `LOG_LEVEL`.

For HTTP transports, `MCP_BEARER_TOKEN` is **required** — the process exits with
status 2 at startup if it is missing.

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
| Claude cowork keeps showing 401                          | Bearer token mismatch. Re-copy from `.env` — no trailing newline / spaces.          |
| Tool returns `Všechny Overpass mirrors selhaly`          | All three OSM mirrors are temporarily down. Retry; consider hosting your own.       |
| `Open-Meteo vrátil HTTP 503`                             | Open-Meteo rate-limit — back off and retry; no API key needed but quotas exist.     |
| `Chyba: leží mimo ČR`                                    | Coordinates outside the ČR bounding box (lat 48–51.5, lon 12–19). All ČÚZK tools enforce this. |
| Stdio mode "hangs"                                       | Expected — stdio servers wait for newline-delimited JSON-RPC on stdin from the client. |

## Notes

- **No caching, no rate-limiting, no persistent state.** Stateless tool calls only.
- **Modern transports.** `sse` is the default for backwards compatibility; you can
  also run with `--transport streamable-http` for the newer MCP transport.
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
