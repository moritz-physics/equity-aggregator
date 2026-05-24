"""WIG20 (Warsaw Stock Exchange) index adapter.

Aggregates per-constituent data for the WIG20 from:

  - **yfinance** — unofficial Yahoo Finance scraper. Used for price, currency,
    sector, beta, market cap, dividend yield, ex-dividend date, etc.
  - **OpenFIGI** — official Bloomberg identifier mapping API. Used as a
    best-effort enrichment / existence check.

Exploration findings that motivated this design:

  * ``yf.Ticker("PKN.WA").info`` returns the same field shape as XETRA/Paris
    tickers. Mapped keys used: ``longName, currentPrice, currency, sector,
    marketCap, beta, dividendYield, exDividendDate``. ``currency`` is PLN
    for Warsaw-listed shares; ``exchange`` reports ``WSE`` /
    ``fullExchangeName`` ``Warsaw``.
  * ``info.get("isin")`` returns ``None`` for every WIG20 ticker probed —
    yfinance does not surface ISINs for Polish listings, matching the DAX
    and CAC 40 findings.
  * The GPW Benchmark / gpw.pl pages used to publish WIG20 components are
    not stable scrape targets: most endpoints either 404 or return
    JS-rendered HTML with no embedded component table. Wikipedia's WIG20
    page (reachable with a descriptive User-Agent) does not include a
    components table either — only a historical performance table.
  * **Conclusion**: a curated static map of ticker → (name, ISIN) is the
    reliable constituent + ISIN source. Composition was cross-checked
    against live yfinance lookups for every ticker. yfinance still drives
    all live financial fields; OpenFIGI is still called as a best-effort
    enrichment and remains the source-of-record once it surfaces ISINs.

Notable composition details:

  * ``ALE.WA`` (Allegro.eu) is Warsaw-listed but Luxembourg-domiciled,
    so its ISIN begins with ``LU``.
  * ``PCO.WA`` (Pepco Group) is Warsaw-listed but Luxembourg-domiciled,
    so its ISIN begins with ``LU``.
  * ``ZAB.WA`` (Żabka Group) is Warsaw-listed but Netherlands-domiciled
    (holding company), so its ISIN begins with ``NL``.
  * All other constituents are PL-domiciled and have ISINs starting with
    ``PL``.

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
OPENFIGI_EXCH_CODE = "PW"  # Warsaw Stock Exchange on OpenFIGI
SOURCE_LABEL = "yfinance (unofficial)"
INDEX_NAME = "WIG20"
INDEX_COUNTRY = "PL"


@dataclass(frozen=True, slots=True)
class _Member:
    ticker: str
    name: str
    isin: str


# WIG20 composition. Curated static map; review when GPW Benchmark rebalances
# (typically quarterly: March / June / September / December). ISINs are
# ISO 6166 codes published by KDPW (the Polish CSD) or the relevant foreign
# CSD for non-PL-domiciled issuers.
WIG20_MEMBERS: tuple[_Member, ...] = (
    _Member("ALE.WA", "Allegro.eu S.A.", "LU2237380790"),
    _Member("ALR.WA", "Alior Bank S.A.", "PLALIOR00045"),
    _Member("BDX.WA", "Budimex SA", "PLBUDMX00013"),
    _Member("CDR.WA", "CD Projekt S.A.", "PLOPTTC00011"),
    _Member("DNP.WA", "Dino Polska S.A.", "PLDINPL00011"),
    _Member("JSW.WA", "Jastrzębska Spółka Węglowa S.A.", "PLJSW0000015"),
    _Member("KGH.WA", "KGHM Polska Miedź S.A.", "PLKGHM000017"),
    _Member("KRU.WA", "KRUK Spółka Akcyjna", "PLKRK0000010"),
    _Member("KTY.WA", "Grupa Kęty S.A.", "PLKETY000011"),
    _Member("LPP.WA", "LPP SA", "PLLPP0000011"),
    _Member("MBK.WA", "mBank S.A.", "PLBRE0000012"),
    _Member("OPL.WA", "Orange Polska S.A.", "PLTLKPL00017"),
    _Member("PCO.WA", "Pepco Group N.V.", "LU2434412847"),
    _Member("PEO.WA", "Bank Polska Kasa Opieki S.A.", "PLPEKAO00016"),
    _Member("PGE.WA", "PGE Polska Grupa Energetyczna S.A.", "PLPGER000010"),
    _Member("PKN.WA", "Orlen S.A.", "PLPKN0000018"),
    _Member("PKO.WA", "PKO Bank Polski S.A.", "PLPKO0000016"),
    _Member("PZU.WA", "Powszechny Zakład Ubezpieczeń SA", "PLPZU0000011"),
    _Member("SPL.WA", "Santander Bank Polska S.A.", "PLBZ00000044"),
    _Member("ZAB.WA", "Żabka Group S.A.", "NL0015002CX0"),
)

assert len(WIG20_MEMBERS) == 20, (
    f"WIG20_MEMBERS has {len(WIG20_MEMBERS)} entries, expected 20"
)

# Tests and callers occasionally want a plain ticker→ISIN map.
WIG20_ISINS: dict[str, str] = {m.ticker: m.isin for m in WIG20_MEMBERS}


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
        except Exception as exc:
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


def _index_country() -> str:
    """The country field on a Constituent reflects the *listing*, not the
    issuer domicile. WIG20 trades on the Warsaw Stock Exchange in PLN;
    every constituent is tagged PL regardless of issuer domicile (e.g.
    Allegro.eu is LU-domiciled, Pepco Group LU, Żabka Group NL — all
    treated as PL for index-listing purposes).
    """
    return INDEX_COUNTRY


def _build_constituent(
    member: _Member,
    yf_info: dict[str, Any],
    figi_record: dict[str, Any] | None,
) -> Constituent:
    """Merge yfinance + OpenFIGI + static map into a Constituent."""
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
        country=_index_country(),
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
    """Fetch all upstream data for one WIG20 member; never raises."""
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
            currency="PLN",
        )


class WIG20Adapter(IndexAdapter):
    """Adapter for the WIG20 index."""

    name: str = INDEX_NAME
    country: str = INDEX_COUNTRY
    source: str = SOURCE_LABEL

    def __init__(self, members: tuple[_Member, ...] = WIG20_MEMBERS) -> None:
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
