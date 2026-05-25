"""IBEX 35 (Bolsa de Madrid) index adapter.

Aggregates per-constituent data for the IBEX 35 from:

  - **yfinance** — unofficial Yahoo Finance scraper. Used for price, currency,
    sector, beta, market cap, dividend yield, ex-dividend date, etc.
  - **OpenFIGI** — official Bloomberg identifier mapping API. Used as a
    best-effort enrichment / existence check.

Exploration findings that motivated this design:

  * ``yf.Ticker("SAN.MC").info`` returns the same field shape as XETRA /
    Paris tickers. Mapped keys used: ``longName, currentPrice, currency,
    sector, marketCap, beta, dividendYield, exDividendDate``. ``currency``
    is EUR for Madrid-listed shares; ``exchange`` reports ``MCE``.
  * ``info.get("isin")`` returns ``None`` for every IBEX 35 ticker probed —
    yfinance does not surface ISINs for Spanish listings, matching the
    DAX, CAC 40 and WIG20 findings.
  * The Bolsas y Mercados Españoles (BME) public site does not expose a
    stable JSON endpoint for IBEX 35 components; its component pages are
    JS-rendered and the documented API requires authentication. Wikipedia's
    IBEX 35 page (reachable with a descriptive User-Agent) does include a
    clean component table with Ticker / Company / Sector columns, but
    **no ISIN column** — so ISINs cannot be sourced from Wikipedia either.
  * **Conclusion**: a curated static map of ticker → (name, ISIN) is the
    reliable constituent + ISIN source. The 35-member composition was
    cross-checked against the Wikipedia component table. yfinance still
    drives all live financial fields; OpenFIGI is still called as a
    best-effort enrichment and remains the source-of-record once it
    surfaces ISINs.

Notable composition details:

  * ``MTS.MC`` (ArcelorMittal) is an IBEX 35 constituent but its issuer
    is Luxembourg-domiciled, so its ISIN begins with ``LU`` rather than
    ``ES``.
  * ``FER.MC`` (Ferrovial) re-domiciled to the Netherlands in 2023 — its
    ISIN now begins with ``NL`` rather than ``ES``.
  * All other constituents are ES-domiciled and have ISINs starting with
    ``ES``.

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
OPENFIGI_EXCH_CODE = "SM"  # Bolsa de Madrid on OpenFIGI
SOURCE_LABEL = "yfinance (unofficial)"
INDEX_NAME = "IBEX 35"
INDEX_COUNTRY = "ES"


@dataclass(frozen=True, slots=True)
class _Member:
    ticker: str
    name: str
    isin: str
    weight: float | None = None  # filled when authoritative source provides it


# IBEX 35 composition. Curated static map; review when the Technical
# Advisory Committee rebalances (twice yearly, June / December, with
# extraordinary reviews as needed). ISINs are ISO 6166 codes published by
# Iberclear (the Spanish CSD) or the relevant foreign CSD for non-ES-
# domiciled issuers.
IBEX35_MEMBERS: tuple[_Member, ...] = (
    _Member("ACS.MC", "ACS Actividades de Construcción y Servicios", "ES0167050915"),
    _Member("ACX.MC", "Acerinox S.A.", "ES0132105018"),
    _Member("AENA.MC", "Aena S.M.E. S.A.", "ES0105046009"),
    _Member("AMS.MC", "Amadeus IT Group S.A.", "ES0109067019"),
    _Member("ANA.MC", "Acciona S.A.", "ES0125220311"),
    _Member("ANE.MC", "Acciona Energía S.A.", "ES0105563003"),
    _Member("BBVA.MC", "Banco Bilbao Vizcaya Argentaria S.A.", "ES0113211835"),
    _Member("BKT.MC", "Bankinter S.A.", "ES0113679I37"),
    _Member("CABK.MC", "CaixaBank S.A.", "ES0140609019"),
    _Member("CLNX.MC", "Cellnex Telecom S.A.", "ES0105066007"),
    _Member("COL.MC", "Inmobiliaria Colonial SOCIMI S.A.", "ES0139140174"),
    _Member("ELE.MC", "Endesa S.A.", "ES0130670112"),
    _Member("ENG.MC", "Enagás S.A.", "ES0130960018"),
    _Member("FDR.MC", "Fluidra S.A.", "ES0171996087"),
    _Member("FER.MC", "Ferrovial S.E.", "NL0015001FS8"),
    _Member("GRF.MC", "Grifols S.A.", "ES0171996095"),
    _Member("IAG.MC", "International Consolidated Airlines Group S.A.", "ES0177542018"),
    _Member("IBE.MC", "Iberdrola S.A.", "ES0144580Y14"),
    _Member("IDR.MC", "Indra Sistemas S.A.", "ES0118594417"),
    _Member("ITX.MC", "Industria de Diseño Textil S.A. (Inditex)", "ES0148396007"),
    _Member("LOG.MC", "Logista Holdings S.A.", "ES0105027009"),
    _Member("MAP.MC", "Mapfre S.A.", "ES0124244E34"),
    _Member("MRL.MC", "Merlin Properties SOCIMI S.A.", "ES0105025003"),
    _Member("MTS.MC", "ArcelorMittal S.A.", "LU1598757687"),
    _Member("NTGY.MC", "Naturgy Energy Group S.A.", "ES0116870314"),
    # Puig Brands: was ES0105631009 (invalid ISO 6166 check digit). The
    # authoritative IPO ISIN per CNMV / Wikipedia is ES0105777017.
    _Member("PUIG.MC", "Puig Brands S.A.", "ES0105777017"),
    _Member("RED.MC", "Redeia Corporación S.A.", "ES0173093024"),
    _Member("REP.MC", "Repsol S.A.", "ES0173516115"),
    _Member("ROVI.MC", "Laboratorios Farmacéuticos Rovi S.A.", "ES0157261019"),
    _Member("SAB.MC", "Banco de Sabadell S.A.", "ES0113860A34"),
    _Member("SAN.MC", "Banco Santander S.A.", "ES0113900J37"),
    _Member("SCYR.MC", "Sacyr S.A.", "ES0182870214"),
    _Member("SLR.MC", "Solaria Energía y Medio Ambiente S.A.", "ES0165386014"),
    _Member("TEF.MC", "Telefónica S.A.", "ES0178430E18"),
    _Member("UNI.MC", "Unicaja Banco S.A.", "ES0180907000"),
)

assert len(IBEX35_MEMBERS) == 35, (
    f"IBEX35_MEMBERS has {len(IBEX35_MEMBERS)} entries, expected 35"
)

# Tests and callers occasionally want a plain ticker→ISIN map.
IBEX35_ISINS: dict[str, str] = {m.ticker: m.isin for m in IBEX35_MEMBERS}


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
    issuer domicile. IBEX 35 trades on the Bolsa de Madrid in EUR; every
    constituent is tagged ES regardless of issuer domicile (e.g.
    ArcelorMittal is LU-domiciled, Ferrovial is NL-domiciled after its
    2023 redomiciliation — both treated as ES for index-listing purposes).
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
    """Fetch all upstream data for one IBEX 35 member; never raises."""
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


class IBEX35Adapter(IndexAdapter):
    """Adapter for the IBEX 35 index."""

    name: str = INDEX_NAME
    country: str = INDEX_COUNTRY
    source: str = SOURCE_LABEL

    def __init__(self, members: tuple[_Member, ...] = IBEX35_MEMBERS) -> None:
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
