"""Unit tests for the FTSE 100 adapter (no network)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from equity_aggregator.adapters import ftse100 as ftse100_module
from equity_aggregator.adapters.ftse100 import (
    FTSE100_ISINS,
    FTSE100_MEMBERS,
    FTSE100Adapter,
    _build_constituent,
    _fetch_member,
    _Member,
    _normalise_price,
)


def _shel_info() -> dict[str, Any]:
    """Realistic SHEL.L payload — price in pence, currency GBp."""
    return {
        "shortName": "SHELL PLC ORD EUR0.07",
        "longName": "Shell plc",
        "currentPrice": 3205.0,
        "regularMarketPrice": 3205.0,
        "currency": "GBp",
        "exDividendDate": 1779321600,
        "dividendYield": 3.63,
        "beta": -0.24,
        "marketCap": 178_350_866_432,
        "sector": "Energy",
        "isin": None,
        "exchange": "LSE",
        "quoteType": "EQUITY",
    }


# ---------------------- _normalise_price ------------------------------------


def test_normalise_price_converts_gbp_pence_to_pounds() -> None:
    price, currency = _normalise_price(3205.0, "GBp")
    assert price == pytest.approx(32.05)
    assert currency == "GBP"


def test_normalise_price_passes_through_gbp() -> None:
    price, currency = _normalise_price(25.0, "GBP")
    assert price == pytest.approx(25.0)
    assert currency == "GBP"


def test_normalise_price_defaults_currency_to_gbp_when_missing() -> None:
    price, currency = _normalise_price(25.0, None)
    assert price == pytest.approx(25.0)
    assert currency == "GBP"


def test_normalise_price_handles_none_price() -> None:
    price, currency = _normalise_price(None, "GBp")
    assert price is None
    assert currency == "GBP"


# ---------------------- _build_constituent ----------------------------------


def test_build_constituent_normalises_gbp_pence() -> None:
    member = _Member("SHEL.L", "SHELL PLC", "GB00BP6MXD84", 7.2976)
    c = _build_constituent(member, _shel_info())
    assert c.ticker == "SHEL.L"
    assert c.country == "GB"
    assert c.currency == "GBP"
    assert c.price == pytest.approx(32.05)
    assert c.sector == "Energy"
    assert c.beta == pytest.approx(-0.24)
    assert c.market_cap == pytest.approx(178_350_866_432.0)
    assert c.ttm_div_yield == pytest.approx(3.63)
    assert c.ex_div_date is not None
    # ISIN now always comes from the curated static map (was None before).
    assert c.isin == "GB00BP6MXD84"
    assert c.isin_source == "static"
    assert c.weight == pytest.approx(7.2976)


def test_build_constituent_no_double_conversion_for_gbp() -> None:
    member = _Member("ABC.L", "ABC PLC", "GB0000000ABCD", 0.5)
    info = _shel_info() | {
        "currency": "GBP",
        "currentPrice": 25.0,
        "regularMarketPrice": 25.0,
    }
    c = _build_constituent(member, info)
    assert c.price == pytest.approx(25.0)
    assert c.currency == "GBP"


def test_build_constituent_falls_back_to_static_name_when_yf_empty() -> None:
    member = _Member("XYZ.L", "Static Name PLC", "GB0000000XYZW", 0.1)
    c = _build_constituent(member, {})
    assert c.name == "Static Name PLC"
    assert c.isin == "GB0000000XYZW"
    assert c.isin_source == "static"


def test_build_constituent_falls_back_to_regular_market_price() -> None:
    member = _Member("SHEL.L", "SHELL PLC", "GB00BP6MXD84", 7.2976)
    info = _shel_info() | {"currentPrice": None}
    c = _build_constituent(member, info)
    # 3205 GBp → 32.05 GBP
    assert c.price == pytest.approx(32.05)
    assert c.currency == "GBP"


# ---------------------- _fetch_member ---------------------------------------


@pytest.mark.asyncio
async def test_fetch_member_returns_constituent_on_success() -> None:
    member = _Member("SHEL.L", "SHELL PLC", "GB00BP6MXD84", 7.2976)

    async def _ok(_: str) -> dict[str, Any]:
        return _shel_info()

    with patch.object(ftse100_module, "_fetch_yf_info", _ok):
        c = await _fetch_member(member)

    assert c.ticker == "SHEL.L"
    assert c.country == "GB"
    assert c.currency == "GBP"
    assert c.isin == "GB00BP6MXD84"


@pytest.mark.asyncio
async def test_fetch_member_survives_total_failure() -> None:
    """When yfinance blows up, still emit a row with static identity + GBP."""
    member = _Member("DEAD.L", "Dead PLC", "GB000DEAD0001", 0.01)

    async def _boom(_: str) -> dict[str, Any]:
        raise RuntimeError("network blew up")

    with patch.object(ftse100_module, "_fetch_yf_info", _boom):
        c = await _fetch_member(member)

    assert c.ticker == "DEAD.L"
    assert c.name == "Dead PLC"
    assert c.isin == "GB000DEAD0001"
    assert c.isin_source == "static"
    assert c.currency == "GBP"
    assert c.price is None


# ---------------------- static-map invariants -------------------------------


def test_ftse100_member_count_matches_index_size() -> None:
    # FTSE Russell maintains 100 names; iShares fund may briefly hold a few
    # extras around rebalances. Cap the window to catch accidental drift.
    assert 95 <= len(FTSE100_MEMBERS) <= 110
    tickers = [m.ticker for m in FTSE100_MEMBERS]
    assert len(set(tickers)) == len(tickers), "duplicate tickers"
    assert all(t.endswith(".L") for t in tickers)


def test_ftse100_every_member_has_a_real_isin() -> None:
    """Regression: the previous adapter shipped ``isin=None`` for every
    constituent. That was unacceptable for a finance app — the static map
    must carry a 12-char ISO 6166 ISIN for every row.
    """
    for m in FTSE100_MEMBERS:
        assert len(m.isin) == 12, f"{m.ticker} ISIN length wrong: {m.isin!r}"
        assert m.isin[:2].isalpha(), f"{m.ticker} ISIN prefix not alpha"
        assert m.isin in FTSE100_ISINS.values()


def test_ftse100_weights_are_in_descending_order() -> None:
    """Static map is generated weight-desc so the UI's default ordering
    reflects index-cap weighting.
    """
    weights = [m.weight for m in FTSE100_MEMBERS]
    assert weights == sorted(weights, reverse=True)


def test_ftse100_adapter_is_instantiable() -> None:
    adapter = FTSE100Adapter()
    assert adapter.name == "FTSE 100"
    assert adapter.country == "GB"
    assert callable(adapter.fetch_constituents)
