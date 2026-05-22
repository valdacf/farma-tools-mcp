"""FastMCP server setup — registers the 5 farma tools.

The same `build_server()` is used for stdio (Claude Desktop) and HTTP
transports — streamable-http (default, endpoint `/mcp`) or SSE (`/sse`).
"""

from __future__ import annotations

import logging
from typing import Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .tools.ares import ares_lookup as _ares_lookup
from .tools.cuzk_areas import cuzk_areas as _cuzk_areas
from .tools.cuzk_parcela import cuzk_parcela as _cuzk_parcela
from .tools.open_meteo import open_meteo as _open_meteo
from .tools.osm_nearby import osm_nearby as _osm_nearby

logger = logging.getLogger("farma_tools_mcp.server")


SERVER_INSTRUCTIONS = (
    "Sada nástrojů pro hobby-farma brainstorm v ČR: ARES (firmy podle IČO), "
    "ČÚZK katastr (parcela na GPS), ČÚZK chráněná území (CHKO, NP, NPR, NPP, Natura 2000), "
    "Open-Meteo (předpověď nebo 10letý klimatický průměr) a OpenStreetMap okolí (farmy, "
    "ubytování, silnice, voda atd.). Volej je při ověřování pozemků, dodavatelů, klimatu a "
    "infrastruktury kolem konkrétního místa v České republice."
)


def build_server(host: str = "0.0.0.0", port: int = 14000) -> FastMCP:
    mcp = FastMCP(
        name="farma-tools",
        instructions=SERVER_INSTRUCTIONS,
        host=host,
        port=port,
        log_level="INFO",
    )

    @mcp.tool(
        name="ares_lookup",
        description=(
            "Vyhledá v ARES (Administrativní registr ekonomických subjektů ČR) firmu podle IČO. "
            "Vrátí strukturovaný výpis: název, sídlo, právní forma, NACE, registrace, doručovací adresa. "
            "Použij při ověřování konkurence, dodavatelů, partnerů, kupců pozemků."
        ),
    )
    async def ares_lookup(
        ico: str = Field(description="IČO firmy. 8 číslic; mezery a úvodní nuly se odstraní/doplní."),
    ) -> str:
        return await _ares_lookup(ico)

    @mcp.tool(
        name="cuzk_parcela",
        description=(
            "Vrátí katastrální informace o parcele na zadaných WGS84 souřadnicích v ČR — číslo parcely, "
            "katastrální území, obec, druh pozemku, výměra. Použij pro lokalizaci pozemku a ověření jeho "
            "charakteru před nabídkou nebo plánováním využití."
        ),
    )
    async def cuzk_parcela(
        latitude: float = Field(description="Zeměpisná šířka WGS84 (48.0–51.5 pro ČR)."),
        longitude: float = Field(description="Zeměpisná délka WGS84 (12.0–19.0 pro ČR)."),
    ) -> str:
        return await _cuzk_parcela(latitude, longitude)

    @mcp.tool(
        name="cuzk_areas",
        description=(
            "Zjistí, zda dané WGS84 souřadnice leží v chráněném území ČR — Národní park, CHKO, "
            "Národní přírodní rezervace/památka, přírodní rezervace/památka, Natura 2000 (EVL/PO). "
            "Volej před plánováním stavby, hospodaření nebo turistických aktivit — chráněné území "
            "zásadně omezuje co se smí. Neověřuje VKP, OP vodního zdroje, záplavové území ani územní plán."
        ),
    )
    async def cuzk_areas(
        latitude: float = Field(description="Zeměpisná šířka WGS84 (48.0–51.5)."),
        longitude: float = Field(description="Zeměpisná délka WGS84 (12.0–19.0)."),
    ) -> str:
        return await _cuzk_areas(latitude, longitude)

    @mcp.tool(
        name="open_meteo",
        description=(
            "Vrátí buď krátkodobou předpověď počasí (1–14 dní, denní teploty/srážky/vítr) nebo "
            "10letý klimatický průměr (ERA5: měsíční Tmax/Tmin, srážky, počet mrazových dnů) pro "
            "GPS souřadnice. Použij pro plánování pastvy, ustájení, sezónnosti, mrazových rizik, "
            "srážkového úhrnu."
        ),
    )
    async def open_meteo(
        latitude: float = Field(description="Zeměpisná šířka WGS84."),
        longitude: float = Field(description="Zeměpisná délka WGS84."),
        mode: Literal["forecast", "climate"] = Field(
            default="forecast",
            description="'forecast' = krátkodobá předpověď; 'climate' = 10letý průměr (ERA5).",
        ),
        days: int = Field(
            default=7,
            description="Počet dní pro forecast mode, 1–14. Ignoruje se v climate módu.",
        ),
    ) -> str:
        return await _open_meteo(latitude, longitude, mode, days)

    @mcp.tool(
        name="osm_nearby",
        description=(
            "Najde objekty v okolí GPS souřadnic v OpenStreetMap — silnice, vodoteče, farmy, "
            "restaurace, ubytování, atrakce, školy, obchody. Hodí se na analýzu dostupnosti, "
            "konkurence a infrastruktury pro návštěvníky farmy. Kategorie: farm, restaurant, "
            "accommodation, tourism, shop, water, road, school, zoo, nebo vlastní 'key=value' tag."
        ),
    )
    async def osm_nearby(
        latitude: float = Field(description="Zeměpisná šířka WGS84."),
        longitude: float = Field(description="Zeměpisná délka WGS84."),
        radius_m: int = Field(default=2000, description="Poloměr hledání v metrech (100–20000)."),
        category: str = Field(
            default="farm",
            description="Předdefinovaná kategorie nebo OSM tag 'key=value'.",
        ),
    ) -> str:
        return await _osm_nearby(latitude, longitude, radius_m, category)

    return mcp
