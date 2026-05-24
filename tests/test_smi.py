"""Unit tests for the SMI adapter (no network)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from equity_aggregator.adapters import smi as smi_module
from equity_aggregator.adapters.smi import (
    SMI_ISINS,
    SMI_MEMBERS,
    SMIAdapter,
    _build_constituent,
    _fetch_member,
    _Member,
    _resolve_isin_from_yfinance,
)


def _nesn_info() -> dict[str, Any]:
    return {
        "longName": "Nestlé S.A.",
        "shortName": "NESTLE N",
        "currentPrice": 78.78,
        "regularMarketPrice": 78.78,
        "previousClose": 78.8,
        "currency": "CHF",
        "country": "Switzerland",
        "sector": "Consumer Defensive",
        "beta": 0.499,
        "marketCap": 202_639_474_688,
        "dividendYield": 3.94,
        "exDividendDate": 1776643200,
        "isin": None,
    }


def test_build_constituent_maps_yfinance_fields() -> None:
    member = _Member("NESN.SW", "Nestlé S.A.", "CH0038863350")
    c = _build_constituent(member, _nesn_info(), figi_record=None)

    assert c.ticker == "NESN.SW"
    assert c.name == "Nestlé S.A."
    assert c.country == "CH"
    assert c.currency == "CHF"
    assert c.price == pytest.approx(78.78)
    assert c.sector == "Consumer Defensive"
    assert c.beta == pytest.approx(0.499)
    assert c.market_cap == pytest.approx(202_639_474_688.0)
    assert c.ttm_div_yield == pytest.approx(3.94)
    # ISIN falls back to the static map when yfinance returns None.
    assert c.isin == "CH0038863350"
    assert c.isin_source == "static"
    # exDividendDate epoch decodes to a real date.
    assert c.ex_div_date is not None
    assert c.ex_div_date.year == 2026
    assert c.ex_div_date.month == 4


def test_build_constituent_prefers_yfinance_isin_when_present() -> None:
    member = _Member("NESN.SW", "Nestlé S.A.", "CH0000FROMSTATIC")
    info = _nesn_info() | {"isin": "CH0000FROMYFINANCE"}
    c = _build_constituent(member, info, figi_record=None)
    assert c.isin == "CH0000FROMYFINANCE"
    assert c.isin_source == "yfinance"


def test_build_constituent_treats_yfinance_dash_as_missing() -> None:
    member = _Member("NESN.SW", "Nestlé S.A.", "CH0038863350")
    info = _nesn_info() | {"isin": "-"}
    c = _build_constituent(member, info, figi_record=None)
    assert c.isin == "CH0038863350"
    assert c.isin_source == "static"


def test_build_constituent_uses_openfigi_isin_when_present() -> None:
    member = _Member("NESN.SW", "Nestlé S.A.", "CH0000FROMSTATIC")
    info = _nesn_info() | {"isin": None}
    figi = {
        "figi": "BBG000CZWV58",
        "name": "NESTLE SA",
        "isin": "CH0000FROMFIGI",
    }
    c = _build_constituent(member, info, figi_record=figi)
    assert c.isin == "CH0000FROMFIGI"
    assert c.isin_source == "openfigi"


def test_resolve_isin_from_yfinance_handles_garbage() -> None:
    assert _resolve_isin_from_yfinance({}) is None
    assert _resolve_isin_from_yfinance({"isin": None}) is None
    assert _resolve_isin_from_yfinance({"isin": ""}) is None
    assert _resolve_isin_from_yfinance({"isin": "-"}) is None
    assert _resolve_isin_from_yfinance({"isin": "  -  "}) is None
    assert _resolve_isin_from_yfinance({"isin": " CH0038863350 "}) == "CH0038863350"


@pytest.mark.asyncio
async def test_fetch_member_survives_total_failure() -> None:
    """When both yfinance and OpenFIGI fail/return empty, still produce a row."""
    member = _Member("XYZ.SW", "Mystery Corp", "CH0000MYSTERY1")

    async def _empty_yf(_: str) -> dict[str, Any]:
        return {}

    async def _none_figi(*_: Any, **__: Any) -> dict[str, Any] | None:
        return None

    with (
        patch.object(smi_module, "_fetch_yf_info", _empty_yf),
        patch.object(smi_module, "_fetch_openfigi", _none_figi),
    ):
        c = await _fetch_member(client=None, member=member)  # type: ignore[arg-type]

    assert c.ticker == "XYZ.SW"
    assert c.name == "Mystery Corp"
    assert c.isin == "CH0000MYSTERY1"
    assert c.isin_source == "static"
    assert c.country == "CH"
    assert c.price is None
    assert c.sector is None


def test_smi_adapter_has_20_members() -> None:
    assert len(SMI_MEMBERS) == 20
    tickers = [m.ticker for m in SMI_MEMBERS]
    assert len(set(tickers)) == 20, "duplicate tickers in SMI_MEMBERS"
    assert all(t.endswith(".SW") for t in tickers)


def test_smi_adapter_is_instantiable() -> None:
    adapter = SMIAdapter()
    assert adapter.name == "SMI"
    assert adapter.country == "CH"
    assert callable(adapter.fetch_constituents)


def test_smi_all_members_have_isin_entry() -> None:
    """Every member ticker must have a corresponding entry in SMI_ISINS."""
    for member in SMI_MEMBERS:
        assert member.ticker in SMI_ISINS, (
            f"{member.ticker} missing from SMI_ISINS"
        )


def test_smi_all_isins_start_with_ch() -> None:
    """All Swiss ISINs in the static map must start with 'CH'."""
    for ticker, isin in SMI_ISINS.items():
        assert isin.startswith("CH"), (
            f"{ticker} has ISIN {isin!r}, expected prefix 'CH'"
        )


def test_smi_currency_on_mock_output() -> None:
    """Currency field from yfinance mock is CHF for SMI constituents."""
    member = _Member("NOVN.SW", "Novartis AG", "CH0012221060")
    info = {
        "longName": "Novartis AG",
        "currentPrice": 95.4,
        "currency": "CHF",
        "sector": "Healthcare",
        "isin": None,
    }
    c = _build_constituent(member, info, figi_record=None)
    assert c.currency == "CHF"
    assert c.country == "CH"


def test_smi_country_is_ch_for_all_members() -> None:
    """All SMI constituents must report country == 'CH' (listing venue)."""
    for member in SMI_MEMBERS:
        info: dict[str, Any] = {"longName": member.name, "currency": "CHF"}
        c = _build_constituent(member, info, figi_record=None)
        assert c.country == "CH", (
            f"{member.ticker} has country={c.country!r}, expected 'CH'"
        )
