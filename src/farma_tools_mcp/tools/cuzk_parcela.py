"""ČÚZK katastr — parcel lookup by WGS84 coordinates."""

from __future__ import annotations

import json
import logging
from urllib.parse import quote

import httpx

from ..http_utils import new_client

logger = logging.getLogger("farma_tools_mcp.tools.cuzk_parcela")

ARCGIS_BASE = "https://ags.cuzk.cz/arcgis/rest/services/RUIAN/MapServer"

DRUH_POZEMKU = {
    2: "orná půda",
    3: "chmelnice",
    4: "vinice",
    5: "zahrada",
    6: "ovocný sad",
    7: "trvalý travní porost",
    10: "lesní pozemek",
    11: "vodní plocha",
    13: "zastavěná plocha a nádvoří",
    14: "ostatní plocha",
}


def _nahlizeni_link(lat: float, lon: float) -> str:
    return f"https://nahlizenidokn.cuzk.cz/MapaIdentifikace.aspx?x={lon}&y={lat}"


async def _query_layer(client: httpx.AsyncClient, url: str) -> dict:
    resp = await client.get(url)
    if resp.status_code >= 400:
        raise httpx.HTTPStatusError(f"HTTP {resp.status_code}", request=resp.request, response=resp)
    return resp.json()


async def cuzk_parcela(latitude: float, longitude: float) -> str:
    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError):
        return f"Chyba: neplatné souřadnice (lat={latitude}, lon={longitude})."

    if not (48.0 <= lat <= 51.5 and 12.0 <= lon <= 19.0):
        return f"Souřadnice ({lat}, {lon}) leží mimo ČR."

    logger.info("cuzk_parcela lat=%s lon=%s", lat, lon)

    geometry = quote(json.dumps({"x": lon, "y": lat, "spatialReference": {"wkid": 4326}}, separators=(",", ":")))
    base_query = (
        f"?f=json&geometry={geometry}&geometryType=esriGeometryPoint&inSR=4326"
        f"&spatialRel=esriSpatialRelIntersects&outFields=*&returnGeometry=false"
    )

    try:
        async with new_client() as client:
            p_data = await _query_layer(client, f"{ARCGIS_BASE}/5/query{base_query}")

            features = p_data.get("features") or []
            if not features:
                return (
                    f"Na souřadnicích ({lat}, {lon}) nebyla v katastru nalezena žádná parcela.\n"
                    f"Otevři ručně: {_nahlizeni_link(lat, lon)}"
                )

            p = features[0].get("attributes") or {}

            ku_nazev = "—"
            obec_kod = None
            ku_kod = p.get("katastralniuzemi")
            if ku_kod:
                try:
                    ku_url = (
                        f"{ARCGIS_BASE}/7/query?f=json&where=kod%3D{ku_kod}"
                        f"&outFields=nazev,obec&returnGeometry=false"
                    )
                    ku_data = await _query_layer(client, ku_url)
                    ku_feats = ku_data.get("features") or []
                    if ku_feats:
                        attrs = ku_feats[0].get("attributes") or {}
                        ku_nazev = attrs.get("nazev") or "—"
                        obec_kod = attrs.get("obec")
                except (httpx.HTTPError, ValueError) as e:
                    logger.warning("cuzk_parcela ku lookup failed: %s", e)

            obec_nazev = "—"
            if obec_kod:
                try:
                    o_url = (
                        f"{ARCGIS_BASE}/12/query?f=json&where=kod%3D{obec_kod}"
                        f"&outFields=nazev&returnGeometry=false"
                    )
                    o_data = await _query_layer(client, o_url)
                    o_feats = o_data.get("features") or []
                    if o_feats:
                        obec_nazev = (o_feats[0].get("attributes") or {}).get("nazev") or "—"
                except (httpx.HTTPError, ValueError) as e:
                    logger.warning("cuzk_parcela obec lookup failed: %s", e)
    except (httpx.HTTPError, ValueError) as e:
        return (
            f"Chyba při dotazu na ČÚZK: {e}\n"
            f"Záložní odkaz: {_nahlizeni_link(lat, lon)}"
        )

    druh_kod = p.get("druhpozemkukod")
    druh = DRUH_POZEMKU.get(druh_kod, f"kód {druh_kod}") if druh_kod is not None else "—"

    vymera = p.get("vymeraparcely")
    if vymera is not None:
        vymera_str = f"{round(vymera)} m² ({vymera / 10000:.2f} ha)"
    else:
        vymera_str = "—"

    lines = [
        f"**Parcela {p.get('cisloparcely') or '?'} v k.ú. {ku_nazev}** (kód k.ú. {ku_kod})",
        f"Obec: {obec_nazev}",
        f"Druh pozemku: {druh}",
        f"Výměra: {vymera_str}",
    ]
    if p.get("zpusobyvyuzitipozemku"):
        lines.append(f"Způsob využití (kód): {p['zpusobyvyuzitipozemku']}")
    lines.append("")
    lines.append(f"Nahlížení do KN: {_nahlizeni_link(lat, lon)}")
    return "\n".join(lines)
