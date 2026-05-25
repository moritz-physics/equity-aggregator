"""Unit tests for the S&P 500 adapter (no network)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from equity_aggregator.adapters import sp500 as sp500_module
from equity_aggregator.adapters.sp500 import (
    SP500_ISINS,
    SP500_MEMBERS,
    SP500Adapter,
    _build_constituent,
    _fetch_member,
    _Member,
    _parse_yield,
    _resolve_isin_from_yfinance,
)


def _aapl_info() -> dict[str, Any]:
    return {
        "shortName": "Apple Inc.",
        "longName": "Apple Inc.",
        "currentPrice": 308.82,
        "regularMarketPrice": 308.82,
        "currency": "USD",
        "exDividendDate": 1778457600,
        "dividendYield": 0.35,
        "trailingAnnualDividendYield": 0.003409948,
        "beta": 1.065,
        "marketCap": 4_535_749_181_440,
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "isin": None,
        "exchange": "NMS",
        "quoteType": "EQUITY",
    }


# ---------------------- _build_constituent ----------------------------------


def test_build_constituent_maps_yfinance_fields() -> None:
    member = _Member("AAPL", "APPLE INC", "US0378331005")
    c = _build_constituent(member, _aapl_info())
    assert c.ticker == "AAPL"
    assert c.name == "Apple Inc."
    assert c.country == "US"
    assert c.currency == "USD"
    assert c.price == pytest.approx(308.82)
    assert c.sector == "Technology"
    assert c.beta == pytest.approx(1.065)
    assert c.market_cap == pytest.approx(4_535_749_181_440.0)
    # 0.003409948 (decimal) → 0.3409948 (percent)
    assert c.ttm_div_yield == pytest.approx(0.3409948)
    assert c.ex_div_date is not None and c.ex_div_date.year == 2026
    # ISIN populated from static map when yfinance returns None.
    assert c.isin == "US0378331005"
    assert c.isin_source == "static"


def test_build_constituent_prefers_yfinance_isin_when_present() -> None:
    member = _Member("AAPL", "APPLE INC", "US0000FROMSTATIC")
    info = _aapl_info() | {"isin": "US0000FROMYFINANCE"}
    c = _build_constituent(member, info)
    assert c.isin == "US0000FROMYFINANCE"
    assert c.isin_source == "yfinance"


def test_build_constituent_treats_yfinance_dash_as_missing() -> None:
    member = _Member("AAPL", "APPLE INC", "US0378331005")
    info = _aapl_info() | {"isin": "-"}
    c = _build_constituent(member, info)
    assert c.isin == "US0378331005"
    assert c.isin_source == "static"


def test_build_constituent_uses_static_name_when_yfinance_empty() -> None:
    member = _Member("WEIRD", "WEIRD STATIC NAME", "US9999999999")
    info = _aapl_info() | {"shortName": None, "longName": None}
    c = _build_constituent(member, info)
    assert c.name == "WEIRD STATIC NAME"


def test_build_constituent_falls_back_to_regular_market_price() -> None:
    member = _Member("AAPL", "APPLE INC", "US0378331005")
    info = _aapl_info() | {"currentPrice": None}
    c = _build_constituent(member, info)
    assert c.price == pytest.approx(308.82)


def test_resolve_isin_from_yfinance_handles_garbage() -> None:
    assert _resolve_isin_from_yfinance({}) is None
    assert _resolve_isin_from_yfinance({"isin": None}) is None
    assert _resolve_isin_from_yfinance({"isin": ""}) is None
    assert _resolve_isin_from_yfinance({"isin": "-"}) is None
    assert _resolve_isin_from_yfinance({"isin": "  -  "}) is None
    assert _resolve_isin_from_yfinance({"isin": " US0378331005 "}) == "US0378331005"


# ---------------------- _parse_yield ----------------------------------------


def test_parse_yield_converts_decimal_to_percent() -> None:
    assert _parse_yield(0.0194) == pytest.approx(1.94)


def test_parse_yield_drops_zero_and_none() -> None:
    assert _parse_yield(None) is None
    assert _parse_yield(0) is None
    assert _parse_yield(0.0) is None


def test_parse_yield_rejects_garbage() -> None:
    assert _parse_yield("nope") is None


# ---------------------- _fetch_member ---------------------------------------


@pytest.mark.asyncio
async def test_fetch_member_returns_constituent() -> None:
    member = _Member("AAPL", "APPLE INC", "US0378331005")

    async def _ok(_: str) -> dict[str, Any]:
        return _aapl_info()

    with patch.object(sp500_module, "_fetch_yf_info", _ok):
        c = await _fetch_member(member)

    assert c.ticker == "AAPL"
    assert c.isin == "US0378331005"
    assert c.isin_source == "static"
    assert c.country == "US"


@pytest.mark.asyncio
async def test_fetch_member_survives_total_failure() -> None:
    """When yfinance fails, still produce a row from the static map."""
    member = _Member("DEAD", "MYSTERY CORP", "US9999991009")

    async def _empty(_: str) -> dict[str, Any]:
        return {}

    with patch.object(sp500_module, "_fetch_yf_info", _empty):
        c = await _fetch_member(member)

    assert c.ticker == "DEAD"
    assert c.name == "MYSTERY CORP"
    assert c.isin == "US9999991009"
    assert c.isin_source == "static"
    assert c.country == "US"
    assert c.price is None


@pytest.mark.asyncio
async def test_fetch_member_swallows_exception() -> None:
    member = _Member("BOOM", "FAILS HARD", "US0000000007")

    async def _boom(_: str) -> dict[str, Any]:
        raise RuntimeError("network blew up")

    with patch.object(sp500_module, "_fetch_yf_info", _boom):
        c = await _fetch_member(member)

    assert c.ticker == "BOOM"
    assert c.isin == "US0000000007"
    assert c.isin_source == "static"


# ---------------------- adapter / index integrity ---------------------------


def test_sp500_adapter_is_instantiable() -> None:
    adapter = SP500Adapter()
    assert adapter.name == "S&P 500"
    assert adapter.country == "US"
    assert callable(adapter.fetch_constituents)


def test_sp500_members_count_is_around_503() -> None:
    # S&P 500 has 503 stocks (3 dual-class share companies).
    # Allow ±5 to absorb rebalances between regenerations.
    assert 498 <= len(SP500_MEMBERS) <= 510
    tickers = [m.ticker for m in SP500_MEMBERS]
    assert len(set(tickers)) == len(tickers), "duplicate tickers in SP500_MEMBERS"


def test_sp500_all_isins_start_with_us() -> None:
    """All S&P 500 ISINs (CINS-based for US listings) must start with 'US'."""
    for ticker, isin in SP500_ISINS.items():
        assert isin.startswith("US"), f"{ticker} ISIN {isin!r} missing 'US' prefix"
        assert len(isin) == 12, f"{ticker} ISIN {isin!r} not 12 chars"


def test_sp500_all_members_have_isin_entry() -> None:
    for m in SP500_MEMBERS:
        assert m.ticker in SP500_ISINS
        assert SP500_ISINS[m.ticker] == m.isin


@pytest.mark.asyncio
async def test_fetch_constituents_uses_static_members_with_yfinance_mock() -> None:
    """Drive a 2-member adapter through a fully-mocked yfinance pipeline."""
    members = (
        _Member("AAPL", "APPLE INC", "US0378331005"),
        _Member("DEAD", "MYSTERY CORP", "US9999991009"),
    )

    async def _fake_yf(ticker: str) -> dict[str, Any]:
        if ticker == "DEAD":
            return {}
        return _aapl_info()

    with patch.object(sp500_module, "_fetch_yf_info", _fake_yf):
        idx = await SP500Adapter(members=members).fetch_constituents()

    assert idx.name == "S&P 500"
    assert idx.country == "US"
    # Static-map driven: every member produces a row even on yfinance failure.
    assert len(idx.constituents) == 2
    tickers = [c.ticker for c in idx.constituents]
    assert tickers == ["AAPL", "DEAD"]
    assert all(c.isin and c.isin.startswith("US") for c in idx.constituents)
    assert all(c.country == "US" for c in idx.constituents)
