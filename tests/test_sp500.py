"""Unit tests for the S&P 500 adapter (no network)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from equity_aggregator.adapters import sp500 as sp500_module
from equity_aggregator.adapters.sp500 import (
    SP500Adapter,
    _build_constituent,
    _fetch_one,
    _fetch_tickers_from_wikipedia,
    _parse_yield,
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
    c = _build_constituent("AAPL", _aapl_info())
    assert c is not None
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
    # ISIN deliberately blank for US tickers.
    assert c.isin is None
    assert c.isin_source is None


def test_build_constituent_returns_none_on_empty_info() -> None:
    assert _build_constituent("AAPL", {}) is None


def test_build_constituent_returns_none_when_quote_type_missing() -> None:
    info = _aapl_info() | {"quoteType": None}
    assert _build_constituent("AAPL", info) is None


def test_build_constituent_falls_back_to_regular_market_price() -> None:
    info = _aapl_info() | {"currentPrice": None}
    c = _build_constituent("AAPL", info)
    assert c is not None
    assert c.price == pytest.approx(308.82)


def test_build_constituent_uses_ticker_when_names_missing() -> None:
    info = _aapl_info() | {"shortName": None, "longName": None}
    c = _build_constituent("WEIRD", info)
    assert c is not None
    assert c.name == "WEIRD"


# ---------------------- _parse_yield ----------------------------------------


def test_parse_yield_converts_decimal_to_percent() -> None:
    assert _parse_yield(0.0194) == pytest.approx(1.94)


def test_parse_yield_drops_zero_and_none() -> None:
    assert _parse_yield(None) is None
    assert _parse_yield(0) is None
    assert _parse_yield(0.0) is None


def test_parse_yield_rejects_garbage() -> None:
    assert _parse_yield("nope") is None


# ---------------------- _fetch_one ------------------------------------------


@pytest.mark.asyncio
async def test_fetch_one_returns_constituent() -> None:
    async def _ok(_: str) -> dict[str, Any]:
        return _aapl_info()

    with patch.object(sp500_module, "_fetch_yf_info", _ok):
        c = await _fetch_one("AAPL")

    assert c is not None
    assert c.ticker == "AAPL"
    assert c.isin is None
    assert c.country == "US"


@pytest.mark.asyncio
async def test_fetch_one_returns_none_on_empty_info() -> None:
    async def _empty(_: str) -> dict[str, Any]:
        return {}

    with patch.object(sp500_module, "_fetch_yf_info", _empty):
        assert await _fetch_one("DEAD") is None


@pytest.mark.asyncio
async def test_fetch_one_returns_none_on_exception() -> None:
    async def _boom(_: str) -> dict[str, Any]:
        raise RuntimeError("network blew up")

    with patch.object(sp500_module, "_fetch_yf_info", _boom):
        assert await _fetch_one("AAPL") is None


# ---------------------- _fetch_tickers_from_wikipedia -----------------------


_FAKE_HTML = """
<html><body><table class="wikitable">
  <tr><th>Symbol</th><th>Security</th></tr>
  <tr><td>AAPL</td><td>Apple Inc.</td></tr>
  <tr><td>MSFT</td><td>Microsoft</td></tr>
  <tr><td>BRK.B</td><td>Berkshire Hathaway</td></tr>
  <tr><td>BF.B</td><td>Brown-Forman</td></tr>
</table></body></html>
"""


@pytest.mark.asyncio
async def test_fetch_tickers_normalises_dot_to_dash() -> None:
    response = httpx.Response(
        200,
        text=_FAKE_HTML,
        request=httpx.Request("GET", sp500_module.WIKIPEDIA_URL),
    )

    async def _get(self: httpx.AsyncClient, url: str, **_: Any) -> httpx.Response:
        return response

    with patch.object(httpx.AsyncClient, "get", _get):
        async with httpx.AsyncClient() as client:
            tickers = await _fetch_tickers_from_wikipedia(client)

    assert tickers == ["AAPL", "MSFT", "BRK-B", "BF-B"]
    assert "BRK.B" not in tickers
    assert "BF.B" not in tickers


@pytest.mark.asyncio
async def test_fetch_tickers_raises_on_http_error() -> None:
    response = httpx.Response(
        403,
        text="forbidden",
        request=httpx.Request("GET", sp500_module.WIKIPEDIA_URL),
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
        request=httpx.Request("GET", sp500_module.WIKIPEDIA_URL),
    )

    async def _get(self: httpx.AsyncClient, url: str, **_: Any) -> httpx.Response:
        return response

    with patch.object(httpx.AsyncClient, "get", _get):
        async with httpx.AsyncClient() as client:
            with pytest.raises(RuntimeError, match="constituents table not found"):
                await _fetch_tickers_from_wikipedia(client)


# ---------------------- SP500Adapter.fetch_constituents ---------------------


@pytest.mark.asyncio
async def test_fetch_constituents_full_flow_with_one_failure() -> None:
    """Mock both Wikipedia and per-ticker fetch; one ticker fails → excluded."""
    fake_tickers = ["AAPL", "MSFT", "BRK-B", "DEAD"]

    async def _fake_wiki(_client: httpx.AsyncClient) -> list[str]:
        return fake_tickers

    async def _fake_yf(ticker: str) -> dict[str, Any]:
        if ticker == "DEAD":
            return {}
        return _aapl_info() | {"shortName": f"{ticker} Inc"}

    with (
        patch.object(sp500_module, "_fetch_tickers_from_wikipedia", _fake_wiki),
        patch.object(sp500_module, "_fetch_yf_info", _fake_yf),
    ):
        idx = await SP500Adapter().fetch_constituents()

    assert idx.name == "S&P 500"
    assert idx.country == "US"
    assert len(idx.constituents) == 3
    tickers = [c.ticker for c in idx.constituents]
    assert "DEAD" not in tickers
    assert "BRK-B" in tickers
    assert all(c.country == "US" for c in idx.constituents)
    assert all(c.isin is None for c in idx.constituents)
    assert all(c.isin_source is None for c in idx.constituents)


@pytest.mark.asyncio
async def test_fetch_constituents_propagates_wikipedia_failure() -> None:
    async def _boom(_client: httpx.AsyncClient) -> list[str]:
        raise httpx.HTTPError("Wikipedia unreachable")

    with patch.object(sp500_module, "_fetch_tickers_from_wikipedia", _boom):
        with pytest.raises(httpx.HTTPError):
            await SP500Adapter().fetch_constituents()


def test_sp500_adapter_is_instantiable() -> None:
    adapter = SP500Adapter()
    assert adapter.name == "S&P 500"
    assert adapter.country == "US"
    assert callable(adapter.fetch_constituents)


# Silence unused-import warnings for AsyncMock (kept available for future tests).
_ = AsyncMock
