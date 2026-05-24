"""Unit tests for the IBEX 35 adapter (no network)."""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import patch

import pytest

from equity_aggregator.adapters import ibex35 as ibex35_module
from equity_aggregator.adapters.ibex35 import (
    IBEX35_ISINS,
    IBEX35_MEMBERS,
    IBEX35Adapter,
    _build_constituent,
    _fetch_member,
    _Member,
    _resolve_isin_from_yfinance,
)


def _san_info() -> dict[str, Any]:
    return {
        "longName": "Banco Santander, S.A.",
        "shortName": "BANCO SANTANDER S.A.",
        "currentPrice": 10.428,
        "regularMarketPrice": 10.428,
        "previousClose": 10.456,
        "currency": "EUR",
        "country": "Spain",
        "sector": "Financial Services",
        "beta": 0.955,
        "marketCap": 150_166_732_800,
        "dividendYield": 2.4,
        "exDividendDate": 1777507200,
        "isin": None,
    }


def test_build_constituent_maps_yfinance_fields() -> None:
    member = _Member("SAN.MC", "Banco Santander S.A.", "ES0113900J37")
    c = _build_constituent(member, _san_info(), figi_record=None)

    assert c.ticker == "SAN.MC"
    assert c.name.startswith("Banco Santander")
    assert c.country == "ES"
    assert c.currency == "EUR"
    assert c.price == pytest.approx(10.428)
    assert c.sector == "Financial Services"
    assert c.beta == pytest.approx(0.955)
    assert c.market_cap == pytest.approx(150_166_732_800.0)
    assert c.ttm_div_yield == pytest.approx(2.4)
    assert c.isin == "ES0113900J37"
    assert c.isin_source == "static"
    assert c.ex_div_date is not None
    assert c.ex_div_date.year == 2026


def test_build_constituent_prefers_yfinance_isin_when_present() -> None:
    member = _Member("SAN.MC", "Santander", "ES000FROMSTATIC")
    info = _san_info() | {"isin": "ES000FROMYFINANCE"}
    c = _build_constituent(member, info, figi_record=None)
    assert c.isin == "ES000FROMYFINANCE"
    assert c.isin_source == "yfinance"


def test_build_constituent_treats_yfinance_dash_as_missing() -> None:
    member = _Member("SAN.MC", "Santander", "ES0113900J37")
    info = _san_info() | {"isin": "-"}
    c = _build_constituent(member, info, figi_record=None)
    assert c.isin == "ES0113900J37"
    assert c.isin_source == "static"


def test_build_constituent_uses_openfigi_isin_when_present() -> None:
    member = _Member("SAN.MC", "Santander", "ES000FROMSTATIC")
    info = _san_info() | {"isin": None}
    figi = {
        "figi": "BBG000K65GY1",
        "name": "BANCO SANTANDER SA",
        "isin": "ES000FROMFIGI",
    }
    c = _build_constituent(member, info, figi_record=figi)
    assert c.isin == "ES000FROMFIGI"
    assert c.isin_source == "openfigi"


def test_resolve_isin_from_yfinance_handles_garbage() -> None:
    assert _resolve_isin_from_yfinance({}) is None
    assert _resolve_isin_from_yfinance({"isin": None}) is None
    assert _resolve_isin_from_yfinance({"isin": ""}) is None
    assert _resolve_isin_from_yfinance({"isin": "-"}) is None
    assert _resolve_isin_from_yfinance({"isin": "  -  "}) is None
    assert _resolve_isin_from_yfinance({"isin": " ES0113900J37 "}) == "ES0113900J37"


@pytest.mark.asyncio
async def test_fetch_member_survives_total_failure() -> None:
    """When both yfinance and OpenFIGI fail/return empty, still produce a row."""
    member = _Member("XYZ.MC", "Mystery Corp", "ES000MYSTERY1")

    async def _empty_yf(_: str) -> dict[str, Any]:
        return {}

    async def _none_figi(*_: Any, **__: Any) -> dict[str, Any] | None:
        return None

    with (
        patch.object(ibex35_module, "_fetch_yf_info", _empty_yf),
        patch.object(ibex35_module, "_fetch_openfigi", _none_figi),
    ):
        c = await _fetch_member(client=None, member=member)  # type: ignore[arg-type]

    assert c.ticker == "XYZ.MC"
    assert c.name == "Mystery Corp"
    assert c.isin == "ES000MYSTERY1"
    assert c.isin_source == "static"
    assert c.country == "ES"
    assert c.price is None
    assert c.sector is None


@pytest.mark.asyncio
async def test_one_ticker_failing_does_not_abort_batch() -> None:
    """If one ticker raises in yfinance, the other 34 still come back."""
    calls: list[str] = []

    async def _yf(ticker: str) -> dict[str, Any]:
        calls.append(ticker)
        if ticker == "SAN.MC":
            return {}
        return {
            "longName": f"Stub {ticker}",
            "currentPrice": 100.0,
            "currency": "EUR",
            "sector": "Industrials",
        }

    async def _figi(*_: Any, **__: Any) -> dict[str, Any] | None:
        return None

    with (
        patch.object(ibex35_module, "_fetch_yf_info", _yf),
        patch.object(ibex35_module, "_fetch_openfigi", _figi),
    ):
        idx = await IBEX35Adapter().fetch_constituents()

    assert len(idx.constituents) == 35
    bad = next(c for c in idx.constituents if c.ticker == "SAN.MC")
    assert bad.isin == "ES0113900J37"
    assert bad.isin_source == "static"
    good = [c for c in idx.constituents if c.ticker != "SAN.MC"]
    assert all(c.price == pytest.approx(100.0) for c in good)
    assert all(c.currency == "EUR" for c in good)


def test_ibex35_adapter_has_35_members() -> None:
    assert len(IBEX35_MEMBERS) == 35
    tickers = [m.ticker for m in IBEX35_MEMBERS]
    assert len(set(tickers)) == 35, "duplicate tickers in IBEX35_MEMBERS"
    assert all(t.endswith(".MC") for t in tickers)


def test_ibex35_isin_map_covers_every_member() -> None:
    assert set(IBEX35_ISINS.keys()) == {m.ticker for m in IBEX35_MEMBERS}
    assert len(IBEX35_ISINS) == 35
    pattern = re.compile(r"^[A-Z]{2}[A-Z0-9]{10}$")
    for ticker, isin in IBEX35_ISINS.items():
        assert pattern.match(isin), f"{ticker} has malformed ISIN {isin!r}"
    es_count = sum(1 for isin in IBEX35_ISINS.values() if isin.startswith("ES"))
    assert es_count >= 30, f"expected >= 30 ES ISINs, got {es_count}"


def test_ibex35_adapter_is_instantiable() -> None:
    adapter = IBEX35Adapter()
    assert adapter.name == "IBEX 35"
    assert adapter.country == "ES"
    assert callable(adapter.fetch_constituents)


@pytest.mark.asyncio
async def test_country_is_es_for_all_constituents() -> None:
    """Every Constituent the adapter produces is tagged country=ES, even
    when the issuer is domiciled elsewhere (ArcelorMittal LU, Ferrovial NL)."""

    async def _yf(_: str) -> dict[str, Any]:
        return {"longName": "x", "currency": "EUR"}

    async def _figi(*_: Any, **__: Any) -> dict[str, Any] | None:
        return None

    with (
        patch.object(ibex35_module, "_fetch_yf_info", _yf),
        patch.object(ibex35_module, "_fetch_openfigi", _figi),
    ):
        idx = await IBEX35Adapter().fetch_constituents()

    assert all(c.country == "ES" for c in idx.constituents)
    assert all(c.currency == "EUR" for c in idx.constituents)


@pytest.mark.asyncio
async def test_isin_source_is_static_when_no_upstream_isin() -> None:
    """Per current findings (yfinance returns no ISIN, OpenFIGI doesn't
    return ISIN), every constituent's isin_source should be 'static'."""

    async def _yf(_: str) -> dict[str, Any]:
        return {"currency": "EUR"}

    async def _figi(*_: Any, **__: Any) -> dict[str, Any] | None:
        return None

    with (
        patch.object(ibex35_module, "_fetch_yf_info", _yf),
        patch.object(ibex35_module, "_fetch_openfigi", _figi),
    ):
        idx = await IBEX35Adapter().fetch_constituents()

    assert all(c.isin_source == "static" for c in idx.constituents)
    assert all(c.isin for c in idx.constituents)
