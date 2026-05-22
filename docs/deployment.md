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
- For Claude.ai cowork, also an OAuth client_id / client_secret pair (since
  cowork's UI requires OAuth, not raw Bearer):
  ```bash
  openssl rand -hex 16   # OAUTH_CLIENT_ID
  openssl rand -hex 32   # OAUTH_CLIENT_SECRET
  ```

## 1. Build the image

```bash
cd /path/to/farma-tools-mcp
docker build -t farma-tools-mcp:latest .
```

Multi-stage `python:3.12-slim`, runs as non-root `uid 10001`, exposes `14000`,
HEALTHCHECK probes the TCP listener (the auth-protected `/mcp` endpoint can't
be probed without a token).

## 2. Run standalone (smoke test)

```bash
export MCP_BEARER_TOKEN=$(openssl rand -hex 32)
docker run --rm -p 14000:14000 \
  -e MCP_BEARER_TOKEN \
  farma-tools-mcp:latest

# In another shell:
curl -i http://localhost:14000/mcp                                         # 401
curl -i -H "Authorization: Bearer $MCP_BEARER_TOKEN" \
  http://localhost:14000/mcp                                               # MCP responds
```

A 401 without the header and a non-401 response with it = server is healthy.

To also enable the OAuth shim for cowork:

```bash
export OAUTH_CLIENT_ID=$(openssl rand -hex 16)
export OAUTH_CLIENT_SECRET=$(openssl rand -hex 32)

docker run --rm -p 14000:14000 \
  -e MCP_BEARER_TOKEN -e OAUTH_CLIENT_ID -e OAUTH_CLIENT_SECRET \
  farma-tools-mcp:latest

# Discovery endpoint should not require auth:
curl -s http://localhost:14000/.well-known/oauth-authorization-server | jq .
```

## 3. Merge into an existing compose stack

The repo ships [docker-compose.snippet.yml](../docker-compose.snippet.yml) —
copy the `farma-tools-mcp:` block into your top-level `docker-compose.yml`
under `services:`.

```bash
# In the directory holding your live docker-compose.yml:
{
  echo "MCP_BEARER_TOKEN=$(openssl rand -hex 32)"
  echo "OAUTH_CLIENT_ID=$(openssl rand -hex 16)"
  echo "OAUTH_CLIENT_SECRET=$(openssl rand -hex 32)"
} >> .env
docker compose up -d farma-tools-mcp
docker compose logs -f farma-tools-mcp
```

Rename the `ai-net` network in the snippet if your stack uses a different
shared network. Uncomment the `OAUTH_*` lines in the snippet only after
populating `.env`.

## 4. Expose via the reverse proxy

Claude.ai cowork needs a public HTTPS URL. Add a vhost that proxies to
`http://farma-tools-mcp:14000` (compose-internal) or `http://<host>:14000`
(standalone). The Streamable HTTP transport streams responses, so disable
proxy buffering — same as for SSE.

### Caddy example

```caddyfile
farma-tools.example.com {
    reverse_proxy farma-tools-mcp:14000 {
        # MCP streamable-http streams chunks; disable buffering
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
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header Connection "";
        proxy_buffering off;       # critical for streaming responses
        proxy_read_timeout 1h;
        chunked_transfer_encoding off;
    }
}
```

The `X-Forwarded-Proto` / `X-Forwarded-Host` headers are needed so that the
OAuth discovery documents advertise the public HTTPS URL rather than the
internal `http://farma-tools-mcp:14000`.

**Streaming note:** any buffering / response cache in front of the server
breaks long-lived streams. Disable it on `/mcp` (and `/sse` if you're using
the SSE transport).

## 5. Connect Claude.ai cowork

In cowork: *Settings → Integrations → Add MCP server*

| Field                              | Value                                                  |
| ---------------------------------- | ------------------------------------------------------ |
| Name                               | `farma-tools`                                          |
| URL                                | `https://farma-tools.example.com/mcp`                  |
| Client ID *(Advanced settings)*    | value of `OAUTH_CLIENT_ID`                             |
| Client Secret *(Advanced settings)*| value of `OAUTH_CLIENT_SECRET`                         |

Cowork's UI doesn't have a raw-Bearer field — the OAuth shim is the path. On
save, cowork will:

1. fetch `/.well-known/oauth-protected-resource` and `/.well-known/oauth-authorization-server`,
2. redirect through `/authorize` (auto-approved),
3. exchange the code at `/token` using your client_id/secret,
4. use the returned bearer token on every subsequent `/mcp` call.

After saving, cowork should list the 5 tools (`ares_lookup`, `cuzk_parcela`,
`cuzk_areas`, `open_meteo`, `osm_nearby`). If listing fails:

1. Check the URL ends in `/mcp` (the streamable-http transport endpoint).
2. Verify Client ID / Secret in Advanced settings have no trailing whitespace
   — paste from `cat .env`, not from a browser tab.
3. Confirm the proxy forwards `X-Forwarded-Proto`/`Host` so discovery returns
   the HTTPS URL.
4. `docker compose logs -f farma-tools-mcp` should show `oauth_token_bad_creds`
   if the secrets don't match — that points at the cowork-side fields.

## Rotating tokens

```bash
# On the host:
sed -i "s/^MCP_BEARER_TOKEN=.*/MCP_BEARER_TOKEN=$(openssl rand -hex 32)/" .env
sed -i "s/^OAUTH_CLIENT_SECRET=.*/OAUTH_CLIENT_SECRET=$(openssl rand -hex 32)/" .env
docker compose up -d farma-tools-mcp     # picks up the new env
```

Then re-paste the new Client Secret into cowork's Advanced settings (cowork
will renegotiate the flow). Old tokens are rejected on the next request.

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

Remove `MCP_BEARER_TOKEN`, `OAUTH_CLIENT_ID`, and `OAUTH_CLIENT_SECRET` from
`.env` when the integration is no longer used — these three are the only
credentials.
