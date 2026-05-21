"""Tests for ares_lookup tool.

Real ARES response for IČO 45274649 (ČEZ, a. s.) lives in
tests/fixtures/ares_company.json — captured live and refreshable.
"""

from __future__ import annotations

import httpx

from farma_tools_mcp.tools.ares import ARES_URL, _clean_ico, ares_lookup


def test_clean_ico_pads_short():
    assert _clean_ico("12345") == "00012345"


def test_clean_ico_strips_non_digits():
    assert _clean_ico("  271 39 028 ") == "27139028"


def test_clean_ico_rejects_too_long():
    assert len(_clean_ico("123456789")) == 9


async def test_ares_invalid_ico_format():
    result = await ares_lookup("abc")
    assert result.startswith("Chyba: IČO musí mít 8 číslic")


async def test_ares_real_cez_payload(mock_http, fixture):
    """Real captured ARES response for ČEZ, a. s. (IČO 45274649)."""
    payload = fixture("ares_company")
    mock_http.get(ARES_URL.format(ico="45274649")).mock(
        return_value=httpx.Response(200, json=payload)
    )

    result = await ares_lookup("45274649")

    assert "**ČEZ, a. s.**" in result
    assert "IČO: 45274649" in result
    assert "DIČ:" in result
    # ČEZ should have several active registrations
    assert "Aktivní registrace:" in result
    assert "Detail: https://ares.gov.cz/ekonomicke-subjekty/?ico=45274649" in result


async def test_ares_404_real_http_code(mock_http):
    """ARES really returns 404 for unknown IČOs (verified live 2026-05)."""
    mock_http.get(ARES_URL.format(ico="00000001")).mock(return_value=httpx.Response(404, json={"kod": "NENALEZENO"}))

    result = await ares_lookup("1")

    assert result == "Subjekt s IČO 00000001 nebyl v ARES nalezen."


async def test_ares_5xx(mock_http):
    mock_http.get(ARES_URL.format(ico="27139028")).mock(return_value=httpx.Response(503))
    result = await ares_lookup("27139028")
    assert result == "ARES vrátil HTTP 503."


async def test_ares_network_error(mock_http):
    mock_http.get(ARES_URL.format(ico="27139028")).mock(side_effect=httpx.ConnectError("connection reset"))
    result = await ares_lookup("27139028")
    assert result.startswith("Chyba při dotazu na ARES:")
    assert "connection reset" in result


async def test_ares_minimal_payload(mock_http):
    """Missing/None optional fields render gracefully."""
    mock_http.get(ARES_URL.format(ico="27139028")).mock(
        return_value=httpx.Response(200, json={"ico": "27139028", "obchodniJmeno": None})
    )

    result = await ares_lookup("27139028")

    assert "**(bez názvu)**" in result
    assert "DIČ: není" in result
    assert "Aktivní registrace" not in result


async def test_ares_seznam_registraci_parsing(mock_http):
    """stavZdroje* keys filter to active / ceased lists."""
    mock_http.get(ARES_URL.format(ico="27139028")).mock(
        return_value=httpx.Response(200, json={
            "ico": "27139028",
            "obchodniJmeno": "Test",
            "seznamRegistraci": {
                "stavZdrojeVR": "AKTIVNI",
                "stavZdrojeRES": "AKTIVNI",
                "stavZdrojeDPH": "ZANIKLY",
                "stavZdrojeXX": "JINY_STAV",  # ignored
            },
        })
    )

    result = await ares_lookup("27139028")

    assert "Aktivní registrace: VR, RES" in result
    assert "Zaniklé registrace: DPH" in result
    assert "JINY_STAV" not in result
