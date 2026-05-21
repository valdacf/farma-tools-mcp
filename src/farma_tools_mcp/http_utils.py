"""Shared httpx client and helpers for tool HTTP calls."""

from __future__ import annotations

import httpx

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
USER_AGENT = "farma-tools-mcp/0.1 (+https://github.com/cloudfield/farma-tools-mcp)"


def new_client(**overrides) -> httpx.AsyncClient:
    """Return a fresh AsyncClient with project defaults.

    Each tool call creates and disposes its own client so tests can inject
    mock transports per call via respx without sharing state.
    """
    kwargs = {
        "timeout": DEFAULT_TIMEOUT,
        "headers": {"User-Agent": USER_AGENT, "Accept": "application/json"},
        "follow_redirects": True,
    }
    kwargs.update(overrides)
    return httpx.AsyncClient(**kwargs)
