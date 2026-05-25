"""AEX index adapter (Amsterdam Exchange Index, 25 constituents).

Aggregates per-constituent data for the AEX from:

  - **yfinance** — unofficial Yahoo Finance scraper. Used for price, currency,
    sector, beta, market cap, dividend yield, ex-dividend date, etc.
  - **OpenFIGI** — official Bloomberg identifier mapping API. Used as a
    best-effort enrichment / existence check.

Exploration findings (live probes run 2026-05-24):

  * AEX tickers use the ``.AS`` suffix (Amsterdam Stock Exchange / Euronext
    Amsterdam). e.g. ``ASML.AS``, ``HEIA.AS``, ``INGA.AS``.
  * Euronext's live index composition API redirects to their homepage and
    does not return machine-readable constituent data without a session cookie.
    Wikipedia's AEX page requires ``lxml`` (not installed). Conclusion: a
    curated static map is the most reliable constituent source.
  * ``yf.Ticker("ASML.AS").info`` returns ~170 fields with EUR currency.
    Mapped keys used: ``longName, currentPrice, regularMarketPrice,
    previousClose, currency, sector, marketCap, beta, dividendYield,
    exDividendDate``. Note: ``dividendYield`` is expressed as a percentage
    (e.g. ``0.77`` means 0.77%).  ``exDividendDate`` is a Unix epoch in
    seconds.
  * ``info.get("isin")`` returns ``None`` for every AEX ticker probed —
    yfinance does not surface ISINs for Amsterdam listings. Static map is the
    reliable ISIN fallback.
  * ``info.get("country")`` returns ``"Netherlands"`` (or occasionally the
    company's domicile). The adapter sets country to ``"NL"`` uniformly to
    reflect the listing venue (Euronext Amsterdam), consistent with DAX
    convention.
  * OpenFIGI ``/v3/mapping`` endpoint does not return ISIN in its free
    response payload; called as a best-effort enrichment only.
  * exchCode for Euronext Amsterdam on OpenFIGI is ``"XAMS"``.
  * All 25 AEX members verified as resolving in yfinance with EUR currency.

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
OPENFIGI_EXCH_CODE = "XAMS"
SOURCE_LABEL = "yfinance (unofficial)"
INDEX_NAME = "AEX"
INDEX_COUNTRY = "NL"


@dataclass(frozen=True, slots=True)
class _Member:
    ticker: str
    name: str
    isin: str
    weight: float  # index weight as %, sourced from iShares AEX ETF holdings


# ---------------------------------------------------------------------------
# BEGIN GENERATED — scripts/gen_ishares_holdings.py aex
# Regenerate via:  uv run python scripts/gen_ishares_holdings.py aex
# Source:          iShares AEX UCITS ETF holdings (fund id 251712)
#                  Composition tracks the AEX index; only Equity asset class
#                  rows are kept (cash/futures filtered).
# Notes:           The earlier hand-curated map carried several stale ISINs
#                  (BESI: NL0000339760 → NL0012866412, Aegon: NL0000303709 →
#                  BMG0112X1056 after the 2023 Bermuda redomicile, Unilever:
#                  GB00B10RZP78 → GB00BVZK7T90 after consolidation, DSM-
#                  Firmenich: NL0000009827 → CH1216478797 after merger).
#                  Pulling from the ETF cures this class of bug at the source.
# ---------------------------------------------------------------------------
AEX_MEMBERS: tuple[_Member, ...] = (
    _Member("ASML.AS", "ASML HOLDING NV", "NL0010273215", 16.3087),
    _Member("SHELL.AS", "SHELL PLC", "GB00BP6MXD84", 13.5003),
    _Member("UNA.AS", "UNILEVER PLC", "GB00BVZK7T90", 11.6423),
    _Member("INGA.AS", "ING GROEP NV", "NL0011821202", 8.2363),
    _Member("REN.AS", "RELX PLC", "GB00B2B0DG97", 5.6395),
    _Member("PRX.AS", "PROSUS NV CLASS N", "NL0013654783", 5.0817),
    _Member("ASM.AS", "ASM INTERNATIONAL NV", "NL0000334118", 4.6081),
    _Member("AD.AS", "KONINKLIJKE AHOLD DELHAIZE NV", "NL0011794037", 3.5617),
    _Member("ADYEN.AS", "ADYEN NV", "NL0012969182", 3.2080),
    _Member("MT.AS", "ARCELORMITTAL SA", "LU1598757687", 2.5078),
    _Member("UMG.AS", "UNIVERSAL MUSIC GROUP NV", "NL0015000IY2", 2.4277),
    _Member("ABN.AS", "ABN AMRO BANK NV", "NL0011540547", 2.2193),
    _Member("HEIA.AS", "HEINEKEN NV", "NL0000009165", 2.1436),
    _Member("NN.AS", "NN GROUP NV", "NL0010773842", 2.1425),
    _Member("BESI.AS", "BE SEMICONDUCTOR INDUSTRIES NV", "NL0012866412", 2.1302),
    _Member("PHIA.AS", "KONINKLIJKE PHILIPS NV", "NL0000009538", 1.9295),
    _Member("KPN.AS", "KONINKLIJKE KPN NV", "NL0000009082", 1.9071),
    _Member("WKL.AS", "WOLTERS KLUWER NV", "NL0000395903", 1.5807),
    _Member("DSFIR.AS", "DSM FIRMENICH AG", "CH1216478797", 1.5330),
    _Member("ASRNL.AS", "ASR NEDERLAND NV", "NL0011872643", 1.0598),
    _Member("AGN.AS", "AEGON LTD", "BMG0112X1056", 1.0068),
    _Member("AKZA.AS", "AKZO NOBEL NV", "NL0013267909", 0.8413),
    _Member("MICC.AS", "MAGNUM ICE CREAM NV", "NL0015002MS2", 0.7372),
    _Member("EXO.AS", "EXOR NV", "NL0012059018", 0.6754),
    _Member("IMCD.AS", "IMCD NV", "NL0010801007", 0.6020),
    _Member("SBMO.AS", "SBM OFFSHORE NV", "NL0000360618", 0.5169),
    _Member("WDP.AS", "WAREHOUSES DE PAUW NV", "BE0974349814", 0.4588),
    _Member("INPST.AS", "INPOST SA", "LU2290522684", 0.4492),
    _Member("CVC.AS", "CVC CAPITAL PARTNERS PLC", "JE00BRX98089", 0.3654),
)
# ---------------------------------------------------------------------------
# END GENERATED
# ---------------------------------------------------------------------------

# AEX is canonically a 25-stock index, but the iShares AEX UCITS ETF that we
# pull from holds ~29 names — the index publisher (Euronext) has expanded
# coverage with recent additions (ASR, Magnum Ice Cream, EXOR, SBM Offshore,
# InPost, CVC, WDP) without removing established members. The fund is the
# authoritative source for whatever the index currently is.
assert 20 <= len(AEX_MEMBERS) <= 35, (
    f"AEX_MEMBERS has {len(AEX_MEMBERS)} entries (expected 20–35)"
)

# Convenience dict for external access and test assertions
AEX_ISINS: dict[str, str] = {m.ticker: m.isin for m in AEX_MEMBERS}


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
    """Fetch all upstream data for one AEX member; never raises."""
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


class AEXAdapter(IndexAdapter):
    """Adapter for the AEX index (Amsterdam Exchange Index, 25 members)."""

    name: str = INDEX_NAME
    country: str = INDEX_COUNTRY
    source: str = SOURCE_LABEL

    def __init__(self, members: tuple[_Member, ...] = AEX_MEMBERS) -> None:
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
