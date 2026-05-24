"""Unit tests for the STI adapter (no network)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from equity_aggregator.adapters import sti as sti_module
from equity_aggregator.adapters.sti import (
    STI_ISINS,
    STI_MEMBERS,
    STIAdapter,
    _build_constituent,
    _fetch_member,
    _Member,
    _resolve_isin_from_yfinance,
)


def _dbs_info() -> dict[str, Any]:
    return {
        "longName": "DBS Group Holdings Ltd",
        "shortName": "DBS",
        "currentPrice": 62.1,
        "regularMarketPrice": 62.1,
        "previousClose": 61.75,
        "currency": "SGD",
        "country": "Singapore",
        "sector": "Financial Services",
        "beta": 0.267,
        "marketCap": 176_217_112_576,
        "dividendYield": 5.22,
        "exDividendDate": 1778457600,
        "isin": None,
    }


def test_build_constituent_maps_yfinance_fields() -> None:
    member = _Member("D05.SI", "DBS Group Holdings Ltd", "SG1L01001701")
    c = _build_constituent(member, _dbs_info(), figi_record=None)

    assert c.ticker == "D05.SI"
    assert c.name == "DBS Group Holdings Ltd"
    assert c.country == "SG"
    assert c.currency == "SGD"
    assert c.price == pytest.approx(62.1)
    assert c.sector == "Financial Services"
    assert c.beta == pytest.approx(0.267)
    assert c.market_cap == pytest.approx(176_217_112_576.0)
    assert c.ttm_div_yield == pytest.approx(5.22)
    # ISIN falls back to the static map when yfinance returns None.
    assert c.isin == "SG1L01001701"
    assert c.isin_source == "static"
    # exDividendDate epoch decodes to a real date.
    assert c.ex_div_date is not None
    assert c.ex_div_date.year == 2026
    assert c.ex_div_date.month == 5


def test_build_constituent_prefers_yfinance_isin_when_present() -> None:
    member = _Member("D05.SI", "DBS Group Holdings Ltd", "SG0000FROMSTATIC")
    info = _dbs_info() | {"isin": "SG0000FROMYFINANCE"}
    c = _build_constituent(member, info, figi_record=None)
    assert c.isin == "SG0000FROMYFINANCE"
    assert c.isin_source == "yfinance"


def test_build_constituent_treats_yfinance_dash_as_missing() -> None:
    member = _Member("D05.SI", "DBS Group Holdings Ltd", "SG1L01001701")
    info = _dbs_info() | {"isin": "-"}
    c = _build_constituent(member, info, figi_record=None)
    assert c.isin == "SG1L01001701"
    assert c.isin_source == "static"


def test_build_constituent_uses_openfigi_isin_when_present() -> None:
    member = _Member("D05.SI", "DBS Group Holdings Ltd", "SG0000FROMSTATIC")
    info = _dbs_info() | {"isin": None}
    figi = {
        "figi": "BBG000BFDQ31",
        "name": "DBS GROUP HOLDINGS",
        "isin": "SG0000FROMFIGI",
    }
    c = _build_constituent(member, info, figi_record=figi)
    assert c.isin == "SG0000FROMFIGI"
    assert c.isin_source == "openfigi"


def test_resolve_isin_from_yfinance_handles_garbage() -> None:
    assert _resolve_isin_from_yfinance({}) is None
    assert _resolve_isin_from_yfinance({"isin": None}) is None
    assert _resolve_isin_from_yfinance({"isin": ""}) is None
    assert _resolve_isin_from_yfinance({"isin": "-"}) is None
    assert _resolve_isin_from_yfinance({"isin": "  -  "}) is None
    assert _resolve_isin_from_yfinance({"isin": " SG1L01001701 "}) == "SG1L01001701"


@pytest.mark.asyncio
async def test_fetch_member_survives_total_failure() -> None:
    """When both yfinance and OpenFIGI fail/return empty, still produce a row."""
    member = _Member("XYZ.SI", "Mystery Corp", "SG0000MYSTERY1")

    async def _empty_yf(_: str) -> dict[str, Any]:
        return {}

    async def _none_figi(*_: Any, **__: Any) -> dict[str, Any] | None:
        return None

    with (
        patch.object(sti_module, "_fetch_yf_info", _empty_yf),
        patch.object(sti_module, "_fetch_openfigi", _none_figi),
    ):
        c = await _fetch_member(client=None, member=member)  # type: ignore[arg-type]

    assert c.ticker == "XYZ.SI"
    assert c.name == "Mystery Corp"
    assert c.isin == "SG0000MYSTERY1"
    assert c.isin_source == "static"
    assert c.country == "SG"
    assert c.price is None
    assert c.sector is None


def test_sti_adapter_has_30_members() -> None:
    assert len(STI_MEMBERS) == 30
    tickers = [m.ticker for m in STI_MEMBERS]
    assert len(set(tickers)) == 30, "duplicate tickers in STI_MEMBERS"
    assert all(t.endswith(".SI") for t in tickers)


def test_sti_adapter_is_instantiable() -> None:
    adapter = STIAdapter()
    assert adapter.name == "STI"
    assert adapter.country == "SG"
    assert callable(adapter.fetch_constituents)


def test_sti_all_members_have_isin_entry() -> None:
    """Every member ticker must have a corresponding entry in STI_ISINS."""
    for member in STI_MEMBERS:
        assert member.ticker in STI_ISINS, (
            f"{member.ticker} missing from STI_ISINS"
        )


def test_sti_currency_on_mock_output() -> None:
    """Currency field from yfinance mock is SGD for domestic STI constituents."""
    member = _Member(
        "O39.SI",
        "Oversea-Chinese Banking Corporation Limited",
        "SG1S04926220",
    )
    info = {
        "longName": "Oversea-Chinese Banking Corporation Limited",
        "currentPrice": 23.53,
        "currency": "SGD",
        "sector": "Financial Services",
        "isin": None,
    }
    c = _build_constituent(member, info, figi_record=None)
    assert c.currency == "SGD"
    assert c.country == "SG"


def test_sti_country_is_sg_for_all_members() -> None:
    """All STI constituents must report country == 'SG' (listing venue)."""
    for member in STI_MEMBERS:
        info: dict[str, Any] = {"longName": member.name, "currency": "SGD"}
        c = _build_constituent(member, info, figi_record=None)
        assert c.country == "SG", (
            f"{member.ticker} has country={c.country!r}, expected 'SG'"
        )
