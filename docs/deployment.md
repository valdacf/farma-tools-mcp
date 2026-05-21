# Deployment

Step-by-step deploy of `farma-tools-mcp` as a remote MCP server reachable by
Claude.ai cowork. For local stdio (Claude Desktop) follow the
[README quick start](../README.md#quick-start-local-stdio) instead.

## Prerequisites

- Docker engine (≥ 20.10) on the host
- A reverse proxy in front of the host that can terminate TLS — Caddy, Traefik,
  nginx, or your existing ingress. Claude.ai cowork **only accepts HTTPS** URLs.
- A bearer token (32 bytes hex is plenty):
  ```bash
  openssl rand -hex 32
  ```

## 1. Build the image

```bash
cd /path/to/farma-tools-mcp
docker build -t farma-tools-mcp:latest .
```

Multi-stage `python:3.12-slim`, runs as non-root `uid 10001`, has a HEALTHCHECK
on `/sse`, exposes `14000`.

## 2. Run standalone (smoke test)

```bash
export MCP_BEARER_TOKEN=$(openssl rand -hex 32)
docker run --rm -p 14000:14000 \
  -e MCP_BEARER_TOKEN \
  farma-tools-mcp:latest

# In another shell:
curl -i http://localhost:14000/sse                                         # 401
curl -i -N -H "Authorization: Bearer $MCP_BEARER_TOKEN" \
  http://localhost:14000/sse                                               # SSE stream
```

A 401 without the header and an SSE stream with it = server is healthy.

## 3. Merge into an existing compose stack

The repo ships [docker-compose.snippet.yml](../docker-compose.snippet.yml) —
copy the `farma-tools-mcp:` block into your top-level `docker-compose.yml`
under `services:`.

```bash
# In the directory holding your live docker-compose.yml:
echo "MCP_BEARER_TOKEN=$(openssl rand -hex 32)" >> .env
docker compose up -d farma-tools-mcp
docker compose logs -f farma-tools-mcp
```

Rename the `ai-net` network in the snippet if your stack uses a different
shared network.

## 4. Expose via the reverse proxy

Claude.ai cowork needs a public HTTPS URL. Add a vhost that proxies to
`http://farma-tools-mcp:14000` (compose-internal) or `http://<host>:14000`
(standalone).

### Caddy example

```caddyfile
farma-tools.example.com {
    reverse_proxy farma-tools-mcp:14000 {
        # SSE needs streaming; disable buffering / flush regularly
        flush_interval -1
    }
}
```

### nginx example

```nginx
server {
    listen 443 ssl http2;
    server_name farma-tools.example.com;

    # …your TLS config…

    location / {
        proxy_pass http://127.0.0.1:14000;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;       # critical for SSE
        proxy_read_timeout 1h;
        chunked_transfer_encoding off;
    }
}
```

**SSE-specific note:** any buffering / response cache in front of the server
will break the long-lived event stream. Disable it on the `/sse` path.

## 5. Connect Claude.ai cowork

In cowork: *Settings → Integrations → Add MCP server*

| Field   | Value                                                  |
| ------- | ------------------------------------------------------ |
| Name    | `farma-tools`                                          |
| URL     | `https://farma-tools.example.com/sse`                  |
| Auth    | Bearer — paste the value of `MCP_BEARER_TOKEN`         |

After saving, cowork should list the 5 tools (`ares_lookup`, `cuzk_parcela`,
`cuzk_areas`, `open_meteo`, `osm_nearby`). If listing fails:

1. Check the URL ends in `/sse` (this is the SSE transport endpoint).
2. Verify the token has no trailing whitespace — paste from `cat .env`, not
   from a browser tab.
3. Check the proxy is not buffering — `curl -i -N` from outside should keep
   the connection open and write events as they arrive.

## Rotating the token

```bash
# On the host:
sed -i "s/^MCP_BEARER_TOKEN=.*/MCP_BEARER_TOKEN=$(openssl rand -hex 32)/" .env
docker compose up -d farma-tools-mcp     # picks up the new env
```

Then paste the new token into cowork. Old token returns `401` immediately.

## Upgrading

```bash
cd /path/to/farma-tools-mcp
git pull
docker build -t farma-tools-mcp:latest .
docker compose up -d farma-tools-mcp
```

The image build is cache-friendly: only `uv sync` and the source layer change
between most upgrades.

## Logs & debugging

- `docker compose logs -f farma-tools-mcp` — Starlette access log + auth events
- Set `LOG_LEVEL=DEBUG` in the env to see every tool invocation and the
  outbound HTTP requests
- HEALTHCHECK status: `docker inspect --format '{{.State.Health.Status}}' farma-tools-mcp`

## Removal

```bash
docker compose down farma-tools-mcp
docker image rm farma-tools-mcp:latest
```

Remove `MCP_BEARER_TOKEN` from `.env` when the integration is no longer used —
the token is the only credential.
