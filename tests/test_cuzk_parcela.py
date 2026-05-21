"""Tests for cuzk_parcela tool.

Real captured responses (Staré Město, Praha) live in tests/fixtures/cuzk_*.json.
"""

from __future__ import annotations

import re

import httpx

from farma_tools_mcp.tools.cuzk_parcela import ARCGIS_BASE, cuzk_parcela


def _parcela_url() -> re.Pattern:
    return re.compile(re.escape(f"{ARCGIS_BASE}/5/query") + r".*")


def _ku_url() -> re.Pattern:
    return re.compile(re.escape(f"{ARCGIS_BASE}/7/query") + r".*")


def _obec_url() -> re.Pattern:
    return re.compile(re.escape(f"{ARCGIS_BASE}/12/query") + r".*")


async def test_outside_cr():
    result = await cuzk_parcela(40.0, 14.0)
    assert "leží mimo ČR" in result


async def test_invalid_coords():
    result = await cuzk_parcela("nope", "also-nope")  # type: ignore[arg-type]
    assert result.startswith("Chyba: neplatné souřadnice")


async def test_real_prague_parcel(mock_http, fixture):
    """End-to-end with real captured responses for a Prague Old Town point."""
    mock_http.get(_parcela_url()).mock(return_value=httpx.Response(200, json=fixture("cuzk_parcela")))
    mock_http.get(_ku_url()).mock(return_value=httpx.Response(200, json=fixture("cuzk_ku")))
    mock_http.get(_obec_url()).mock(return_value=httpx.Response(200, json=fixture("cuzk_obec")))

    result = await cuzk_parcela(50.0875, 14.4214)

    # From the real fixtures: parcela 1090 v k.ú. Staré Město, Praha,
    # ostatní plocha (druh 14), 15869 m².
    assert "Parcela 1090" in result
    assert "Staré Město" in result
    assert "kód k.ú. 727024" in result
    assert "Obec: Praha" in result
    assert "Druh pozemku: ostatní plocha" in result
    assert "15869 m²" in result
    assert "Nahlížení do KN: https://nahlizenidokn.cuzk.cz/MapaIdentifikace.aspx?x=14.4214&y=50.0875" in result


async def test_no_parcela_found(mock_http):
    mock_http.get(_parcela_url()).mock(return_value=httpx.Response(200, json={"features": []}))

    result = await cuzk_parcela(50.3066, 14.4256)

    assert "nebyla v katastru nalezena žádná parcela" in result
    assert "https://nahlizenidokn.cuzk.cz" in result


async def test_arcgis_5xx_returns_fallback(mock_http):
    mock_http.get(_parcela_url()).mock(return_value=httpx.Response(503))

    result = await cuzk_parcela(50.3066, 14.4256)

    assert "Chyba při dotazu na ČÚZK" in result
    assert "Záložní odkaz: https://nahlizenidokn.cuzk.cz" in result


async def test_unknown_druh_code(mock_http):
    """Land-use code outside the curated dictionary renders raw kód."""
    mock_http.get(_parcela_url()).mock(
        return_value=httpx.Response(
            200,
            json={
                "features": [
                    {"attributes": {"cisloparcely": "1/1", "katastralniuzemi": 1, "vymeraparcely": 100, "druhpozemkukod": 99}}
                ]
            },
        )
    )
    mock_http.get(_ku_url()).mock(return_value=httpx.Response(200, json={"features": []}))

    result = await cuzk_parcela(50.0, 14.0)

    assert "Druh pozemku: kód 99" in result
    assert "k.ú. —" in result


async def test_ku_lookup_failure_tolerated(mock_http, fixture):
    """If k.ú. layer 7 fails, the parcela line still renders with '—'."""
    mock_http.get(_parcela_url()).mock(return_value=httpx.Response(200, json=fixture("cuzk_parcela")))
    mock_http.get(_ku_url()).mock(return_value=httpx.Response(500))

    result = await cuzk_parcela(50.0875, 14.4214)

    assert "Parcela 1090" in result
    assert "k.ú. —" in result
