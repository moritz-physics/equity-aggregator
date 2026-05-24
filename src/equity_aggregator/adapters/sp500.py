"""S&P 500 index adapter.

Aggregates per-constituent data for the S&P 500 from:

  - **Wikipedia** — live constituent list from ``List_of_S&P_500_companies``,
    table[0]. The Wikipedia table is the canonical free source of the current
    composition (S&P does not publish a free constituent list).
  - **yfinance** — unofficial Yahoo Finance scraper. Used for price, currency,
    sector, beta, market cap, dividend yield, ex-dividend date, etc.

Exploration findings that motivated this design (see ``5A`` notes):

  * Wikipedia's S&P 500 page is 503 rows, not 500: GOOGL/GOOG, FOX/FOXA and
    NWS/NWSA each contribute two share classes. The list can also briefly
    differ from the official index by a few days around S&P rebalances.
  * Wikipedia rejects bare ``Mozilla/5.0`` requests with 403 per the WMF
    robot policy. A descriptive UA is required.
  * Two ticker symbols use ``.`` in the Wikipedia spelling (``BRK.B``,
    ``BF.B``) but yfinance expects ``-`` instead — applied uniformly.
  * ``yf.Ticker(t).info["isin"]`` is ``None`` for every US ticker probed.
    yfinance does not surface ISINs for US listings, and there is no free
    bulk ISIN source for ~500 US securities; ISINs are deliberately left
    ``None`` rather than maintained as a static map.
  * For US tickers ``currentPrice`` and ``regularMarketPrice`` are
    consistently populated and identical. Tested fan-out: 50 tickers in
    parallel via ``asyncio.to_thread`` completed in ~2.5s with no errors.

⚠️  yfinance is **unofficial**. Yahoo changes endpoints, field shapes, and
    rate limits without notice. Cache aggressively, fail loudly on schema
    drift, and never use this as a system of record.
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

WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
WIKIPEDIA_UA = (
    "equity-aggregator/0.1 (research tool; "
    "+https://github.com/equity-aggregator) httpx/python"
)
SOURCE_LABEL = "yfinance (unofficial)"
INDEX_NAME = "S&P 500"
INDEX_COUNTRY = "US"


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


def _parse_yield(value: Any) -> float | None:
    """Convert yfinance ``trailingAnnualDividendYield`` (decimal, e.g.
    0.0194 = 1.94%) into the percent-units expected by ``Constituent``.
    Returns None for missing/zero values so downstream "with dividend"
    counts only see real distributions.
    """
    parsed = _coerce_float(value)
    if parsed is None or parsed <= 0:
        return None
    return parsed * 100


async def _fetch_tickers_from_wikipedia(
    client: httpx.AsyncClient,
) -> list[str]:
    """Fetch the live S&P 500 constituent tickers from Wikipedia.

    Applies the ``.`` → ``-`` normalisation that yfinance requires for
    share-class tickers (BRK.B → BRK-B, BF.B → BF-B).
    """
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
    if not tables or "Symbol" not in tables[0].columns:
        raise RuntimeError(
            "S&P 500: Wikipedia constituents table not found "
            "(expected first table with 'Symbol' column)"
        )
    raw: list[Any] = list(tables[0]["Symbol"].tolist())
    return [str(s).replace(".", "-") for s in raw]


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
    """Build a Constituent from a yfinance info dict.

    Returns None if the upstream payload is empty or clearly invalid
    (no ``quoteType``), so the adapter can drop dead tickers cleanly
    instead of emitting half-populated rows.
    """
    if not info or info.get("quoteType") is None:
        return None

    name = (
        _coerce_str(info.get("shortName"))
        or _coerce_str(info.get("longName"))
        or ticker
    )

    price = _coerce_float(info.get("currentPrice"))
    if price is None:
        price = _coerce_float(info.get("regularMarketPrice"))

    return Constituent(
        ticker=ticker,
        name=name,
        isin=None,
        isin_source=None,
        country=INDEX_COUNTRY,
        price=price,
        currency=_coerce_str(info.get("currency")),
        ex_div_date=_epoch_to_date(info.get("exDividendDate")),
        ttm_div_yield=_parse_yield(info.get("trailingAnnualDividendYield")),
        beta=_coerce_float(info.get("beta")),
        market_cap=_coerce_float(info.get("marketCap")),
        sector=_coerce_str(info.get("sector")),
    )


async def _fetch_one(ticker: str) -> Constituent | None:
    """Fetch a single S&P 500 ticker; never raises. Returns None on failure."""
    try:
        info = await _fetch_yf_info(ticker)
        return _build_constituent(ticker, info)
    except Exception as exc:
        logger.warning("S&P 500: failed to fetch %s: %s", ticker, exc)
        return None


class SP500Adapter(IndexAdapter):
    """Adapter for the S&P 500 index."""

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
