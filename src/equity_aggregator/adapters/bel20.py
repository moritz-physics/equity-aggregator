"""BEL 20 index adapter (Brussels Exchange Index, 20 constituents).

Aggregates per-constituent data for the BEL 20 from:

  - **yfinance** — unofficial Yahoo Finance scraper. Used for price, currency,
    sector, beta, market cap, dividend yield, ex-dividend date, etc.
  - **OpenFIGI** — official Bloomberg identifier mapping API. Used as a
    best-effort enrichment / existence check.

Exploration findings (live probes run 2026-05-24):

  * BEL 20 tickers use the ``.BR`` suffix (Euronext Brussels).
    e.g. ``ABI.BR``, ``UCB.BR``, ``SOLB.BR``.
  * Euronext's live index composition API (``live.euronext.com/en/pd_es/data/
    index/compositon``) returns HTTP 200 with an ``aaData`` array containing
    20 empty arrays — no ticker or name data is embedded. The non-``_es``
    endpoint redirects to the homepage. Wikipedia's BEL 20 page requires
    ``lxml`` (not installed). Conclusion: a curated static map is the most
    reliable constituent source.
  * ``yf.Ticker("ABI.BR").info`` returns ~170 fields with EUR currency.
    Mapped keys used: ``longName, currentPrice, regularMarketPrice,
    previousClose, currency, sector, marketCap, beta, dividendYield,
    exDividendDate``. Note: ``dividendYield`` is expressed as a percentage
    (e.g. ``1.6`` means 1.6%). ``exDividendDate`` is a Unix epoch in seconds.
  * ``info.get("isin")`` — the key is entirely absent from ABI.BR and all
    other BEL 20 tickers probed. yfinance does not surface ISINs for Belgian
    listings. Static map is the only ISIN source.
  * ``info.get("country")`` returns ``"Belgium"`` for Belgian-incorporated
    companies. The adapter sets country to ``"BE"`` uniformly to reflect the
    listing venue (Euronext Brussels), consistent with DAX/AEX convention.
  * OpenFIGI ``/v3/mapping`` endpoint does not return ISIN in its free
    response payload; called as a best-effort enrichment only.
  * exchCode for Euronext Brussels on OpenFIGI is ``"XBRU"``.
  * All 20 BEL 20 members resolve in yfinance with EUR currency.
  * Note on composition: the BEL 20 includes two non-Belgian-domiciled
    members — argenx SE (ARGX.BR, NL-domiciled, ISIN NL0010832176) and
    Aperam SA (APAM.BR, LU-domiciled, ISIN LU0569974404). They are listed
    on Euronext Brussels and are bona-fide index constituents, analogous to
    Airbus / Stellantis in the CAC 40. ISIN-prefix validation downstream
    must accept ISO 6166 codes from any country, not just BE.

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
OPENFIGI_EXCH_CODE = "XBRU"
SOURCE_LABEL = "yfinance (unofficial)"
INDEX_NAME = "BEL 20"
INDEX_COUNTRY = "BE"


@dataclass(frozen=True, slots=True)
class _Member:
    ticker: str
    name: str
    isin: str


# BEL 20 composition. Curated static map; review when Euronext Brussels
# rebalances (typically quarterly). ISINs are ISO 6166 codes; most members
# are BE-prefixed, but argenx (NL) and Aperam (LU) are non-Belgian-domiciled
# index members listed on Euronext Brussels.
BEL20_MEMBERS: tuple[_Member, ...] = (
    _Member("ABI.BR", "Anheuser-Busch InBev SA/NV", "BE0974293251"),
    _Member("ACKB.BR", "Ackermans & Van Haaren NV", "BE0003764785"),
    _Member("AED.BR", "Aedifica NV/SA", "BE0003851681"),
    _Member("AGS.BR", "ageas SA/NV", "BE0974264930"),
    _Member("APAM.BR", "Aperam SA", "LU0569974404"),
    _Member("ARGX.BR", "argenx SE", "NL0010832176"),
    _Member("BEKB.BR", "NV Bekaert SA", "BE0003789394"),
    _Member("BPOST.BR", "bpost NV/SA", "BE0974268972"),
    _Member("COFB.BR", "Cofinimmo SA", "BE0003593044"),
    _Member("COLR.BR", "Colruyt Group N.V.", "BE0974256852"),
    _Member("DIE.BR", "D'Ieteren Group SA", "BE0974259238"),
    _Member("GBLB.BR", "Groupe Bruxelles Lambert SA", "BE0003797140"),
    _Member("KBC.BR", "KBC Group NV", "BE0003565737"),
    _Member("LOTB.BR", "Lotus Bakeries NV", "BE0003532583"),
    _Member("MELE.BR", "Melexis NV", "BE0003469031"),
    _Member("PROX.BR", "Proximus PLC", "BE0003810273"),
    _Member("SOF.BR", "Sofina Société Anonyme", "BE0003717312"),
    _Member("SOLB.BR", "Solvay SA", "BE0003470755"),
    _Member("UCB.BR", "UCB SA", "BE0003739530"),
    _Member("WDP.BR", "Warehouses De Pauw SA", "BE0003763779"),
)

assert len(BEL20_MEMBERS) == 20, (
    f"BEL20_MEMBERS has {len(BEL20_MEMBERS)} entries, expected 20"
)

# Convenience dict for external access and test assertions
BEL20_ISINS: dict[str, str] = {m.ticker: m.isin for m in BEL20_MEMBERS}


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
    )


async def _fetch_member(
    client: httpx.AsyncClient, member: _Member
) -> Constituent:
    """Fetch all upstream data for one BEL 20 member; never raises."""
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
            currency="EUR",
        )


class BEL20Adapter(IndexAdapter):
    """Adapter for the BEL 20 index (Brussels Exchange Index, 20 members)."""

    name: str = INDEX_NAME
    country: str = INDEX_COUNTRY
    source: str = SOURCE_LABEL

    def __init__(self, members: tuple[_Member, ...] = BEL20_MEMBERS) -> None:
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
