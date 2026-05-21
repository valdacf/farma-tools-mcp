"""Tests for open_meteo tool.

Real captured responses (Prague, 3-day forecast + 2-year ERA5 climate) live in
tests/fixtures/openmeteo_*.json.
"""

from __future__ import annotations

import datetime as dt
import re

import httpx

from farma_tools_mcp.tools.open_meteo import ARCHIVE_URL, FORECAST_URL, open_meteo


def _archive_re() -> re.Pattern:
    return re.compile(re.escape(ARCHIVE_URL) + r".*")


def _forecast_re() -> re.Pattern:
    return re.compile(re.escape(FORECAST_URL) + r".*")


async def test_invalid_coords():
    result = await open_meteo("not-a-number", 14.0)  # type: ignore[arg-type]
    assert result.startswith("Chyba: neplatné souřadnice")


async def test_real_prague_forecast(mock_http, fixture):
    """End-to-end with real 3-day Prague forecast fixture."""
    mock_http.get(_forecast_re()).mock(return_value=httpx.Response(200, json=fixture("openmeteo_forecast")))

    result = await open_meteo(50.0875, 14.4214, mode="forecast", days=3)

    assert "**Předpověď pro 50.0875, 14.4214 (3 dní)**" in result
    # Header row always present
    assert "Datum | Tmin | Tmax | Srážky | Vítr" in result
    # 3 data rows
    lines = [l for l in result.splitlines() if re.match(r"^\d{4}-\d{2}-\d{2}", l)]
    assert len(lines) == 3
    # Each line should have temperatures with °C and precipitation with mm
    for line in lines:
        assert "°C" in line
        assert "mm" in line
        assert "km/h" in line


async def test_forecast_5xx(mock_http):
    mock_http.get(_forecast_re()).mock(return_value=httpx.Response(502))
    result = await open_meteo(50.0, 14.0)
    assert result == "Open-Meteo vrátil HTTP 502."


async def test_forecast_clamps_days(mock_http):
    """`days=999` is clamped to 14 in the outgoing request."""
    route = mock_http.get(_forecast_re()).mock(
        return_value=httpx.Response(
            200,
            json={
                "daily": {
                    "time": [f"2026-01-{i:02d}" for i in range(1, 15)],
                    "temperature_2m_max": [0] * 14,
                    "temperature_2m_min": [0] * 14,
                    "precipitation_sum": [0] * 14,
                    "wind_speed_10m_max": [0] * 14,
                    "weathercode": [0] * 14,
                }
            },
        )
    )

    result = await open_meteo(50.0, 14.0, mode="forecast", days=999)

    assert "14 dní" in result
    assert "forecast_days=14" in str(route.calls.last.request.url)


async def test_real_prague_climate(mock_http, fixture):
    """End-to-end with real 2-year ERA5 climate fixture for Prague."""
    mock_http.get(_archive_re()).mock(return_value=httpx.Response(200, json=fixture("openmeteo_climate")))

    result = await open_meteo(50.0875, 14.4214, mode="climate")

    # Header shows year range derived from current date
    today = dt.datetime.now(dt.timezone.utc)
    assert f"**Klimatická data pro 50.0875, 14.4214**" in result
    # All 12 months present
    for m in ("Leden", "Únor", "Březen", "Duben", "Květen", "Červen",
              "Červenec", "Srpen", "Září", "Říjen", "Listopad", "Prosinec"):
        assert m + " | " in result
    # Aggregates present
    assert "Průměrný roční úhrn srážek:" in result
    assert "Průměrný počet mrazových dnů" in result
    # Sanity-check: precip total must be positive (Prague gets >400mm/year)
    m = re.search(r"Průměrný roční úhrn srážek: (\d+) mm", result)
    assert m and int(m.group(1)) > 100


async def test_climate_aggregation_logic(mock_http):
    """Synthetic input — verifies monthly averaging + frost-day counting."""
    today = dt.datetime.now(dt.timezone.utc)
    end_y = today.year - 1
    start_y = end_y - 9
    days: list[str] = []
    tmax: list[float] = []
    tmin: list[float] = []
    prcp: list[float] = []
    for y in range(start_y, end_y + 1):
        for md in ("01-01", "04-01", "07-01", "12-01"):
            days.append(f"{y}-{md}")
            tmax.append(20.0)
            tmin.append(-5.0 if md in ("01-01", "12-01") else 5.0)
            prcp.append(10.0)

    mock_http.get(_archive_re()).mock(
        return_value=httpx.Response(
            200,
            json={"daily": {
                "time": days,
                "temperature_2m_max": tmax,
                "temperature_2m_min": tmin,
                "precipitation_sum": prcp,
            }},
        )
    )

    result = await open_meteo(50.0, 14.0, mode="climate")

    assert "Leden | 20.0°C | -5.0°C | 10 mm" in result
    assert "Duben | 20.0°C | 5.0°C | 10 mm" in result
    assert "Průměrný počet mrazových dnů (Tmin < 0°C) ročně: 2" in result
    assert "Průměrný roční úhrn srážek: 40 mm" in result


async def test_climate_empty_response(mock_http):
    mock_http.get(_archive_re()).mock(return_value=httpx.Response(200, json={"daily": {"time": []}}))
    result = await open_meteo(50.0, 14.0, mode="climate")
    assert result == "Žádná klimatická data nebyla vrácena."
