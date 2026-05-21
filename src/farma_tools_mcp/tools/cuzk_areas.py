"""ČÚZK chráněná území — large-area + Natura 2000 protected zones."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from ..http_utils import new_client

logger = logging.getLogger("farma_tools_mcp.tools.cuzk_areas")

ARCGIS_BASE = "https://ags.cuzk.cz/arcgis/rest/services/RUIAN/MapServer"


@dataclass(frozen=True)
class Layer:
    id: int
    label: str


LAYERS: tuple[Layer, ...] = (
    Layer(30, "Národní park (NP)"),
    Layer(40, "CHKO"),
    Layer(44, "Národní přírodní rezervace (NPR)"),
    Layer(48, "Národní přírodní památka (NPP)"),
    Layer(52, "Přírodní rezervace (PR)"),
    Layer(56, "Přírodní památka (PP)"),
    Layer(60, "Natura 2000 – Evropsky významná lokalita (EVL)"),
    Layer(62, "Natura 2000 – Ptačí oblast (PO)"),
)


async def _query(client: httpx.AsyncClient, layer: Layer, base_query: str) -> tuple[Layer, list[dict] | None, str | None]:
    url = f"{ARCGIS_BASE}/{layer.id}/query{base_query}"
    try:
        resp = await client.get(url)
        if resp.status_code >= 400:
            return layer, None, f"HTTP {resp.status_code}"
        data = resp.json()
        feats = [f.get("attributes") or {} for f in (data.get("features") or [])]
        return layer, feats, None
    except (httpx.HTTPError, ValueError) as e:
        return layer, None, str(e)


async def cuzk_areas(latitude: float, longitude: float) -> str:
    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError):
        return f"Chyba: neplatné souřadnice (lat={latitude}, lon={longitude})."

    if not (48.0 <= lat <= 51.5 and 12.0 <= lon <= 19.0):
        return f"Souřadnice ({lat}, {lon}) leží mimo ČR."

    logger.info("cuzk_areas lat=%s lon=%s", lat, lon)

    geometry = quote(json.dumps({"x": lon, "y": lat, "spatialReference": {"wkid": 4326}}, separators=(",", ":")))
    base_query = (
        f"?f=json&geometry={geometry}&geometryType=esriGeometryPoint&inSR=4326"
        f"&spatialRel=esriSpatialRelIntersects&outFields=nazev,kod,cislo,odkaz&returnGeometry=false"
    )

    async with new_client() as client:
        results = await asyncio.gather(*[_query(client, layer, base_query) for layer in LAYERS])

    hits: list[tuple[Layer, list[dict]]] = [(layer, feats) for layer, feats, err in results if feats]
    errors: list[tuple[Layer, str]] = [(layer, err) for layer, feats, err in results if err]

    lines = [f"**Kontrola chráněných území na {lat}, {lon}**", ""]
    if not hits:
        lines.append("✅ Souřadnice neleží v žádném velkoplošném ani Natura 2000 chráněném území.")
        lines.append("")
        lines.append("Pozor — neověřuje to lokální VKP, OP vodního zdroje, záplavové území ani územní plán obce.")
    else:
        lines.append("⚠️ Souřadnice leží v chráněném území:")
        for layer, feats in hits:
            for f in feats:
                parts = [layer.label, f.get("nazev") or "(bez názvu)"]
                if f.get("cislo"):
                    parts.append(f"č. {f['cislo']}")
                lines.append(f"- {' — '.join(parts)}")
                if f.get("odkaz"):
                    lines.append(f"  {f['odkaz']}")
        lines.append("")
        lines.append(
            "Důsledky: omezení stavební činnosti, hospodaření, oplocení, vstupu zvířat, návštěvnosti. "
            "Před investicí konzultovat s AOPK ČR / krajským úřadem / správou daného území."
        )

    if errors:
        lines.append("")
        joined = "; ".join(f"{layer.label} – {err}" for layer, err in errors)
        lines.append(f"(Některé vrstvy se nepovedlo zkontrolovat: {joined})")

    return "\n".join(lines)
