"""Unit tests for the CAC 40 adapter (no network)."""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import patch

import pytest

from equity_aggregator.adapters import cac40 as cac40_module
from equity_aggregator.adapters.cac40 import (
    CAC40_ISINS,
    CAC40_MEMBERS,
    CAC40Adapter,
    _build_constituent,
    _fetch_member,
    _Member,
    _resolve_isin_from_yfinance,
)


def _lvmh_info() -> dict[str, Any]:
    return {
        "longName": "LVMH Moët Hennessy - Louis Vuitton, Société Européenne",
        "shortName": "LVMH",
        "currentPrice": 472.6,
        "regularMarketPrice": 472.6,
        "previousClose": 473.55,
        "currency": "EUR",
        "country": "France",
        "sector": "Consumer Cyclical",
        "beta": 0.835,
        "marketCap": 233_500_901_376,
        "dividendYield": 2.75,
        "exDividendDate": 1777334400,
        "isin": None,
    }


def test_build_constituent_maps_yfinance_fields() -> None:
    member = _Member("MC.PA", "LVMH Moët Hennessy Louis Vuitton SE", "FR0000121014")
    c = _build_constituent(member, _lvmh_info(), figi_record=None)

    assert c.ticker == "MC.PA"
    assert c.name.startswith("LVMH")
    assert c.country == "FR"
    assert c.currency == "EUR"
    assert c.price == pytest.approx(472.6)
    assert c.sector == "Consumer Cyclical"
    assert c.beta == pytest.approx(0.835)
    assert c.market_cap == pytest.approx(233_500_901_376.0)
    assert c.ttm_div_yield == pytest.approx(2.75)
    assert c.isin == "FR0000121014"
    assert c.isin_source == "static"
    assert c.ex_div_date is not None
    assert c.ex_div_date.year == 2026


def test_build_constituent_prefers_yfinance_isin_when_present() -> None:
    member = _Member("MC.PA", "LVMH", "FR000FROMSTATIC")
    info = _lvmh_info() | {"isin": "FR000FROMYFINANCE"}
    c = _build_constituent(member, info, figi_record=None)
    assert c.isin == "FR000FROMYFINANCE"
    assert c.isin_source == "yfinance"


def test_build_constituent_treats_yfinance_dash_as_missing() -> None:
    member = _Member("MC.PA", "LVMH", "FR0000121014")
    info = _lvmh_info() | {"isin": "-"}
    c = _build_constituent(member, info, figi_record=None)
    assert c.isin == "FR0000121014"
    assert c.isin_source == "static"


def test_build_constituent_uses_openfigi_isin_when_present() -> None:
    member = _Member("MC.PA", "LVMH", "FR000FROMSTATIC")
    info = _lvmh_info() | {"isin": None}
    figi = {
        "figi": "BBG000K4ND22",
        "name": "LVMH MOET HENNESSY LOUIS VUI",
        "isin": "FR000FROMFIGI",
    }
    c = _build_constituent(member, info, figi_record=figi)
    assert c.isin == "FR000FROMFIGI"
    assert c.isin_source == "openfigi"


def test_resolve_isin_from_yfinance_handles_garbage() -> None:
    assert _resolve_isin_from_yfinance({}) is None
    assert _resolve_isin_from_yfinance({"isin": None}) is None
    assert _resolve_isin_from_yfinance({"isin": ""}) is None
    assert _resolve_isin_from_yfinance({"isin": "-"}) is None
    assert _resolve_isin_from_yfinance({"isin": "  -  "}) is None
    assert _resolve_isin_from_yfinance({"isin": " FR0000121014 "}) == "FR0000121014"


@pytest.mark.asyncio
async def test_fetch_member_survives_total_failure() -> None:
    """When both yfinance and OpenFIGI fail/return empty, still produce a row."""
    member = _Member("XYZ.PA", "Mystery Corp", "FR000MYSTERY1")

    async def _empty_yf(_: str) -> dict[str, Any]:
        return {}

    async def _none_figi(*_: Any, **__: Any) -> dict[str, Any] | None:
        return None

    with (
        patch.object(cac40_module, "_fetch_yf_info", _empty_yf),
        patch.object(cac40_module, "_fetch_openfigi", _none_figi),
    ):
        c = await _fetch_member(client=None, member=member)  # type: ignore[arg-type]

    assert c.ticker == "XYZ.PA"
    assert c.name == "Mystery Corp"
    assert c.isin == "FR000MYSTERY1"
    assert c.isin_source == "static"
    assert c.country == "FR"
    assert c.price is None
    assert c.sector is None


@pytest.mark.asyncio
async def test_one_ticker_failing_does_not_abort_batch() -> None:
    """If one ticker raises in yfinance, the other 39 still come back."""
    calls: list[str] = []

    async def _yf(ticker: str) -> dict[str, Any]:
        calls.append(ticker)
        if ticker == "MC.PA":
            return {}  # simulate total upstream failure for one ticker
        return {
            "longName": f"Stub {ticker}",
            "currentPrice": 100.0,
            "currency": "EUR",
            "sector": "Industrials",
        }

    async def _figi(*_: Any, **__: Any) -> dict[str, Any] | None:
        return None

    with (
        patch.object(cac40_module, "_fetch_yf_info", _yf),
        patch.object(cac40_module, "_fetch_openfigi", _figi),
    ):
        idx = await CAC40Adapter().fetch_constituents()

    assert len(idx.constituents) == 40
    bad = next(c for c in idx.constituents if c.ticker == "MC.PA")
    assert bad.isin == "FR0000121014"
    assert bad.isin_source == "static"
    # The remaining 39 picked up the stub price.
    good = [c for c in idx.constituents if c.ticker != "MC.PA"]
    assert all(c.price == pytest.approx(100.0) for c in good)


def test_cac40_adapter_has_40_members() -> None:
    assert len(CAC40_MEMBERS) == 40
    tickers = [m.ticker for m in CAC40_MEMBERS]
    assert len(set(tickers)) == 40, "duplicate tickers in CAC40_MEMBERS"


def test_cac40_isin_map_covers_every_member() -> None:
    assert set(CAC40_ISINS.keys()) == {m.ticker for m in CAC40_MEMBERS}
    assert len(CAC40_ISINS) == 40
    # ISO 6166: 2 letters + 10 alphanumerics.
    pattern = re.compile(r"^[A-Z]{2}[A-Z0-9]{10}$")
    for ticker, isin in CAC40_ISINS.items():
        assert pattern.match(isin), f"{ticker} has malformed ISIN {isin!r}"
    # The vast majority of CAC 40 issuers are French-domiciled.
    fr_count = sum(1 for isin in CAC40_ISINS.values() if isin.startswith("FR"))
    assert fr_count >= 35, f"expected >= 35 FR ISINs, got {fr_count}"


def test_cac40_adapter_is_instantiable() -> None:
    adapter = CAC40Adapter()
    assert adapter.name == "CAC 40"
    assert adapter.country == "FR"
    assert callable(adapter.fetch_constituents)


@pytest.mark.asyncio
async def test_country_is_fr_for_all_constituents() -> None:
    """Every Constituent the adapter produces is tagged country=FR, even
    when the issuer is domiciled elsewhere (Airbus NL, ArcelorMittal LU)."""

    async def _yf(_: str) -> dict[str, Any]:
        return {"longName": "x", "currency": "EUR"}

    async def _figi(*_: Any, **__: Any) -> dict[str, Any] | None:
        return None

    with (
        patch.object(cac40_module, "_fetch_yf_info", _yf),
        patch.object(cac40_module, "_fetch_openfigi", _figi),
    ):
        idx = await CAC40Adapter().fetch_constituents()

    assert all(c.country == "FR" for c in idx.constituents)


@pytest.mark.asyncio
async def test_isin_source_is_static_when_no_upstream_isin() -> None:
    """Per current findings (yfinance returns no ISIN, OpenFIGI doesn't
    return ISIN), every constituent's isin_source should be 'static'."""

    async def _yf(_: str) -> dict[str, Any]:
        return {"currency": "EUR"}

    async def _figi(*_: Any, **__: Any) -> dict[str, Any] | None:
        return None

    with (
        patch.object(cac40_module, "_fetch_yf_info", _yf),
        patch.object(cac40_module, "_fetch_openfigi", _figi),
    ):
        idx = await CAC40Adapter().fetch_constituents()

    assert all(c.isin_source == "static" for c in idx.constituents)
    assert all(c.isin for c in idx.constituents)
