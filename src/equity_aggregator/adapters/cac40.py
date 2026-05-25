"""CAC 40 index adapter.

Aggregates per-constituent data for the CAC 40 from:

  - **yfinance** — unofficial Yahoo Finance scraper. Used for price, currency,
    sector, beta, market cap, dividend yield, ex-dividend date, etc.
  - **OpenFIGI** — official Bloomberg identifier mapping API. Used as a
    best-effort enrichment / existence check.

Exploration findings that motivated this design:

  * ``yf.Ticker("MC.PA").info`` returns the same field shape as German
    XETRA tickers. Mapped keys used: ``longName, currentPrice, currency,
    sector, marketCap, beta, dividendYield, exDividendDate, country``.
    ``dividendYield`` is already a percentage (e.g. ``2.75`` means 2.75%);
    ``exDividendDate`` is a Unix epoch in seconds.
  * ``info.get("isin")`` returns ``None`` for every CAC 40 ticker probed.
    The ``yf.Ticker.isin`` *attribute* occasionally returns a value, but the
    value is unrelated to the Paris listing (e.g. it returned a Canadian
    ISIN ``CA50244Q1037`` for ``MC.PA``). Treat ``yf.Ticker.isin`` as
    untrustworthy and only consult ``info.get("isin")``, matching the DAX
    adapter's behaviour.
  * Euronext's public live endpoints either require POST with a CSRF token
    or return 403 to unauthenticated browser-style GETs, so they are not a
    reliable scrape target.
  * Wikipedia's CAC 40 page is reachable with a polite (descriptive) UA;
    a bare ``Mozilla/5.0`` UA is 403'd by the WMF edge. The components
    table lists 40 rows with Company/Sector/GICS/Ticker columns, but
    **no ISIN column** — so ISINs cannot be sourced from Wikipedia either.
  * **Conclusion**: a curated static map of ticker → (name, ISIN) is the
    reliable constituent + ISIN source. yfinance still drives all live
    financial fields; OpenFIGI is still called as a best-effort enrichment
    and remains the source-of-record once it surfaces ISINs.

Notable composition details:

  * ``MT.AS`` (ArcelorMittal) is a CAC 40 constituent but its primary
    Euronext listing is in Amsterdam, not Paris — hence the ``.AS`` suffix
    rather than ``.PA``. Its ISIN starts with ``LU``.
  * ``AIR.PA`` (Airbus), ``STLAP.PA`` (Stellantis) and ``STMPA.PA``
    (STMicroelectronics) are Paris-listed but issuer-domiciled in NL, so
    their ISINs begin with ``NL`` rather than ``FR``.

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
OPENFIGI_EXCH_CODE = "FP"  # Euronext Paris on OpenFIGI
SOURCE_LABEL = "yfinance (unofficial)"
INDEX_NAME = "CAC 40"
INDEX_COUNTRY = "FR"


@dataclass(frozen=True, slots=True)
class _Member:
    ticker: str
    name: str
    isin: str
    weight: float | None = None  # filled when authoritative source provides it


# CAC 40 composition. Curated static map; review when Euronext rebalances
# (typically quarterly). ISINs are ISO 6166 codes published by Euronext.
CAC40_MEMBERS: tuple[_Member, ...] = (
    _Member("AC.PA", "Accor SA", "FR0000120404"),
    _Member("AI.PA", "Air Liquide SA", "FR0000120073"),
    _Member("AIR.PA", "Airbus SE", "NL0000235190"),
    _Member("MT.AS", "ArcelorMittal SA", "LU1598757687"),
    _Member("CS.PA", "AXA SA", "FR0000120628"),
    _Member("BNP.PA", "BNP Paribas SA", "FR0000131104"),
    _Member("EN.PA", "Bouygues SA", "FR0000120503"),
    _Member("BVI.PA", "Bureau Veritas SA", "FR0006174348"),
    _Member("CAP.PA", "Capgemini SE", "FR0000125338"),
    _Member("CA.PA", "Carrefour SA", "FR0000120172"),
    _Member("ACA.PA", "Crédit Agricole SA", "FR0000045072"),
    _Member("BN.PA", "Danone SA", "FR0000120644"),
    _Member("DSY.PA", "Dassault Systèmes SE", "FR0014003TT8"),
    _Member("EDEN.PA", "Edenred SE", "FR0010908533"),
    _Member("ENGI.PA", "Engie SA", "FR0010208488"),
    _Member("EL.PA", "EssilorLuxottica SA", "FR0000121667"),
    _Member("ERF.PA", "Eurofins Scientific SE", "FR0014000MR3"),
    _Member("RMS.PA", "Hermès International SCA", "FR0000052292"),
    _Member("KER.PA", "Kering SA", "FR0000121485"),
    _Member("OR.PA", "L'Oréal SA", "FR0000120321"),
    _Member("LR.PA", "Legrand SA", "FR0010307819"),
    _Member("MC.PA", "LVMH Moët Hennessy Louis Vuitton SE", "FR0000121014"),
    # Michelin: was FR001400AJD7 (fails ISO 6166 check digit). Authoritative
    # ISIN per Euronext instrument search: FR001400AJ45 (Compagnie Générale
    # des Établissements Michelin, the post-2024 SCA → SE structure).
    _Member("ML.PA", "Michelin (Cie Générale des Étab.) SCA", "FR001400AJ45"),
    _Member("ORA.PA", "Orange SA", "FR0000133308"),
    _Member("RI.PA", "Pernod Ricard SA", "FR0000120693"),
    _Member("PUB.PA", "Publicis Groupe SA", "FR0000130577"),
    _Member("RNO.PA", "Renault SA", "FR0000131906"),
    _Member("SAF.PA", "Safran SA", "FR0000073272"),
    _Member("SGO.PA", "Compagnie de Saint-Gobain SA", "FR0000125007"),
    _Member("SAN.PA", "Sanofi SA", "FR0000120578"),
    _Member("SU.PA", "Schneider Electric SE", "FR0000121972"),
    _Member("GLE.PA", "Société Générale SA", "FR0000130809"),
    _Member("STLAP.PA", "Stellantis N.V.", "NL00150001Q9"),
    _Member("STMPA.PA", "STMicroelectronics N.V.", "NL0000226223"),
    _Member("TEP.PA", "Teleperformance SE", "FR0000051807"),
    _Member("HO.PA", "Thales SA", "FR0000121329"),
    _Member("TTE.PA", "TotalEnergies SE", "FR0000120271"),
    _Member("URW.PA", "Unibail-Rodamco-Westfield SE", "FR0013326246"),
    _Member("VIE.PA", "Veolia Environnement SA", "FR0000124141"),
    _Member("DG.PA", "Vinci SA", "FR0000125486"),
)

assert len(CAC40_MEMBERS) == 40, (
    f"CAC40_MEMBERS has {len(CAC40_MEMBERS)} entries, expected 40"
)

# Tests and callers occasionally want a plain ticker→ISIN map.
CAC40_ISINS: dict[str, str] = {m.ticker: m.isin for m in CAC40_MEMBERS}


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
    issuer domicile. The CAC 40 prices in Paris/Amsterdam (Euronext) in
    EUR; every constituent is tagged FR regardless of issuer domicile
    (e.g. Airbus is NL-domiciled, ArcelorMittal LU, Stellantis NL — all
    treated as FR for index-listing purposes).
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
        weight=member.weight,
    )


async def _fetch_member(
    client: httpx.AsyncClient, member: _Member
) -> Constituent:
    """Fetch all upstream data for one CAC 40 member; never raises."""
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


class CAC40Adapter(IndexAdapter):
    """Adapter for the CAC 40 index."""

    name: str = INDEX_NAME
    country: str = INDEX_COUNTRY
    source: str = SOURCE_LABEL

    def __init__(self, members: tuple[_Member, ...] = CAC40_MEMBERS) -> None:
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
