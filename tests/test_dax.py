"""Unit tests for the DAX adapter (no network)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from equity_aggregator.adapters import dax as dax_module
from equity_aggregator.adapters.dax import (
    DAX_MEMBERS,
    DAXAdapter,
    _build_constituent,
    _fetch_member,
    _Member,
    _resolve_isin_from_yfinance,
)


def _adidas_info() -> dict[str, Any]:
    return {
        "longName": "adidas AG",
        "shortName": "ADIDAS AG",
        "currentPrice": 154.5,
        "regularMarketPrice": 154.5,
        "previousClose": 150.0,
        "currency": "EUR",
        "country": "Germany",
        "sector": "Consumer Cyclical",
        "beta": 1.209,
        "marketCap": 27_400_000_000,
        "dividendYield": 1.81,
        "exDividendDate": 1778198400,
        "isin": None,
    }


def test_build_constituent_maps_yfinance_fields() -> None:
    member = _Member("ADS.DE", "adidas AG", "DE000A1EWWW0")
    c = _build_constituent(member, _adidas_info(), figi_record=None)

    assert c.ticker == "ADS.DE"
    assert c.name == "adidas AG"
    assert c.country == "DE"
    assert c.currency == "EUR"
    assert c.price == pytest.approx(154.5)
    assert c.sector == "Consumer Cyclical"
    assert c.beta == pytest.approx(1.209)
    assert c.market_cap == pytest.approx(27_400_000_000.0)
    assert c.ttm_div_yield == pytest.approx(1.81)
    # ISIN falls back to the static map when yfinance returns None.
    assert c.isin == "DE000A1EWWW0"
    assert c.isin_source == "static"
    # exDividendDate epoch decodes to a real date.
    assert c.ex_div_date is not None
    assert c.ex_div_date.year == 2026
    assert c.ex_div_date.month == 5


def test_build_constituent_prefers_yfinance_isin_when_present() -> None:
    member = _Member("ADS.DE", "adidas AG", "DE000FROMSTATIC")
    info = _adidas_info() | {"isin": "DE000FROMYFINANCE"}
    c = _build_constituent(member, info, figi_record=None)
    assert c.isin == "DE000FROMYFINANCE"
    assert c.isin_source == "yfinance"


def test_build_constituent_treats_yfinance_dash_as_missing() -> None:
    member = _Member("ADS.DE", "adidas AG", "DE000A1EWWW0")
    info = _adidas_info() | {"isin": "-"}
    c = _build_constituent(member, info, figi_record=None)
    assert c.isin == "DE000A1EWWW0"
    assert c.isin_source == "static"


def test_build_constituent_uses_openfigi_isin_when_present() -> None:
    member = _Member("ADS.DE", "adidas AG", "DE000FROMSTATIC")
    info = _adidas_info() | {"isin": None}
    figi = {
        "figi": "BBG000FR1Q22",
        "name": "ADIDAS AG",
        "isin": "DE000FROMFIGI",
    }
    c = _build_constituent(member, info, figi_record=figi)
    assert c.isin == "DE000FROMFIGI"
    assert c.isin_source == "openfigi"


def test_resolve_isin_from_yfinance_handles_garbage() -> None:
    assert _resolve_isin_from_yfinance({}) is None
    assert _resolve_isin_from_yfinance({"isin": None}) is None
    assert _resolve_isin_from_yfinance({"isin": ""}) is None
    assert _resolve_isin_from_yfinance({"isin": "-"}) is None
    assert _resolve_isin_from_yfinance({"isin": "  -  "}) is None
    assert _resolve_isin_from_yfinance({"isin": " DE0007164600 "}) == "DE0007164600"


@pytest.mark.asyncio
async def test_fetch_member_survives_total_failure() -> None:
    """When both yfinance and OpenFIGI fail/return empty, still produce a row."""
    member = _Member("XYZ.DE", "Mystery Corp", "DE000MYSTERY1")

    async def _empty_yf(_: str) -> dict[str, Any]:
        return {}

    async def _none_figi(*_: Any, **__: Any) -> dict[str, Any] | None:
        return None

    with (
        patch.object(dax_module, "_fetch_yf_info", _empty_yf),
        patch.object(dax_module, "_fetch_openfigi", _none_figi),
    ):
        c = await _fetch_member(client=None, member=member)  # type: ignore[arg-type]

    assert c.ticker == "XYZ.DE"
    assert c.name == "Mystery Corp"
    assert c.isin == "DE000MYSTERY1"
    assert c.isin_source == "static"
    assert c.country == "DE"
    assert c.price is None
    assert c.sector is None


def test_dax_adapter_has_40_members() -> None:
    assert len(DAX_MEMBERS) == 40
    tickers = [m.ticker for m in DAX_MEMBERS]
    assert len(set(tickers)) == 40, "duplicate tickers in DAX_MEMBERS"
    assert all(t.endswith(".DE") for t in tickers)


def test_dax_adapter_is_instantiable() -> None:
    adapter = DAXAdapter()
    assert adapter.name == "DAX"
    assert adapter.country == "DE"
    assert callable(adapter.fetch_constituents)
