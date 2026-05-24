"""Unit tests for the BEL 20 adapter (no network)."""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import patch

import pytest

from equity_aggregator.adapters import bel20 as bel20_module
from equity_aggregator.adapters.bel20 import (
    BEL20_ISINS,
    BEL20_MEMBERS,
    BEL20Adapter,
    _build_constituent,
    _fetch_member,
    _Member,
    _resolve_isin_from_yfinance,
)


def _abi_info() -> dict[str, Any]:
    return {
        "longName": "Anheuser-Busch InBev SA/NV",
        "shortName": "AB INBEV",
        "currentPrice": 71.9,
        "regularMarketPrice": 71.9,
        "previousClose": 71.42,
        "currency": "EUR",
        "country": "Belgium",
        "sector": "Consumer Defensive",
        "beta": 0.786,
        "marketCap": 139_222_548_480,
        "dividendYield": 1.6,
        "exDividendDate": 1778112000,
        "isin": None,
    }


def test_build_constituent_maps_yfinance_fields() -> None:
    member = _Member("ABI.BR", "Anheuser-Busch InBev SA/NV", "BE0974293251")
    c = _build_constituent(member, _abi_info(), figi_record=None)

    assert c.ticker == "ABI.BR"
    assert c.name == "Anheuser-Busch InBev SA/NV"
    assert c.country == "BE"
    assert c.currency == "EUR"
    assert c.price == pytest.approx(71.9)
    assert c.sector == "Consumer Defensive"
    assert c.beta == pytest.approx(0.786)
    assert c.market_cap == pytest.approx(139_222_548_480.0)
    assert c.ttm_div_yield == pytest.approx(1.6)
    # ISIN falls back to the static map when yfinance returns None.
    assert c.isin == "BE0974293251"
    assert c.isin_source == "static"
    # exDividendDate epoch decodes to a real date.
    assert c.ex_div_date is not None
    assert c.ex_div_date.year == 2026
    assert c.ex_div_date.month == 5


def test_build_constituent_prefers_yfinance_isin_when_present() -> None:
    member = _Member("ABI.BR", "Anheuser-Busch InBev SA/NV", "BE0000FROMSTATIC")
    info = _abi_info() | {"isin": "BE0000FROMYFINANCE"}
    c = _build_constituent(member, info, figi_record=None)
    assert c.isin == "BE0000FROMYFINANCE"
    assert c.isin_source == "yfinance"


def test_build_constituent_treats_yfinance_dash_as_missing() -> None:
    member = _Member("ABI.BR", "Anheuser-Busch InBev SA/NV", "BE0974293251")
    info = _abi_info() | {"isin": "-"}
    c = _build_constituent(member, info, figi_record=None)
    assert c.isin == "BE0974293251"
    assert c.isin_source == "static"


def test_build_constituent_uses_openfigi_isin_when_present() -> None:
    member = _Member("ABI.BR", "Anheuser-Busch InBev SA/NV", "BE0000FROMSTATIC")
    info = _abi_info() | {"isin": None}
    figi = {
        "figi": "BBG000BH5G46",
        "name": "ANHEUSER BUSCH INBEV",
        "isin": "BE0000FROMFIGI",
    }
    c = _build_constituent(member, info, figi_record=figi)
    assert c.isin == "BE0000FROMFIGI"
    assert c.isin_source == "openfigi"


def test_resolve_isin_from_yfinance_handles_garbage() -> None:
    assert _resolve_isin_from_yfinance({}) is None
    assert _resolve_isin_from_yfinance({"isin": None}) is None
    assert _resolve_isin_from_yfinance({"isin": ""}) is None
    assert _resolve_isin_from_yfinance({"isin": "-"}) is None
    assert _resolve_isin_from_yfinance({"isin": "  -  "}) is None
    assert _resolve_isin_from_yfinance({"isin": " BE0974293251 "}) == "BE0974293251"


@pytest.mark.asyncio
async def test_fetch_member_survives_total_failure() -> None:
    """When both yfinance and OpenFIGI fail/return empty, still produce a row."""
    member = _Member("XYZ.BR", "Mystery Corp", "BE0000MYSTERY1")

    async def _empty_yf(_: str) -> dict[str, Any]:
        return {}

    async def _none_figi(*_: Any, **__: Any) -> dict[str, Any] | None:
        return None

    with (
        patch.object(bel20_module, "_fetch_yf_info", _empty_yf),
        patch.object(bel20_module, "_fetch_openfigi", _none_figi),
    ):
        c = await _fetch_member(client=None, member=member)  # type: ignore[arg-type]

    assert c.ticker == "XYZ.BR"
    assert c.name == "Mystery Corp"
    assert c.isin == "BE0000MYSTERY1"
    assert c.isin_source == "static"
    assert c.country == "BE"
    assert c.price is None
    assert c.sector is None


def test_bel20_adapter_has_20_members() -> None:
    assert len(BEL20_MEMBERS) == 20
    tickers = [m.ticker for m in BEL20_MEMBERS]
    assert len(set(tickers)) == 20, "duplicate tickers in BEL20_MEMBERS"
    assert all(t.endswith(".BR") for t in tickers)


def test_bel20_adapter_is_instantiable() -> None:
    adapter = BEL20Adapter()
    assert adapter.name == "BEL 20"
    assert adapter.country == "BE"
    assert callable(adapter.fetch_constituents)


def test_bel20_all_members_have_isin_entry() -> None:
    """Every member ticker must have a corresponding entry in BEL20_ISINS."""
    for member in BEL20_MEMBERS:
        assert member.ticker in BEL20_ISINS, (
            f"{member.ticker} missing from BEL20_ISINS"
        )


def test_bel20_isins_are_valid_iso6166_and_mostly_belgian() -> None:
    """All ISINs match ISO 6166 format; at least 16 of 20 are BE-prefixed.

    The BEL 20 includes a small number of non-Belgian-domiciled members
    (e.g. argenx — NL, Aperam — LU) that are listed on Euronext Brussels.
    """
    iso6166 = re.compile(r"^[A-Z]{2}[A-Z0-9]{10}$")
    for ticker, isin in BEL20_ISINS.items():
        assert iso6166.match(isin), (
            f"{ticker} has ISIN {isin!r}, not valid ISO 6166"
        )
    be_count = sum(1 for isin in BEL20_ISINS.values() if isin.startswith("BE"))
    assert be_count >= 16, (
        f"only {be_count}/20 BEL 20 ISINs are BE-prefixed (expected ≥16)"
    )


def test_bel20_currency_on_mock_output() -> None:
    """Currency field from yfinance mock is EUR for BEL 20 constituents."""
    member = _Member("KBC.BR", "KBC Group NV", "BE0003565737")
    info = {
        "longName": "KBC Group NV",
        "currentPrice": 112.6,
        "currency": "EUR",
        "sector": "Financial Services",
        "isin": None,
    }
    c = _build_constituent(member, info, figi_record=None)
    assert c.currency == "EUR"
    assert c.country == "BE"


def test_bel20_country_is_be_for_all_members() -> None:
    """All BEL 20 constituents must report country == 'BE' (listing venue)."""
    for member in BEL20_MEMBERS:
        info: dict[str, Any] = {"longName": member.name, "currency": "EUR"}
        c = _build_constituent(member, info, figi_record=None)
        assert c.country == "BE", (
            f"{member.ticker} has country={c.country!r}, expected 'BE'"
        )
