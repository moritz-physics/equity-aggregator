"""Unit tests for the FTSE 100 adapter (no network)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import httpx
import pytest

from equity_aggregator.adapters import ftse100 as ftse100_module
from equity_aggregator.adapters.ftse100 import (
    FTSE100Adapter,
    _build_constituent,
    _fetch_one,
    _fetch_tickers_from_wikipedia,
    _normalise_price,
    _with_suffix,
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


# ---------------------- _with_suffix ----------------------------------------


def test_with_suffix_appends_dot_l() -> None:
    assert _with_suffix("SHEL") == "SHEL.L"


def test_with_suffix_idempotent() -> None:
    assert _with_suffix("SHEL.L") == "SHEL.L"


def test_with_suffix_uppercases() -> None:
    assert _with_suffix("shel") == "SHEL.L"


# ---------------------- _build_constituent ----------------------------------


def test_build_constituent_normalises_gbp_pence() -> None:
    c = _build_constituent("SHEL.L", _shel_info())
    assert c is not None
    assert c.ticker == "SHEL.L"
    assert c.country == "GB"
    assert c.currency == "GBP"
    assert c.price == pytest.approx(32.05)
    assert c.sector == "Energy"
    assert c.beta == pytest.approx(-0.24)
    assert c.market_cap == pytest.approx(178_350_866_432.0)
    assert c.ttm_div_yield == pytest.approx(3.63)
    assert c.ex_div_date is not None
    assert c.isin is None
    assert c.isin_source is None


def test_build_constituent_no_double_conversion_for_gbp() -> None:
    info = _shel_info() | {
        "currency": "GBP",
        "currentPrice": 25.0,
        "regularMarketPrice": 25.0,
    }
    c = _build_constituent("ABC.L", info)
    assert c is not None
    assert c.price == pytest.approx(25.0)
    assert c.currency == "GBP"


def test_build_constituent_returns_none_on_empty_info() -> None:
    assert _build_constituent("SHEL.L", {}) is None


def test_build_constituent_returns_none_when_quote_type_missing() -> None:
    info = _shel_info() | {"quoteType": None}
    assert _build_constituent("SHEL.L", info) is None


def test_build_constituent_falls_back_to_regular_market_price() -> None:
    info = _shel_info() | {"currentPrice": None}
    c = _build_constituent("SHEL.L", info)
    assert c is not None
    # 3205 GBp → 32.05 GBP
    assert c.price == pytest.approx(32.05)
    assert c.currency == "GBP"


def test_build_constituent_uses_ticker_when_names_missing() -> None:
    info = _shel_info() | {"shortName": None, "longName": None}
    c = _build_constituent("WEIRD.L", info)
    assert c is not None
    assert c.name == "WEIRD.L"


# ---------------------- _fetch_one ------------------------------------------


@pytest.mark.asyncio
async def test_fetch_one_returns_constituent() -> None:
    async def _ok(_: str) -> dict[str, Any]:
        return _shel_info()

    with patch.object(ftse100_module, "_fetch_yf_info", _ok):
        c = await _fetch_one("SHEL.L")

    assert c is not None
    assert c.ticker == "SHEL.L"
    assert c.country == "GB"
    assert c.currency == "GBP"


@pytest.mark.asyncio
async def test_fetch_one_returns_none_on_empty_info() -> None:
    async def _empty(_: str) -> dict[str, Any]:
        return {}

    with patch.object(ftse100_module, "_fetch_yf_info", _empty):
        assert await _fetch_one("DEAD.L") is None


@pytest.mark.asyncio
async def test_fetch_one_returns_none_on_exception() -> None:
    async def _boom(_: str) -> dict[str, Any]:
        raise RuntimeError("network blew up")

    with patch.object(ftse100_module, "_fetch_yf_info", _boom):
        assert await _fetch_one("SHEL.L") is None


# ---------------------- _fetch_tickers_from_wikipedia -----------------------


_FAKE_HTML = """
<html><body>
  <table><tr><th>Unrelated</th></tr><tr><td>x</td></tr></table>
  <table>
    <tr><th>Company</th><th>Ticker</th><th>Sector</th></tr>
    <tr><td>Shell plc</td><td>SHEL</td><td>Energy</td></tr>
    <tr><td>AstraZeneca</td><td>AZN</td><td>Healthcare</td></tr>
    <tr><td>HSBC</td><td>HSBA</td><td>Financials</td></tr>
  </table>
</body></html>
"""


@pytest.mark.asyncio
async def test_fetch_tickers_appends_dot_l_suffix() -> None:
    response = httpx.Response(
        200,
        text=_FAKE_HTML,
        request=httpx.Request("GET", ftse100_module.WIKIPEDIA_URL),
    )

    async def _get(self: httpx.AsyncClient, url: str, **_: Any) -> httpx.Response:
        return response

    with patch.object(httpx.AsyncClient, "get", _get):
        async with httpx.AsyncClient() as client:
            tickers = await _fetch_tickers_from_wikipedia(client)

    assert tickers == ["SHEL.L", "AZN.L", "HSBA.L"]


@pytest.mark.asyncio
async def test_fetch_tickers_raises_on_http_error() -> None:
    response = httpx.Response(
        403,
        text="forbidden",
        request=httpx.Request("GET", ftse100_module.WIKIPEDIA_URL),
    )

    async def _get(self: httpx.AsyncClient, url: str, **_: Any) -> httpx.Response:
        return response

    with patch.object(httpx.AsyncClient, "get", _get):
        async with httpx.AsyncClient() as client:
            with pytest.raises(httpx.HTTPStatusError):
                await _fetch_tickers_from_wikipedia(client)


@pytest.mark.asyncio
async def test_fetch_tickers_raises_when_table_missing() -> None:
    response = httpx.Response(
        200,
        text="<html><body><table><tr><th>X</th></tr><tr><td>1</td></tr></table></body></html>",
        request=httpx.Request("GET", ftse100_module.WIKIPEDIA_URL),
    )

    async def _get(self: httpx.AsyncClient, url: str, **_: Any) -> httpx.Response:
        return response

    with patch.object(httpx.AsyncClient, "get", _get):
        async with httpx.AsyncClient() as client:
            with pytest.raises(RuntimeError, match="constituents table not found"):
                await _fetch_tickers_from_wikipedia(client)


# ---------------------- FTSE100Adapter.fetch_constituents -------------------


@pytest.mark.asyncio
async def test_fetch_constituents_full_flow_with_one_failure() -> None:
    fake_tickers = ["SHEL.L", "AZN.L", "HSBA.L", "DEAD.L"]

    async def _fake_wiki(_client: httpx.AsyncClient) -> list[str]:
        return fake_tickers

    async def _fake_yf(ticker: str) -> dict[str, Any]:
        if ticker == "DEAD.L":
            return {}
        return _shel_info() | {"shortName": f"{ticker} Co"}

    with (
        patch.object(ftse100_module, "_fetch_tickers_from_wikipedia", _fake_wiki),
        patch.object(ftse100_module, "_fetch_yf_info", _fake_yf),
    ):
        idx = await FTSE100Adapter().fetch_constituents()

    assert idx.name == "FTSE 100"
    assert idx.country == "GB"
    assert len(idx.constituents) == 3
    tickers = [c.ticker for c in idx.constituents]
    assert "DEAD.L" not in tickers
    assert all(c.country == "GB" for c in idx.constituents)
    assert all(c.currency == "GBP" for c in idx.constituents)
    assert all(c.isin is None for c in idx.constituents)
    assert all(c.isin_source is None for c in idx.constituents)


@pytest.mark.asyncio
async def test_fetch_constituents_propagates_wikipedia_failure() -> None:
    async def _boom(_client: httpx.AsyncClient) -> list[str]:
        raise httpx.HTTPError("Wikipedia unreachable")

    with patch.object(ftse100_module, "_fetch_tickers_from_wikipedia", _boom):
        with pytest.raises(httpx.HTTPError):
            await FTSE100Adapter().fetch_constituents()


def test_ftse100_adapter_is_instantiable() -> None:
    adapter = FTSE100Adapter()
    assert adapter.name == "FTSE 100"
    assert adapter.country == "GB"
    assert callable(adapter.fetch_constituents)
