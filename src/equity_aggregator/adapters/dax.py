"""DAX 40 index adapter.

Aggregates per-constituent data for the DAX 40 from:

  - **yfinance** — unofficial Yahoo Finance scraper. Used for price, currency,
    sector, beta, market cap, dividend yield, ex-dividend date, etc.
  - **OpenFIGI** — official Bloomberg identifier mapping API. Used as a
    best-effort enrichment / existence check.

Exploration findings that motivated this design (see scripts in
``/tmp/explore_dax*.py`` during Phase 1):

  * ``yf.Ticker("ADS.DE").info`` returns ~169 fields. Mapped keys used:
    ``longName, currentPrice, currency, sector, marketCap, beta,
    dividendYield, exDividendDate, country``. Note: ``dividendYield`` is
    already expressed as a percentage (e.g. ``1.81`` means 1.81%), and
    ``exDividendDate`` is a Unix epoch in seconds.
  * ``yf.Ticker(...).isin`` returns the sentinel string ``"-"`` for every
    DAX ticker we probed — yfinance does *not* surface ISINs for German
    listings. ``info.get("isin")`` returns ``None``.
  * OpenFIGI's ``/v3/mapping`` endpoint returns ``figi, name, ticker,
    exchCode, compositeFIGI, securityType, marketSector, shareClassFIGI,
    securityType2, securityDescription`` — **no ISIN field**. OpenFIGI is
    FIGI-centric; ISIN is not part of its free response payload.
  * Wikipedia's DAX page is reachable with a custom User-Agent (it 403s a
    bare ``urllib`` request) but the rendered text mixes current and
    historical members (e.g. FME / Fresenius Medical Care, which was
    demoted in 2023, still appears). ``pandas.read_html`` requires
    ``lxml``/``html5lib``, neither installed.
  * **Conclusion**: for a fixed-size, well-known index, the most reliable
    constituent source is a curated static map of ticker → (name, ISIN).
    The map should be reviewed when Deutsche Börse publishes a
    composition change (typically quarterly). yfinance still drives all
    live financial fields; OpenFIGI is still called as a best-effort
    enrichment, and is the source-of-record once it ever starts surfacing
    ISINs.

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
OPENFIGI_EXCH_CODE = "GS"  # XETRA on OpenFIGI
SOURCE_LABEL = "yfinance (unofficial)"
INDEX_NAME = "DAX"
INDEX_COUNTRY = "DE"


@dataclass(frozen=True, slots=True)
class _Member:
    ticker: str
    name: str
    isin: str
    weight: float | None = None  # filled when authoritative source provides it


# DAX 40 composition. Curated static map; review when Deutsche Börse rebalances
# (typically quarterly). ISINs are ISO 6166 codes published by WM Datenservice.
DAX_MEMBERS: tuple[_Member, ...] = (
    _Member("ADS.DE", "adidas AG", "DE000A1EWWW0"),
    _Member("AIR.DE", "Airbus SE", "NL0000235190"),
    _Member("ALV.DE", "Allianz SE", "DE0008404005"),
    _Member("BAS.DE", "BASF SE", "DE000BASF111"),
    _Member("BAYN.DE", "Bayer AG", "DE000BAY0017"),
    _Member("BEI.DE", "Beiersdorf AG", "DE0005200000"),
    _Member("BMW.DE", "Bayerische Motoren Werke AG", "DE0005190003"),
    _Member("BNR.DE", "Brenntag SE", "DE000A1DAHH0"),
    _Member("CBK.DE", "Commerzbank AG", "DE000CBK1001"),
    _Member("CON.DE", "Continental AG", "DE0005439004"),
    _Member("DB1.DE", "Deutsche Börse AG", "DE0005810055"),
    _Member("DBK.DE", "Deutsche Bank AG", "DE0005140008"),
    _Member("DHL.DE", "DHL Group", "DE0005552004"),
    _Member("DTE.DE", "Deutsche Telekom AG", "DE0005557508"),
    _Member("DTG.DE", "Daimler Truck Holding AG", "DE000DTR0CK8"),
    _Member("ENR.DE", "Siemens Energy AG", "DE000ENER6Y0"),
    _Member("EOAN.DE", "E.ON SE", "DE000ENAG999"),
    _Member("FRE.DE", "Fresenius SE & Co. KGaA", "DE0005785604"),
    _Member("HEI.DE", "Heidelberg Materials AG", "DE0006047004"),
    _Member("HEN3.DE", "Henkel AG & Co. KGaA (Vz)", "DE0006048432"),
    _Member("HNR1.DE", "Hannover Rück SE", "DE0008402215"),
    _Member("IFX.DE", "Infineon Technologies AG", "DE0006231004"),
    _Member("MBG.DE", "Mercedes-Benz Group AG", "DE0007100000"),
    _Member("MRK.DE", "Merck KGaA", "DE0006599905"),
    _Member("MTX.DE", "MTU Aero Engines AG", "DE000A0D9PT0"),
    _Member("MUV2.DE", "Münchener Rückversicherungs-Gesellschaft AG", "DE0008430026"),
    _Member("P911.DE", "Dr. Ing. h.c. F. Porsche AG (Pref)", "DE000PAG9113"),
    _Member("PAH3.DE", "Porsche Automobil Holding SE (Pref)", "DE000PAH0038"),
    _Member("QIA.DE", "QIAGEN N.V.", "NL0012169213"),
    _Member("RHM.DE", "Rheinmetall AG", "DE0007030009"),
    _Member("RWE.DE", "RWE AG", "DE0007037129"),
    _Member("SAP.DE", "SAP SE", "DE0007164600"),
    _Member("SHL.DE", "Siemens Healthineers AG", "DE000SHL1006"),
    _Member("SIE.DE", "Siemens AG", "DE0007236101"),
    _Member("SRT3.DE", "Sartorius AG (Vz)", "DE0007165631"),
    _Member("SY1.DE", "Symrise AG", "DE000SYM9999"),
    _Member("VNA.DE", "Vonovia SE", "DE000A1ML7J1"),
    _Member("VOW3.DE", "Volkswagen AG (Vz)", "DE0007664039"),
    _Member("ZAL.DE", "Zalando SE", "DE000ZAL1111"),
    _Member("G24.DE", "Scout24 SE", "DE000A12DM80"),
)

assert len(DAX_MEMBERS) == 40, (
    f"DAX_MEMBERS has {len(DAX_MEMBERS)} entries, expected 40"
)


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
    # Treat any 4xx (rate-limit, bad request, etc.) as a silent miss — the
    # caller falls through to static ISIN resolution. 5xx and other non-200s
    # also fall through but are logged at debug to keep CLI/UI noise down.
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
    issuer domicile. DAX trades on XETRA/Frankfurt; every constituent is DE
    regardless of where the underlying company is incorporated (e.g. Airbus
    is NL-domiciled, Qiagen is NL-domiciled — both list on XETRA in EUR).
    """
    return INDEX_COUNTRY


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
        country=_index_country(),
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
    """Fetch all upstream data for one DAX member; never raises."""
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
            weight=member.weight,
        )


class DAXAdapter(IndexAdapter):
    """Adapter for the DAX 40 index."""

    name: str = INDEX_NAME
    country: str = INDEX_COUNTRY
    source: str = SOURCE_LABEL

    def __init__(self, members: tuple[_Member, ...] = DAX_MEMBERS) -> None:
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
