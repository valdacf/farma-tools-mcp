"""OpenStreetMap nearby POIs via Overpass with mirror fallback."""

from __future__ import annotations

import logging
import math
from urllib.parse import quote

import httpx

from ..http_utils import new_client

logger = logging.getLogger("farma_tools_mcp.tools.osm_nearby")

CATEGORY_MAP: dict[str, list[str]] = {
    "farm": ['["landuse"="farmyard"]', '["place"="farm"]', '["building"="farm"]', '["building"="barn"]'],
    "restaurant": ['["amenity"="restaurant"]', '["amenity"="cafe"]', '["amenity"="pub"]', '["amenity"="fast_food"]'],
    "accommodation": [
        '["tourism"="hotel"]', '["tourism"="guest_house"]', '["tourism"="hostel"]',
        '["tourism"="apartment"]', '["tourism"="camp_site"]', '["tourism"="chalet"]',
    ],
    "tourism": ['["tourism"~"attraction|museum|viewpoint|theme_park|zoo|picnic_site"]'],
    "shop": ['["shop"]'],
    "water": ['["natural"="water"]', '["waterway"="river"]', '["waterway"="stream"]', '["natural"="spring"]'],
    "road": ['["highway"~"motorway|trunk|primary|secondary|tertiary"]'],
    "school": ['["amenity"~"school|kindergarten"]'],
    "zoo": ['["tourism"="zoo"]', '["amenity"="animal_shelter"]', '["leisure"="park"]'],
}

OVERPASS_MIRRORS = (
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)

POI_TAG_KEYS = ("amenity", "tourism", "shop", "landuse", "building", "natural", "waterway", "highway", "place", "leisure")


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    s = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(s))


def _build_query(filters: list[str], radius: int, lat: float, lon: float) -> str:
    parts = []
    for f in filters:
        parts.append(f"  node{f}(around:{radius},{lat},{lon});")
        parts.append(f"  way{f}(around:{radius},{lat},{lon});")
        parts.append(f"  relation{f}(around:{radius},{lat},{lon});")
    return "[out:json][timeout:25];\n(\n" + "\n".join(parts) + "\n);\nout center tags 80;"


async def _post_overpass(query: str) -> tuple[httpx.Response | None, str]:
    last_err = ""
    body = "data=" + quote(query)
    headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
    async with new_client(headers=headers, timeout=httpx.Timeout(40.0, connect=10.0)) as client:
        for mirror in OVERPASS_MIRRORS:
            try:
                resp = await client.post(mirror, content=body)
                if resp.is_success:
                    return resp, ""
                last_err = f"{mirror}: HTTP {resp.status_code}"
            except httpx.HTTPError as e:
                last_err = f"{mirror}: {e}"
    return None, last_err


async def osm_nearby(latitude: float, longitude: float, radius_m: int = 2000, category: str = "farm") -> str:
    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError):
        return "Chyba: neplatné souřadnice."

    try:
        radius = int(radius_m) if radius_m is not None else 2000
    except (TypeError, ValueError):
        radius = 2000
    radius = max(100, min(radius, 20_000))

    cat = str(category or "").strip()
    if cat in CATEGORY_MAP:
        filters = CATEGORY_MAP[cat]
    elif "=" in cat:
        k, _, v = cat.partition("=")
        filters = [f'["{k}"="{v}"]']
    else:
        known = ", ".join(CATEGORY_MAP.keys())
        return f"Neznámá kategorie '{category}'. Použij: {known} nebo vlastní tag 'key=value'."

    query = _build_query(filters, radius, lat, lon)
    logger.info("osm_nearby cat=%s radius=%s lat=%s lon=%s", cat, radius, lat, lon)

    resp, last_err = await _post_overpass(query)
    if resp is None:
        return f"Všechny Overpass mirrors selhaly. Poslední: {last_err}"

    try:
        data = resp.json()
    except ValueError as e:
        return f"Chyba při parsování Overpass odpovědi: {e}"

    elements = data.get("elements") or []
    if not elements:
        return f"V okolí {radius}m od ({lat}, {lon}) nebylo nic z kategorie '{cat}' nalezeno."

    results = []
    for e in elements:
        elat = e.get("lat") or (e.get("center") or {}).get("lat")
        elon = e.get("lon") or (e.get("center") or {}).get("lon")
        if elat is None or elon is None:
            continue
        try:
            dist = _haversine(lat, lon, float(elat), float(elon))
        except (TypeError, ValueError):
            continue
        tags = e.get("tags") or {}
        name = tags.get("name") or tags.get("name:cs") or "(bez názvu)"
        type_pairs = [f"{k}={v}" for k, v in tags.items() if k in POI_TAG_KEYS]
        results.append({
            "name": name,
            "type": ", ".join(type_pairs),
            "dist": dist,
            "lat": float(elat),
            "lon": float(elon),
        })

    results.sort(key=lambda r: r["dist"])
    results = results[:30]

    if not results:
        return f"V okolí {radius}m od ({lat}, {lon}) nebylo nic z kategorie '{cat}' nalezeno."

    lines = [f"**{len(results)} výsledků pro '{cat}' v okolí {radius}m od ({lat}, {lon})**", ""]
    for r in results:
        lines.append(
            f"- {round(r['dist'])}m | {r['name']} [{r['type']}] ({r['lat']:.5f}, {r['lon']:.5f})"
        )
    return "\n".join(lines)
