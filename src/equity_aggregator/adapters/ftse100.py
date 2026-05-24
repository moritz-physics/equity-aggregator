"""FTSE 100 index adapter.

Aggregates per-constituent data for the FTSE 100 from:

  - **Wikipedia** — live constituent list from ``FTSE_100_Index``. Table
    index 6 carries the 100 rows with ``Company`` and ``Ticker`` columns
    (``Ticker`` is the bare LSE EPIC, without the ``.L`` suffix that
    yfinance requires).
  - **yfinance** — unofficial Yahoo Finance scraper. Used for price,
    currency, sector, beta, market cap, dividend yield, ex-dividend date.

Exploration findings that motivated this design:

  * Wikipedia 403s requests without a descriptive User-Agent (WMF robot
    policy). Same UA pattern as ``sp500.py``.
  * The constituents table is at index 6 of ``pd.read_html``, with columns
    ``['Company', 'Ticker', 'FTSE industry classification benchmark
    sector[39]']``. There is **no ISIN column** on this page → ISINs are
    left ``None`` (no curated static map maintained for the FTSE 100).
  * Tickers on Wikipedia are bare EPICs (e.g. ``SHEL``, ``HSBA``). yfinance
    requires the ``.L`` suffix for London listings; appended uniformly.
  * **GBp vs GBP normalisation.** LSE quotes most equities in pence, and
    yfinance faithfully returns ``currency="GBp"`` with the price in pence
    (e.g. SHEL.L: ``currentPrice=3205.0 GBp`` ≡ £32.05). We always
    normalise to GBP at the adapter boundary so downstream code never has
    to remember the pence convention. Tickers already quoted in ``"GBP"``
    are passed through unchanged (no double-conversion).
  * ``currentPrice`` and ``regularMarketPrice`` are populated identically
    for every sampled LSE ticker; we prefer ``currentPrice`` and fall back
    to ``regularMarketPrice``.
  * ``info.get("isin")`` is ``None`` for every sampled LSE ticker —
    yfinance does not surface ISINs for London listings either.
  * ``dividendYield`` is already expressed as a percent (e.g. ``3.63`` ≡
    3.63%) — matches the convention used by ``dax.py``.

⚠️  yfinance is **unofficial**. Yahoo changes endpoints, field shapes, and
    rate limits without notice. The Wikipedia constituent list can also
    lag FTSE Russell rebalances by a few days. Cache aggressively, fail
    loudly on schema drift, and never use this as a system of record.
"""

from __future__ import annotations

import asyncio
import io
import logging
from datetime import UTC, date, datetime
from typing import Any, cast

import httpx
import pandas as pd  # pyright: ignore[reportMissingTypeStubs]

from equity_aggregator.adapters.base import IndexAdapter
from equity_aggregator.core.models import Constituent, Index

logger = logging.getLogger(__name__)

WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/FTSE_100_Index"
WIKIPEDIA_UA = (
    "equity-aggregator/0.1 (research tool; "
    "+https://github.com/equity-aggregator) httpx/python"
)
SOURCE_LABEL = "yfinance (unofficial)"
INDEX_NAME = "FTSE 100"
INDEX_COUNTRY = "GB"
YF_SUFFIX = ".L"


def _epoch_to_date(value: Any) -> date | None:
    if value is None:
        return None
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    try:
        return datetime.fromtimestamp(ts, tz=UTC).date()
    except (OverflowError, OSError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:  # noqa: PLR0124 — NaN check
        return None
    return out


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return str(value)


def _normalise_price(
    price: float | None, currency: str | None
) -> tuple[float | None, str]:
    """LSE quotes prices in pence (``GBp``). Convert to pounds (``GBP``)
    so downstream code only sees a single canonical unit. Tickers already
    quoted in ``GBP`` (or with unknown currency) are passed through and
    defaulted to ``GBP``.
    """
    if currency == "GBp":
        converted = round(price / 100, 4) if price is not None else None
        return converted, "GBP"
    return price, currency or "GBP"


async def _fetch_tickers_from_wikipedia(
    client: httpx.AsyncClient,
) -> list[str]:
    """Fetch the live FTSE 100 EPICs from Wikipedia and append ``.L``."""
    r = await client.get(
        WIKIPEDIA_URL,
        headers={"User-Agent": WIKIPEDIA_UA},
        follow_redirects=True,
    )
    r.raise_for_status()
    tables = cast(
        list[Any],
        pd.read_html(io.StringIO(r.text)),  # pyright: ignore[reportUnknownMemberType]
    )
    for table in tables:
        cols = [str(c) for c in table.columns.tolist()]
        if "Ticker" in cols and "Company" in cols:
            raw: list[Any] = list(table["Ticker"].tolist())
            return [_with_suffix(str(s)) for s in raw]
    raise RuntimeError(
        "FTSE 100: Wikipedia constituents table not found "
        "(expected a table with 'Ticker' and 'Company' columns)"
    )


def _with_suffix(epic: str) -> str:
    epic = epic.strip().upper()
    return epic if epic.endswith(YF_SUFFIX) else f"{epic}{YF_SUFFIX}"


async def _fetch_yf_info(ticker: str) -> dict[str, Any]:
    """Fetch ``yfinance.Ticker(ticker).info`` off the event loop."""

    def _call() -> dict[str, Any]:
        import yfinance as yf  # pyright: ignore[reportMissingTypeStubs]

        try:
            data: Any = yf.Ticker(ticker).info  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        except Exception as exc:
            logger.warning("yfinance .info failed for %s: %s", ticker, exc)
            return {}
        if isinstance(data, dict):
            return cast(dict[str, Any], data)
        return {}

    return await asyncio.to_thread(_call)


def _build_constituent(ticker: str, info: dict[str, Any]) -> Constituent | None:
    """Build a Constituent, normalising GBp prices to GBP."""
    if not info or info.get("quoteType") is None:
        return None

    name = (
        _coerce_str(info.get("shortName"))
        or _coerce_str(info.get("longName"))
        or ticker
    )

    raw_price = _coerce_float(info.get("currentPrice"))
    if raw_price is None:
        raw_price = _coerce_float(info.get("regularMarketPrice"))

    price, currency = _normalise_price(raw_price, _coerce_str(info.get("currency")))

    return Constituent(
        ticker=ticker,
        name=name,
        isin=None,
        isin_source=None,
        country=INDEX_COUNTRY,
        price=price,
        currency=currency,
        ex_div_date=_epoch_to_date(info.get("exDividendDate")),
        ttm_div_yield=_coerce_float(info.get("dividendYield")),
        beta=_coerce_float(info.get("beta")),
        market_cap=_coerce_float(info.get("marketCap")),
        sector=_coerce_str(info.get("sector")),
    )


async def _fetch_one(ticker: str) -> Constituent | None:
    try:
        info = await _fetch_yf_info(ticker)
        return _build_constituent(ticker, info)
    except Exception as exc:
        logger.warning("FTSE 100: failed to fetch %s: %s", ticker, exc)
        return None


class FTSE100Adapter(IndexAdapter):
    """Adapter for the FTSE 100 index."""

    name: str = INDEX_NAME
    country: str = INDEX_COUNTRY
    source: str = SOURCE_LABEL

    async def fetch_constituents(self) -> Index:
        async with httpx.AsyncClient(timeout=30.0) as client:
            tickers = await _fetch_tickers_from_wikipedia(client)

        results = await asyncio.gather(*(_fetch_one(t) for t in tickers))
        constituents = [c for c in results if c is not None]

        return Index(
            name=self.name,
            country=self.country,
            constituents=constituents,
            fetched_at=datetime.now(tz=UTC),
            source=self.source,
        )
