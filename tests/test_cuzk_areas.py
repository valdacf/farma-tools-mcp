"""Tests for cuzk_areas tool.

Real captured responses from a point in CHKO Křivoklátsko (49.9684, 13.9869)
live in tests/fixtures/cuzk_area_layer*.json — exactly one layer (CHKO, id 40)
returns a hit. They make the "hits in CHKO" test reflect real upstream output.
"""

from __future__ import annotations

import re

import httpx

from farma_tools_mcp.tools.cuzk_areas import ARCGIS_BASE, LAYERS, cuzk_areas


def _layer_url(layer_id: int) -> re.Pattern:
    return re.compile(re.escape(f"{ARCGIS_BASE}/{layer_id}/query") + r".*")


async def test_outside_cr():
    result = await cuzk_areas(40.0, 14.0)
    assert "leží mimo ČR" in result


async def test_no_hits(mock_http):
    """All 8 layers return empty → friendly green-check message."""
    for layer in LAYERS:
        mock_http.get(_layer_url(layer.id)).mock(return_value=httpx.Response(200, json={"features": []}))

    result = await cuzk_areas(50.0, 14.0)

    assert "✅ Souřadnice neleží v žádném velkoplošném" in result
    assert "VKP, OP vodního zdroje" in result


async def test_real_krivoklatsko_point(mock_http, fixture):
    """End-to-end on a real CHKO Křivoklátsko point (49.9684, 13.9869)."""
    for layer in LAYERS:
        mock_http.get(_layer_url(layer.id)).mock(
            return_value=httpx.Response(200, json=fixture(f"cuzk_area_layer{layer.id}"))
        )

    result = await cuzk_areas(49.9684, 13.9869)

    assert "⚠️ Souřadnice leží v chráněném území" in result
    assert "CHKO — Křivoklátsko" in result
    assert "č. 24" in result
    assert "drusop.aopk.gov.cz" in result
    assert "AOPK ČR" in result


async def test_partial_layer_failure_is_tolerated(mock_http):
    """One layer 5xx → that layer reported as error, rest of result intact."""
    for layer in LAYERS:
        if layer.id == 60:
            mock_http.get(_layer_url(layer.id)).mock(return_value=httpx.Response(500))
        else:
            mock_http.get(_layer_url(layer.id)).mock(return_value=httpx.Response(200, json={"features": []}))

    result = await cuzk_areas(50.0, 14.0)

    assert "✅" in result  # no hits → green check still present
    assert "Některé vrstvy se nepovedlo zkontrolovat" in result
    assert "Natura 2000 – Evropsky významná lokalita (EVL)" in result
    assert "HTTP 500" in result


async def test_multiple_hits_same_layer(mock_http):
    """A layer with several features renders each on its own bullet line."""
    mock_http.get(_layer_url(56)).mock(
        return_value=httpx.Response(
            200,
            json={
                "features": [
                    {"attributes": {"nazev": "Lokality A", "cislo": 1, "kod": 1}},
                    {"attributes": {"nazev": None, "cislo": None, "kod": 2}},
                ]
            },
        )
    )
    for layer in LAYERS:
        if layer.id != 56:
            mock_http.get(_layer_url(layer.id)).mock(return_value=httpx.Response(200, json={"features": []}))

    result = await cuzk_areas(50.0, 14.0)

    assert "Přírodní památka (PP) — Lokality A — č. 1" in result
    assert "Přírodní památka (PP) — (bez názvu)" in result
