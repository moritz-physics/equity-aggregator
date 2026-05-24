"""Unit tests for the WIG20 adapter (no network)."""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import patch

import pytest

from equity_aggregator.adapters import wig20 as wig20_module
from equity_aggregator.adapters.wig20 import (
    WIG20_ISINS,
    WIG20_MEMBERS,
    WIG20Adapter,
    _build_constituent,
    _fetch_member,
    _Member,
    _resolve_isin_from_yfinance,
)


def _pkn_info() -> dict[str, Any]:
    return {
        "longName": "Orlen S.A.",
        "shortName": "PKNORLEN",
        "currentPrice": 143.34,
        "regularMarketPrice": 143.34,
        "previousClose": 142.32,
        "currency": "PLN",
        "country": "Poland",
        "sector": "Energy",
        "beta": 0.469,
        "marketCap": 166_409_437_184,
        "dividendYield": 5.58,
        "exDividendDate": 1781654400,
        "isin": None,
    }


def test_build_constituent_maps_yfinance_fields() -> None:
    member = _Member("PKN.WA", "Orlen S.A.", "PLPKN0000018")
    c = _build_constituent(member, _pkn_info(), figi_record=None)

    assert c.ticker == "PKN.WA"
    assert c.name == "Orlen S.A."
    assert c.country == "PL"
    assert c.currency == "PLN"
    assert c.price == pytest.approx(143.34)
    assert c.sector == "Energy"
    assert c.beta == pytest.approx(0.469)
    assert c.market_cap == pytest.approx(166_409_437_184.0)
    assert c.ttm_div_yield == pytest.approx(5.58)
    assert c.isin == "PLPKN0000018"
    assert c.isin_source == "static"
    assert c.ex_div_date is not None
    assert c.ex_div_date.year == 2026


def test_build_constituent_prefers_yfinance_isin_when_present() -> None:
    member = _Member("PKN.WA", "Orlen", "PLPKNFROMSTAT")
    info = _pkn_info() | {"isin": "PLPKNFROMYFIN"}
    c = _build_constituent(member, info, figi_record=None)
    assert c.isin == "PLPKNFROMYFIN"
    assert c.isin_source == "yfinance"


def test_build_constituent_treats_yfinance_dash_as_missing() -> None:
    member = _Member("PKN.WA", "Orlen", "PLPKN0000018")
    info = _pkn_info() | {"isin": "-"}
    c = _build_constituent(member, info, figi_record=None)
    assert c.isin == "PLPKN0000018"
    assert c.isin_source == "static"


def test_build_constituent_uses_openfigi_isin_when_present() -> None:
    member = _Member("PKN.WA", "Orlen", "PLPKNFROMSTAT")
    info = _pkn_info() | {"isin": None}
    figi = {
        "figi": "BBG000BLBPB7",
        "name": "ORLEN SA",
        "isin": "PLPKNFROMFIGI",
    }
    c = _build_constituent(member, info, figi_record=figi)
    assert c.isin == "PLPKNFROMFIGI"
    assert c.isin_source == "openfigi"


def test_resolve_isin_from_yfinance_handles_garbage() -> None:
    assert _resolve_isin_from_yfinance({}) is None
    assert _resolve_isin_from_yfinance({"isin": None}) is None
    assert _resolve_isin_from_yfinance({"isin": ""}) is None
    assert _resolve_isin_from_yfinance({"isin": "-"}) is None
    assert _resolve_isin_from_yfinance({"isin": "  -  "}) is None
    assert _resolve_isin_from_yfinance({"isin": " PLPKN0000018 "}) == "PLPKN0000018"


@pytest.mark.asyncio
async def test_fetch_member_survives_total_failure() -> None:
    """When both yfinance and OpenFIGI fail/return empty, still produce a row."""
    member = _Member("XYZ.WA", "Mystery Corp", "PLMYSTERY001")

    async def _empty_yf(_: str) -> dict[str, Any]:
        return {}

    async def _none_figi(*_: Any, **__: Any) -> dict[str, Any] | None:
        return None

    with (
        patch.object(wig20_module, "_fetch_yf_info", _empty_yf),
        patch.object(wig20_module, "_fetch_openfigi", _none_figi),
    ):
        c = await _fetch_member(client=None, member=member)  # type: ignore[arg-type]

    assert c.ticker == "XYZ.WA"
    assert c.name == "Mystery Corp"
    assert c.isin == "PLMYSTERY001"
    assert c.isin_source == "static"
    assert c.country == "PL"
    assert c.price is None
    assert c.sector is None


@pytest.mark.asyncio
async def test_one_ticker_failing_does_not_abort_batch() -> None:
    """If one ticker raises in yfinance, the other 19 still come back."""
    calls: list[str] = []

    async def _yf(ticker: str) -> dict[str, Any]:
        calls.append(ticker)
        if ticker == "PKN.WA":
            return {}
        return {
            "longName": f"Stub {ticker}",
            "currentPrice": 100.0,
            "currency": "PLN",
            "sector": "Industrials",
        }

    async def _figi(*_: Any, **__: Any) -> dict[str, Any] | None:
        return None

    with (
        patch.object(wig20_module, "_fetch_yf_info", _yf),
        patch.object(wig20_module, "_fetch_openfigi", _figi),
    ):
        idx = await WIG20Adapter().fetch_constituents()

    assert len(idx.constituents) == 20
    bad = next(c for c in idx.constituents if c.ticker == "PKN.WA")
    assert bad.isin == "PLPKN0000018"
    assert bad.isin_source == "static"
    good = [c for c in idx.constituents if c.ticker != "PKN.WA"]
    assert all(c.price == pytest.approx(100.0) for c in good)
    assert all(c.currency == "PLN" for c in good)


def test_wig20_adapter_has_20_members() -> None:
    assert len(WIG20_MEMBERS) == 20
    tickers = [m.ticker for m in WIG20_MEMBERS]
    assert len(set(tickers)) == 20, "duplicate tickers in WIG20_MEMBERS"
    assert all(t.endswith(".WA") for t in tickers)


def test_wig20_isin_map_covers_every_member() -> None:
    assert set(WIG20_ISINS.keys()) == {m.ticker for m in WIG20_MEMBERS}
    assert len(WIG20_ISINS) == 20
    # ISO 6166: 2 letters + 10 alphanumerics.
    pattern = re.compile(r"^[A-Z]{2}[A-Z0-9]{10}$")
    for ticker, isin in WIG20_ISINS.items():
        assert pattern.match(isin), f"{ticker} has malformed ISIN {isin!r}"
    # The vast majority of WIG20 issuers are Polish-domiciled.
    pl_count = sum(1 for isin in WIG20_ISINS.values() if isin.startswith("PL"))
    assert pl_count >= 15, f"expected >= 15 PL ISINs, got {pl_count}"


def test_wig20_adapter_is_instantiable() -> None:
    adapter = WIG20Adapter()
    assert adapter.name == "WIG20"
    assert adapter.country == "PL"
    assert callable(adapter.fetch_constituents)


@pytest.mark.asyncio
async def test_country_is_pl_for_all_constituents() -> None:
    """Every Constituent the adapter produces is tagged country=PL, even
    when the issuer is domiciled elsewhere (Allegro LU, Pepco LU, Żabka NL)."""

    async def _yf(_: str) -> dict[str, Any]:
        return {"longName": "x", "currency": "PLN"}

    async def _figi(*_: Any, **__: Any) -> dict[str, Any] | None:
        return None

    with (
        patch.object(wig20_module, "_fetch_yf_info", _yf),
        patch.object(wig20_module, "_fetch_openfigi", _figi),
    ):
        idx = await WIG20Adapter().fetch_constituents()

    assert all(c.country == "PL" for c in idx.constituents)
    assert all(c.currency == "PLN" for c in idx.constituents)


@pytest.mark.asyncio
async def test_isin_source_is_static_when_no_upstream_isin() -> None:
    """Per current findings (yfinance returns no ISIN, OpenFIGI doesn't
    return ISIN), every constituent's isin_source should be 'static'."""

    async def _yf(_: str) -> dict[str, Any]:
        return {"currency": "PLN"}

    async def _figi(*_: Any, **__: Any) -> dict[str, Any] | None:
        return None

    with (
        patch.object(wig20_module, "_fetch_yf_info", _yf),
        patch.object(wig20_module, "_fetch_openfigi", _figi),
    ):
        idx = await WIG20Adapter().fetch_constituents()

    assert all(c.isin_source == "static" for c in idx.constituents)
    assert all(c.isin for c in idx.constituents)
