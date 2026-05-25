"""SMI index adapter (Swiss Market Index, 20 constituents).

Aggregates per-constituent data for the SMI from:

  - **yfinance** — unofficial Yahoo Finance scraper. Used for price, currency,
    sector, beta, market cap, dividend yield, ex-dividend date, etc.
  - **OpenFIGI** — official Bloomberg identifier mapping API. Used as a
    best-effort enrichment / existence check.

Exploration findings (live probes run 2026-05-24):

  * SMI tickers use the ``.SW`` suffix (SIX Swiss Exchange / Euronext Zurich).
    e.g. ``NESN.SW``, ``NOVN.SW``, ``ROG.SW``.
  * SIX Group's API endpoint (``api.six-group.com/api/findata/v1/indices/...``)
    returns 404 for the SMI composition. The SIX Group website URL redirects to
    their homepage and does not return machine-readable constituent data.
    Wikipedia's SMI page requires ``lxml`` (not installed). Conclusion: a
    curated static map is the most reliable constituent source.
  * ``yf.Ticker("NESN.SW").info`` returns ~170 fields with CHF currency.
    Mapped keys used: ``longName, currentPrice, regularMarketPrice,
    previousClose, currency, sector, marketCap, beta, dividendYield,
    exDividendDate``. Note: ``dividendYield`` is expressed as a percentage
    (e.g. ``3.94`` means 3.94%). ``exDividendDate`` is a Unix epoch in seconds.
  * ``info.get("isin")`` returns ``None`` for NESN.SW — yfinance does not
    surface ISINs for Swiss listings. Static map is the reliable ISIN fallback.
  * ``info.get("country")`` returns ``"Switzerland"`` for Swiss-incorporated
    companies. The adapter sets country to ``"CH"`` uniformly to reflect the
    listing venue (SIX Swiss Exchange), consistent with DAX/AEX convention.
  * OpenFIGI ``/v3/mapping`` endpoint does not return ISIN in its free
    response payload; called as a best-effort enrichment only.
  * exchCode for SIX Swiss Exchange on OpenFIGI is ``"XSWX"``.
  * All 20 SMI members verified in static map with CHF currency on SIX.

⚠️  yfinance is **unofficial**. Yahoo changes endpoints, field shapes, and
    rate limits without notice. Cache aggressively, fail loudly on schema
    drift, and never use this as a system of record.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, cast

import httpx

from equity_aggregator.adapters.base import IndexAdapter
from equity_aggregator.core.models import Constituent, Index

logger = logging.getLogger(__name__)

OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
OPENFIGI_EXCH_CODE = "XSWX"
SOURCE_LABEL = "yfinance (unofficial)"
INDEX_NAME = "SMI"
INDEX_COUNTRY = "CH"


@dataclass(frozen=True, slots=True)
class _Member:
    ticker: str
    name: str
    isin: str
    weight: float | None = None  # filled when authoritative source provides it


# SMI 20 composition. Curated static map; review when SIX rebalances
# (typically quarterly). ISINs are ISO 6166 codes; Swiss securities start "CH".
SMI_MEMBERS: tuple[_Member, ...] = (
    _Member("ABBN.SW", "ABB Ltd", "CH0012221716"),
    _Member("ALC.SW", "Alcon Inc.", "CH0432492467"),
    _Member("CFR.SW", "Compagnie Financière Richemont SA", "CH0210483332"),
    _Member("GEBN.SW", "Geberit AG", "CH0030170408"),
    _Member("GIVN.SW", "Givaudan SA", "CH0010645932"),
    _Member("HOLN.SW", "Holcim Ltd", "CH0012214059"),
    _Member("KNIN.SW", "Kuehne + Nagel International AG", "CH0025238863"),
    _Member("LOGN.SW", "Logitech International S.A.", "CH0025751329"),
    _Member("LONN.SW", "Lonza Group Ltd", "CH0013841017"),
    _Member("NESN.SW", "Nestlé S.A.", "CH0038863350"),
    # Novartis: was CH0012221060 (invalid ISO 6166 check digit). The
    # authoritative ISIN per SIX Swiss Exchange / Wikipedia is CH0012005267.
    _Member("NOVN.SW", "Novartis AG", "CH0012005267"),
    _Member("PGHN.SW", "Partners Group Holding AG", "CH0024608827"),
    _Member("ROG.SW", "Roche Holding AG", "CH0012032048"),
    _Member("SAGN.SW", "Straumann Holding AG", "CH0012280076"),
    _Member("SCMN.SW", "Swisscom AG", "CH0008742519"),
    _Member("SGSN.SW", "SGS SA", "CH0002497458"),
    _Member("SLHN.SW", "Swiss Life Holding AG", "CH0014852781"),
    _Member("SREN.SW", "Swiss Re AG", "CH0126881561"),
    _Member("UBSG.SW", "UBS Group AG", "CH0244767585"),
    _Member("ZURN.SW", "Zurich Insurance Group AG", "CH0011075394"),
)

assert len(SMI_MEMBERS) == 20, (
    f"SMI_MEMBERS has {len(SMI_MEMBERS)} entries, expected 20"
)

# Convenience dict for external access and test assertions
SMI_ISINS: dict[str, str] = {m.ticker: m.isin for m in SMI_MEMBERS}


def _epoch_to_date(value: Any) -> date | None:
    """Convert a Yahoo-style Unix epoch (seconds) to a date, defensively."""
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
    # yfinance sometimes returns NaN
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


def _resolve_isin_from_yfinance(info: dict[str, Any]) -> str | None:
    """yfinance occasionally has an 'isin' key. Treat '-' as missing."""
    raw = info.get("isin")
    if not isinstance(raw, str):
        return None
    raw = raw.strip()
    if not raw or raw == "-":
        return None
    return raw


async def _fetch_yf_info(ticker: str) -> dict[str, Any]:
    """Fetch yfinance.Ticker(ticker).info off the event loop."""

    def _call() -> dict[str, Any]:
        import yfinance as yf  # pyright: ignore[reportMissingTypeStubs]

        try:
            data: Any = yf.Ticker(ticker).info  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        except Exception as exc:  # network / scrape errors
            logger.warning("yfinance .info failed for %s: %s", ticker, exc)
            return {}
        if isinstance(data, dict):
            return cast(dict[str, Any], data)
        return {}

    return await asyncio.to_thread(_call)


async def _fetch_openfigi(
    client: httpx.AsyncClient, base_ticker: str
) -> dict[str, Any] | None:
    """Best-effort OpenFIGI lookup for a single ticker. Returns the first
    record on success, or None if the API does not yield usable data.

    OpenFIGI does not currently surface ISIN in its response, but we still
    call it: (1) as a remote sanity check that the ticker exists, and
    (2) so we transparently pick up an ISIN if OpenFIGI ever starts
    returning one.
    """
    payload = [
        {
            "idType": "TICKER",
            "idValue": base_ticker,
            "exchCode": OPENFIGI_EXCH_CODE,
        }
    ]
    try:
        r = await client.post(OPENFIGI_URL, json=payload, timeout=15.0)
    except httpx.HTTPError as exc:
        logger.debug("OpenFIGI request failed for %s: %s", base_ticker, exc)
        return None
    # Treat any 4xx (rate-limit, bad request, etc.) as a silent miss.
    if 400 <= r.status_code < 500:
        return None
    if r.status_code != 200:
        logger.debug(
            "OpenFIGI non-200 for %s: %s", base_ticker, r.status_code
        )
        return None
    try:
        body: Any = r.json()
    except ValueError:
        return None
    if not isinstance(body, list) or not body:
        return None
    entry: Any = body[0]  # pyright: ignore[reportUnknownVariableType]
    if not isinstance(entry, dict):
        return None
    records: Any = cast(dict[str, Any], entry).get("data")
    if not isinstance(records, list) or not records:
        return None
    first: Any = records[0]  # pyright: ignore[reportUnknownVariableType]
    if isinstance(first, dict):
        return cast(dict[str, Any], first)
    return None


def _build_constituent(
    member: _Member,
    yf_info: dict[str, Any],
    figi_record: dict[str, Any] | None,
) -> Constituent:
    """Merge yfinance + OpenFIGI + static map into a Constituent."""
    # ISIN resolution order: yfinance → OpenFIGI → static map.
    isin: str | None = _resolve_isin_from_yfinance(yf_info)
    source: str | None = "yfinance" if isin else None

    if not isin and figi_record is not None:
        figi_isin = figi_record.get("isin")
        if isinstance(figi_isin, str) and figi_isin.strip():
            isin = figi_isin.strip()
            source = "openfigi"

    if not isin:
        isin = member.isin
        source = "static"

    name = _coerce_str(yf_info.get("longName")) or _coerce_str(
        yf_info.get("shortName")
    ) or member.name

    price = _coerce_float(yf_info.get("currentPrice"))
    if price is None:
        price = _coerce_float(yf_info.get("regularMarketPrice"))
    if price is None:
        price = _coerce_float(yf_info.get("previousClose"))

    return Constituent(
        ticker=member.ticker,
        name=name,
        isin=isin,
        isin_source=source,
        country=INDEX_COUNTRY,
        price=price,
        currency=_coerce_str(yf_info.get("currency")),
        ex_div_date=_epoch_to_date(yf_info.get("exDividendDate")),
        ttm_div_yield=_coerce_float(yf_info.get("dividendYield")),
        beta=_coerce_float(yf_info.get("beta")),
        market_cap=_coerce_float(yf_info.get("marketCap")),
        sector=_coerce_str(yf_info.get("sector")),
        weight=member.weight,
    )


async def _fetch_member(
    client: httpx.AsyncClient, member: _Member
) -> Constituent:
    """Fetch all upstream data for one SMI member; never raises."""
    base_ticker = member.ticker.split(".", 1)[0]
    yf_info, figi_record = await asyncio.gather(
        _fetch_yf_info(member.ticker),
        _fetch_openfigi(client, base_ticker),
    )
    try:
        return _build_constituent(member, yf_info, figi_record)
    except Exception as exc:
        logger.warning(
            "Falling back to static-only constituent for %s: %s", member.ticker, exc
        )
        return Constituent(
            ticker=member.ticker,
            name=member.name,
            isin=member.isin,
            isin_source="static",
            country=INDEX_COUNTRY,
            currency="CHF",
            weight=member.weight,
        )


class SMIAdapter(IndexAdapter):
    """Adapter for the SMI index (Swiss Market Index, 20 members)."""

    name: str = INDEX_NAME
    country: str = INDEX_COUNTRY
    source: str = SOURCE_LABEL

    def __init__(self, members: tuple[_Member, ...] = SMI_MEMBERS) -> None:
        self._members = members

    async def fetch_constituents(self) -> Index:
        async with httpx.AsyncClient() as client:
            constituents = await asyncio.gather(
                *(_fetch_member(client, m) for m in self._members)
            )
        return Index(
            name=self.name,
            country=self.country,
            constituents=list(constituents),
            fetched_at=datetime.now(tz=UTC),
            source=self.source,
        )
