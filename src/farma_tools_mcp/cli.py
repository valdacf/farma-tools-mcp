"""CLI entry-point for farma-tools-mcp."""

from __future__ import annotations

import argparse
import logging
import os
import sys

import uvicorn

from .auth import BearerAuthMiddleware
from .oauth import OAuthShim
from .server import build_server


def _configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level,
        format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
        stream=sys.stderr,
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="farma-tools-mcp", description="MCP server with Czech-domain tools.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "sse", "streamable-http"),
        default=os.environ.get("MCP_TRANSPORT", "streamable-http"),
        help="Transport. 'stdio' for local Claude Desktop, 'streamable-http' (default) or 'sse' for remote MCP.",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("MCP_HOST", "0.0.0.0"),
        help="Bind host for HTTP transports (default: 0.0.0.0).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("MCP_PORT", "14000")),
        help="Bind port for HTTP transports (default: 14000).",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("LOG_LEVEL", "INFO"),
        help="Python logging level (default: INFO).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _configure_logging(args.log_level.upper())

    mcp = build_server(host=args.host, port=args.port)

    if args.transport == "stdio":
        mcp.run(transport="stdio")
        return 0

    token = os.environ.get("MCP_BEARER_TOKEN", "").strip()
    if not token:
        sys.stderr.write(
            "FATAL: MCP_BEARER_TOKEN env var must be set for HTTP transports. "
            "Generate one with: openssl rand -hex 32\n"
        )
        return 2

    oauth_id = os.environ.get("OAUTH_CLIENT_ID", "").strip()
    oauth_secret = os.environ.get("OAUTH_CLIENT_SECRET", "").strip()
    if bool(oauth_id) != bool(oauth_secret):
        sys.stderr.write(
            "FATAL: OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET must be set together (or both unset).\n"
        )
        return 2

    if args.transport == "sse":
        app = mcp.sse_app()
    else:  # streamable-http
        app = mcp.streamable_http_app()

    exempt_paths: set[str] = set()
    if oauth_id and oauth_secret:
        shim = OAuthShim(client_id=oauth_id, client_secret=oauth_secret, access_token=token)
        for route in shim.routes():
            app.router.routes.append(route)
        exempt_paths = shim.paths()

    app.add_middleware(BearerAuthMiddleware, expected_token=token, exempt_paths=exempt_paths)

    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level.lower())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
