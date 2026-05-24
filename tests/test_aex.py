"""Unit tests for the AEX adapter (no network)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from equity_aggregator.adapters import aex as aex_module
from equity_aggregator.adapters.aex import (
    AEX_ISINS,
    AEX_MEMBERS,
    AEXAdapter,
    _build_constituent,
    _fetch_member,
    _Member,
    _resolve_isin_from_yfinance,
)


def _asml_info() -> dict[str, Any]:
    return {
        "longName": "ASML Holding N.V.",
        "shortName": "ASML HOLDING",
        "currentPrice": 1409.0,
        "regularMarketPrice": 1409.0,
        "previousClose": 1345.2,
        "currency": "EUR",
        "country": "Netherlands",
        "sector": "Technology",
        "beta": 1.373,
        "marketCap": 543_053_479_936,
        "dividendYield": 0.77,
        "exDividendDate": 1776988800,
        "isin": None,
    }


def test_build_constituent_maps_yfinance_fields() -> None:
    member = _Member("ASML.AS", "ASML Holding N.V.", "NL0010273215")
    c = _build_constituent(member, _asml_info(), figi_record=None)

    assert c.ticker == "ASML.AS"
    assert c.name == "ASML Holding N.V."
    assert c.country == "NL"
    assert c.currency == "EUR"
    assert c.price == pytest.approx(1409.0)
    assert c.sector == "Technology"
    assert c.beta == pytest.approx(1.373)
    assert c.market_cap == pytest.approx(543_053_479_936.0)
    assert c.ttm_div_yield == pytest.approx(0.77)
    # ISIN falls back to the static map when yfinance returns None.
    assert c.isin == "NL0010273215"
    assert c.isin_source == "static"
    # exDividendDate epoch decodes to a real date.
    assert c.ex_div_date is not None
    assert c.ex_div_date.year == 2026
    assert c.ex_div_date.month == 4


def test_build_constituent_prefers_yfinance_isin_when_present() -> None:
    member = _Member("ASML.AS", "ASML Holding N.V.", "NL0000FROMSTATIC")
    info = _asml_info() | {"isin": "NL0000FROMYFINANCE"}
    c = _build_constituent(member, info, figi_record=None)
    assert c.isin == "NL0000FROMYFINANCE"
    assert c.isin_source == "yfinance"


def test_build_constituent_treats_yfinance_dash_as_missing() -> None:
    member = _Member("ASML.AS", "ASML Holding N.V.", "NL0010273215")
    info = _asml_info() | {"isin": "-"}
    c = _build_constituent(member, info, figi_record=None)
    assert c.isin == "NL0010273215"
    assert c.isin_source == "static"


def test_build_constituent_uses_openfigi_isin_when_present() -> None:
    member = _Member("ASML.AS", "ASML Holding N.V.", "NL0000FROMSTATIC")
    info = _asml_info() | {"isin": None}
    figi = {
        "figi": "BBG000C1KBR2",
        "name": "ASML HOLDING NV",
        "isin": "NL0000FROMFIGI",
    }
    c = _build_constituent(member, info, figi_record=figi)
    assert c.isin == "NL0000FROMFIGI"
    assert c.isin_source == "openfigi"


def test_resolve_isin_from_yfinance_handles_garbage() -> None:
    assert _resolve_isin_from_yfinance({}) is None
    assert _resolve_isin_from_yfinance({"isin": None}) is None
    assert _resolve_isin_from_yfinance({"isin": ""}) is None
    assert _resolve_isin_from_yfinance({"isin": "-"}) is None
    assert _resolve_isin_from_yfinance({"isin": "  -  "}) is None
    assert _resolve_isin_from_yfinance({"isin": " NL0010273215 "}) == "NL0010273215"


@pytest.mark.asyncio
async def test_fetch_member_survives_total_failure() -> None:
    """When both yfinance and OpenFIGI fail/return empty, still produce a row."""
    member = _Member("XYZ.AS", "Mystery Corp", "NL0000MYSTERY1")

    async def _empty_yf(_: str) -> dict[str, Any]:
        return {}

    async def _none_figi(*_: Any, **__: Any) -> dict[str, Any] | None:
        return None

    with (
        patch.object(aex_module, "_fetch_yf_info", _empty_yf),
        patch.object(aex_module, "_fetch_openfigi", _none_figi),
    ):
        c = await _fetch_member(client=None, member=member)  # type: ignore[arg-type]

    assert c.ticker == "XYZ.AS"
    assert c.name == "Mystery Corp"
    assert c.isin == "NL0000MYSTERY1"
    assert c.isin_source == "static"
    assert c.country == "NL"
    assert c.price is None
    assert c.sector is None


def test_aex_adapter_has_25_members() -> None:
    assert len(AEX_MEMBERS) == 25
    tickers = [m.ticker for m in AEX_MEMBERS]
    assert len(set(tickers)) == 25, "duplicate tickers in AEX_MEMBERS"
    assert all(t.endswith(".AS") for t in tickers)


def test_aex_adapter_is_instantiable() -> None:
    adapter = AEXAdapter()
    assert adapter.name == "AEX"
    assert adapter.country == "NL"
    assert callable(adapter.fetch_constituents)


def test_aex_all_members_have_isin_entry() -> None:
    """Every member ticker must have a corresponding entry in AEX_ISINS."""
    for member in AEX_MEMBERS:
        assert member.ticker in AEX_ISINS, (
            f"{member.ticker} missing from AEX_ISINS"
        )


def test_aex_currency_on_mock_output() -> None:
    """Currency field from yfinance mock is EUR for AEX constituents."""
    member = _Member("HEIA.AS", "Heineken N.V.", "NL0000009165")
    info = {
        "longName": "Heineken N.V.",
        "currentPrice": 68.86,
        "currency": "EUR",
        "sector": "Consumer Defensive",
        "isin": None,
    }
    c = _build_constituent(member, info, figi_record=None)
    assert c.currency == "EUR"
    assert c.country == "NL"


def test_aex_country_is_nl_for_all_members() -> None:
    """All AEX constituents must report country == 'NL' (listing venue)."""
    for member in AEX_MEMBERS:
        info: dict[str, Any] = {"longName": member.name, "currency": "EUR"}
        c = _build_constituent(member, info, figi_record=None)
        assert c.country == "NL", (
            f"{member.ticker} has country={c.country!r}, expected 'NL'"
        )
