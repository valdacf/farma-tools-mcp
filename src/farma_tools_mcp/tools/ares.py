"""ARES lookup — Czech business registry by IČO."""

from __future__ import annotations

import logging
import re

import httpx

from ..http_utils import new_client

logger = logging.getLogger("farma_tools_mcp.tools.ares")

ARES_URL = "https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/{ico}"


def _clean_ico(raw: str) -> str:
    digits = re.sub(r"\D", "", str(raw or ""))
    return digits.zfill(8) if digits else ""


async def ares_lookup(ico: str) -> str:
    cleaned = _clean_ico(ico)
    if len(cleaned) != 8:
        return f"Chyba: IČO musí mít 8 číslic. Dostal jsem '{ico}'."

    logger.info("ares_lookup ico=%s", cleaned)
    try:
        async with new_client() as client:
            resp = await client.get(ARES_URL.format(ico=cleaned))
    except httpx.HTTPError as e:
        return f"Chyba při dotazu na ARES: {e}"

    if resp.status_code == 404:
        return f"Subjekt s IČO {cleaned} nebyl v ARES nalezen."
    if resp.status_code >= 400:
        return f"ARES vrátil HTTP {resp.status_code}."

    try:
        d = resp.json()
    except ValueError as e:
        return f"Chyba při parsování ARES odpovědi: {e}"

    lines: list[str] = [
        f"**{d.get('obchodniJmeno') or '(bez názvu)'}**",
        f"IČO: {d.get('ico', cleaned)}",
        f"DIČ: {d.get('dic') or 'není'}",
        f"Právní forma: {d.get('pravniForma') or '—'}",
        f"Sídlo: {(d.get('sidlo') or {}).get('textovaAdresa') or '—'}",
        f"Kraj: {(d.get('sidlo') or {}).get('nazevKraje') or '—'}",
        f"Datum aktualizace: {d.get('datumAktualizace') or '—'}",
    ]

    nace = d.get("czNace2008") or d.get("czNace")
    if isinstance(nace, list) and nace:
        lines.append(f"NACE (předmět činnosti): {', '.join(str(n) for n in nace)}")

    if d.get("financniUrad"):
        lines.append(f"Finanční úřad (kód): {d['financniUrad']}")

    sr = d.get("seznamRegistraci")
    if isinstance(sr, dict):
        active = [k.removeprefix("stavZdroje") for k, v in sr.items() if v == "AKTIVNI"]
        ceased = [k.removeprefix("stavZdroje") for k, v in sr.items() if v == "ZANIKLY"]
        if active:
            lines.append(f"Aktivní registrace: {', '.join(active)}")
        if ceased:
            lines.append(f"Zaniklé registrace: {', '.join(ceased)}")

    adresa = d.get("adresaDorucovaci")
    if isinstance(adresa, dict):
        parts = [adresa.get(f"radekAdresy{i}") for i in (1, 2, 3)]
        parts = [p for p in parts if p]
        if parts:
            lines.append(f"Doručovací adresa: {', '.join(parts)}")

    lines.append("")
    lines.append(f"Detail: https://ares.gov.cz/ekonomicke-subjekty/?ico={cleaned}")
    return "\n".join(lines)
