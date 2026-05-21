"""Open-Meteo — weather forecast & ERA5 climate aggregates."""

from __future__ import annotations

import datetime as dt
import logging
import math
from typing import Literal

import httpx

from ..http_utils import new_client

logger = logging.getLogger("farma_tools_mcp.tools.open_meteo")

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/era5"

MONTHS_CZ = [
    "Leden", "Únor", "Březen", "Duben", "Květen", "Červen",
    "Červenec", "Srpen", "Září", "Říjen", "Listopad", "Prosinec",
]


def _safe_float(x) -> float | None:
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


async def _forecast(lat: float, lon: float, days: int) -> str:
    days_clamped = max(1, min(int(days or 7), 14))
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max,weathercode",
        "timezone": "Europe/Prague",
        "forecast_days": days_clamped,
    }
    async with new_client() as client:
        resp = await client.get(FORECAST_URL, params=params)
    if resp.status_code >= 400:
        return f"Open-Meteo vrátil HTTP {resp.status_code}."
    data = resp.json()
    w = data.get("daily") or {}
    times = w.get("time") or []
    if not times:
        return "Žádná data nebyla vrácena."

    lines = [
        f"**Předpověď pro {lat}, {lon} ({days_clamped} dní)**",
        "",
        "Datum | Tmin | Tmax | Srážky | Vítr",
    ]
    tmin = w.get("temperature_2m_min") or []
    tmax = w.get("temperature_2m_max") or []
    prcp = w.get("precipitation_sum") or []
    wind = w.get("wind_speed_10m_max") or []
    for i, day in enumerate(times):
        lines.append(
            f"{day} | {tmin[i] if i < len(tmin) else '—'}°C | "
            f"{tmax[i] if i < len(tmax) else '—'}°C | "
            f"{prcp[i] if i < len(prcp) else '—'} mm | "
            f"{wind[i] if i < len(wind) else '—'} km/h"
        )
    return "\n".join(lines)


async def _climate(lat: float, lon: float) -> str:
    today = dt.datetime.now(dt.timezone.utc)
    end_y = today.year - 1
    start_y = end_y - 9
    start = f"{start_y}-01-01"
    end = f"{end_y}-12-31"

    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start,
        "end_date": end,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
        "timezone": "Europe/Prague",
    }
    async with new_client(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
        resp = await client.get(ARCHIVE_URL, params=params)
    if resp.status_code >= 400:
        return f"Open-Meteo archive vrátil HTTP {resp.status_code}."
    data = resp.json()
    daily = data.get("daily") or {}
    days = daily.get("time") or []
    if not days:
        return "Žádná klimatická data nebyla vrácena."

    tmax_arr = daily.get("temperature_2m_max") or []
    tmin_arr = daily.get("temperature_2m_min") or []
    prcp_arr = daily.get("precipitation_sum") or []

    months: list[dict] = [{"tmax": [], "tmin": [], "prcp": 0.0, "n": 0} for _ in range(12)]
    frost_days = 0
    for i, day in enumerate(days):
        try:
            m = int(day[5:7]) - 1
        except (ValueError, IndexError):
            continue
        if not (0 <= m < 12):
            continue
        tmax = _safe_float(tmax_arr[i] if i < len(tmax_arr) else None)
        tmin = _safe_float(tmin_arr[i] if i < len(tmin_arr) else None)
        prcp = _safe_float(prcp_arr[i] if i < len(prcp_arr) else None) or 0.0
        if tmax is not None:
            months[m]["tmax"].append(tmax)
        if tmin is not None:
            months[m]["tmin"].append(tmin)
            if tmin < 0:
                frost_days += 1
        months[m]["prcp"] += prcp
        months[m]["n"] += 1

    years = end_y - start_y + 1
    avg = lambda arr: (sum(arr) / len(arr)) if arr else float("nan")

    lines = [
        f"**Klimatická data pro {lat}, {lon}** (průměry {start_y}–{end_y})",
        "Měsíc | Tmax avg | Tmin avg | Srážky/měs",
    ]
    total_prcp = 0.0
    for m in range(12):
        month_prcp_avg = months[m]["prcp"] / years
        total_prcp += months[m]["prcp"]
        lines.append(
            f"{MONTHS_CZ[m]} | {avg(months[m]['tmax']):.1f}°C | "
            f"{avg(months[m]['tmin']):.1f}°C | {month_prcp_avg:.0f} mm"
        )
    lines.append("")
    lines.append(f"Průměrný roční úhrn srážek: {total_prcp / years:.0f} mm")
    lines.append(f"Průměrný počet mrazových dnů (Tmin < 0°C) ročně: {frost_days / years:.0f}")
    return "\n".join(lines)


async def open_meteo(
    latitude: float,
    longitude: float,
    mode: Literal["forecast", "climate"] = "forecast",
    days: int = 7,
) -> str:
    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError):
        return f"Chyba: neplatné souřadnice (lat={latitude}, lon={longitude})."

    use_climate = str(mode or "").lower() == "climate"
    logger.info("open_meteo lat=%s lon=%s mode=%s days=%s", lat, lon, "climate" if use_climate else "forecast", days)

    try:
        if use_climate:
            return await _climate(lat, lon)
        return await _forecast(lat, lon, days)
    except httpx.HTTPError as e:
        return f"Chyba při dotazu na Open-Meteo: {e}"
    except ValueError as e:
        return f"Chyba při parsování Open-Meteo odpovědi: {e}"
