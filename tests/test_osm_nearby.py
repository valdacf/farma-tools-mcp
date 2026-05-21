"""Tests for osm_nearby tool.

Real captured Overpass response (Prague centre, 500m radius restaurants) lives
in tests/fixtures/overpass_restaurants.json.
"""

from __future__ import annotations

import httpx

from farma_tools_mcp.tools.osm_nearby import OVERPASS_MIRRORS, osm_nearby


async def test_invalid_coords():
    result = await osm_nearby("nope", 14.0)  # type: ignore[arg-type]
    assert result == "Chyba: neplatné souřadnice."


async def test_unknown_category():
    result = await osm_nearby(50.0, 14.0, category="totally-bogus")
    assert "Neznámá kategorie 'totally-bogus'" in result
    assert "farm" in result


async def test_real_prague_restaurants(mock_http, fixture):
    """Real Overpass response — Prague centre, 500m, restaurants."""
    mock_http.post(OVERPASS_MIRRORS[0]).mock(return_value=httpx.Response(200, json=fixture("overpass_restaurants")))

    result = await osm_nearby(50.0875, 14.4214, radius_m=500, category="restaurant")

    # Heading
    assert "**" in result
    assert "v okolí 500m od (50.0875, 14.4214)" in result
    # Items must be sorted ascending by distance
    import re
    dists = [int(m.group(1)) for m in re.finditer(r"^- (\d+)m \|", result, flags=re.MULTILINE)]
    assert dists == sorted(dists)
    # At least one result has an amenity tag in the type column
    assert "amenity=restaurant" in result or "amenity=cafe" in result


async def test_happy_path_farm_synthetic(mock_http):
    """Minimal synthetic case — easier to assert on exact text."""
    payload = {
        "elements": [
            {"type": "node", "lat": 50.001, "lon": 14.001, "tags": {"place": "farm", "name": "Farma Šťastný kohout"}},
            {"type": "way", "center": {"lat": 50.01, "lon": 14.01}, "tags": {"building": "barn"}},
        ]
    }
    mock_http.post(OVERPASS_MIRRORS[0]).mock(return_value=httpx.Response(200, json=payload))

    result = await osm_nearby(50.0, 14.0, radius_m=5000, category="farm")

    assert "**2 výsledků pro 'farm' v okolí 5000m od (50.0, 14.0)**" in result
    assert "Farma Šťastný kohout" in result
    assert "[place=farm]" in result
    assert "(bez názvu)" in result
    assert "[building=barn]" in result


async def test_first_mirror_fails_falls_back_to_second(mock_http):
    mock_http.post(OVERPASS_MIRRORS[0]).mock(return_value=httpx.Response(406))
    mock_http.post(OVERPASS_MIRRORS[1]).mock(
        return_value=httpx.Response(
            200,
            json={"elements": [{"type": "node", "lat": 50.0001, "lon": 14.0001, "tags": {"shop": "bakery", "name": "Pekárna"}}]},
        )
    )

    result = await osm_nearby(50.0, 14.0, category="shop")

    assert "Pekárna" in result
    assert "[shop=bakery]" in result


async def test_all_mirrors_fail(mock_http):
    for mirror in OVERPASS_MIRRORS:
        mock_http.post(mirror).mock(return_value=httpx.Response(429))

    result = await osm_nearby(50.0, 14.0)

    assert "Všechny Overpass mirrors selhaly" in result
    assert "HTTP 429" in result


async def test_empty_result(mock_http):
    mock_http.post(OVERPASS_MIRRORS[0]).mock(return_value=httpx.Response(200, json={"elements": []}))
    result = await osm_nearby(50.0, 14.0, radius_m=300, category="zoo")
    assert "nebylo nic z kategorie 'zoo' nalezeno" in result


async def test_custom_tag_kv(mock_http):
    mock_http.post(OVERPASS_MIRRORS[0]).mock(
        return_value=httpx.Response(
            200,
            json={"elements": [{"type": "node", "lat": 50.0, "lon": 14.0, "tags": {"craft": "blacksmith", "name": "Kovárna"}}]},
        )
    )
    result = await osm_nearby(50.0, 14.0, category="craft=blacksmith")
    assert "Kovárna" in result


async def test_radius_clamping(mock_http):
    route = mock_http.post(OVERPASS_MIRRORS[0]).mock(return_value=httpx.Response(200, json={"elements": []}))
    await osm_nearby(50.0, 14.0, radius_m=999999, category="farm")
    sent_body = route.calls.last.request.content.decode()
    assert "around%3A20000" in sent_body
