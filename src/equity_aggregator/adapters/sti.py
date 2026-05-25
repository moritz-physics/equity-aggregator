"""STI index adapter (Straits Times Index, 30 constituents).

Aggregates per-constituent data for the STI from:

  - **yfinance** — unofficial Yahoo Finance scraper. Used for price, currency,
    sector, beta, market cap, dividend yield, ex-dividend date, etc.
  - **OpenFIGI** — official Bloomberg identifier mapping API. Used as a
    best-effort enrichment / existence check.

Exploration findings (live probes run 2026-05-24):

  * STI tickers use the ``.SI`` suffix (Singapore Exchange / SGX).
    e.g. ``D05.SI``, ``O39.SI``, ``U11.SI``.
  * SGX's JSON API at ``api2.sgx.com`` returns 404 for the STI constituent
    endpoint. The SGX web page is a JavaScript SPA with no parseable HTML
    table. Conclusion: a curated static map is the most reliable constituent
    source.
  * ``yf.Ticker("D05.SI").info`` returns ~161 fields with SGD currency.
    Mapped keys used: ``longName, currentPrice, regularMarketPrice,
    previousClose, currency, sector, marketCap, beta, dividendYield,
    exDividendDate``. Note: ``dividendYield`` is expressed as a percentage
    (e.g. ``5.22`` means 5.22%). ``exDividendDate`` is a Unix epoch in
    seconds.
  * ``info.get("isin")`` returns ``None`` for every STI ticker probed —
    yfinance does not surface ISINs for Singapore listings. Static map is the
    reliable ISIN fallback.
  * ``info.get("country")`` returns ``"Singapore"`` for domestic listings.
    Two STI members (Hongkong Land ``H78.SI`` and Jardine Matheson ``J36.SI``)
    are priced in USD on SGX — ``currency`` will be ``"USD"`` for those
    tickers; the adapter does not override this.
  * The adapter sets ``country`` to ``"SG"`` uniformly to reflect the listing
    venue (SGX), consistent with DAX convention.
  * OpenFIGI ``/v3/mapping`` endpoint does not return ISIN in its free
    response payload; called as a best-effort enrichment only.
  * exchCode for Singapore Exchange on OpenFIGI is ``"XSES"``.
  * All 30 STI members verified as resolving in yfinance.

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
OPENFIGI_EXCH_CODE = "XSES"
SOURCE_LABEL = "yfinance (unofficial)"
INDEX_NAME = "STI"
INDEX_COUNTRY = "SG"


@dataclass(frozen=True, slots=True)
class _Member:
    ticker: str
    name: str
    isin: str
    weight: float | None = None  # filled when authoritative source provides it


# ---------------------------------------------------------------------------
# BEGIN GENERATED — scripts/gen_sti_isins.py
# Regenerate via:  uv run python scripts/gen_sti_isins.py
# Source:          State Street SPDR Straits Times Index ETF (SGX:ES3)
#                  holdings xlsx. The ETF tracks the STI, so holdings ==
#                  constituents. Cash sleeves + the JPMorgan SGD liquidity
#                  fund (1.9% sleeve, not part of the index) are filtered.
# Notes:           Earlier hand-curated map had 16 ISINs that failed the
#                  ISO 6166 check digit — those were guaranteed-wrong
#                  values regardless of the company identity. This map is
#                  the daily-truth from State Street's published holdings.
# ---------------------------------------------------------------------------
STI_MEMBERS: tuple[_Member, ...] = (
    _Member("D05.SI", "DBS Group Holdings Ltd", "SG1L01001701", 26.1695),
    _Member("O39.SI", "Oversea-Chinese Banking Corporation Limited", "SG1S04926220", 15.9945),
    _Member("U11.SI", "United Overseas Bank Limited", "SG1M31001969", 9.6304),
    _Member("Z74.SI", "Singapore Telecommunications Limited", "SG1T75931496", 6.8806),
    _Member("S68.SI", "Singapore Exchange Ltd.", "SG1J26887955", 3.7964),
    _Member("S63.SI", "Singapore Technologies Engineering Ltd", "SG1F60858221", 3.5129),
    _Member("J36.SI", "Jardine Matheson Holdings Limited", "BMG507361001", 3.4887),
    _Member("BN4.SI", "Keppel Ltd.", "SG1U68934629", 3.2124),
    _Member("C38U.SI", "CapitaLand Integrated Commercial Trust", "SG1M51904654", 2.8349),
    _Member("H78.SI", "Hongkong Land Holdings Limited", "BMG4587L1090", 2.1560),
    _Member("A17U.SI", "CapitaLand Ascendas REIT", "SG1M77906915", 2.1240),
    _Member("C6L.SI", "Singapore Airlines Ltd.", "SG1V61937297", 2.1125),
    _Member("BS6.SI", "Yangzijiang Shipbuilding (Holdings) Ltd.", "SG1U76934819", 1.9794),
    _Member("F34.SI", "Wilmar International Limited", "SG1T56930848", 1.3206),
    _Member("9CI.SI", "CapitaLand Investment Limited", "SGXE62145532", 1.2445),
    _Member("U96.SI", "Sembcorp Industries Ltd.", "SG1R50925390", 1.1373),
    _Member("U14.SI", "UOL Group Limited", "SG1S83002349", 0.9843),
    _Member("V03.SI", "Venture Corporation Limited", "SG0531000230", 0.9805),
    _Member("5E2.SI", "Seatrium Limited", "SGXE34184239", 0.9707),
    _Member("AJBU.SI", "Keppel DC REIT", "SG1AF6000009", 0.9286),
    _Member("ME8U.SI", "Mapletree Industrial Trust", "SG2C32962814", 0.8438),
    _Member("M44U.SI", "Mapletree Logistics Trust", "SG1S03926213", 0.8335),
    _Member("G13.SI", "Genting Singapore Limited", "SGXE21576413", 0.7004),
    _Member("Y92.SI", "Thai Beverage Public Co. Ltd.", "TH0902010014", 0.6937),
    _Member("C09.SI", "City Developments Limited", "SG1R89002252", 0.6746),
    _Member("S58.SI", "SATS Ltd", "SG1I52882764", 0.6047),
    _Member("J69U.SI", "Frasers Centrepoint Trust", "SG1T60930966", 0.6026),
    _Member("N2IU.SI", "Mapletree Pan Asia Commercial Trust", "SG2D18969584", 0.5967),
    _Member("BUOU.SI", "Frasers Logistics & Commercial Trust", "SG1CI9000006", 0.5671),
    _Member("D01.SI", "DFI Retail Group Holdings Limited", "BMG2624N1535", 0.3441),
)
# ---------------------------------------------------------------------------
# END GENERATED
# ---------------------------------------------------------------------------

assert len(STI_MEMBERS) == 30, (
    f"STI_MEMBERS has {len(STI_MEMBERS)} entries, expected 30"
)

# Convenience dict for external access and test assertions
STI_ISINS: dict[str, str] = {m.ticker: m.isin for m in STI_MEMBERS}


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
    """Fetch all upstream data for one STI member; never raises."""
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
            currency="SGD",
            weight=member.weight,
        )


class STIAdapter(IndexAdapter):
    """Adapter for the STI index (Straits Times Index, 30 members)."""

    name: str = INDEX_NAME
    country: str = INDEX_COUNTRY
    source: str = SOURCE_LABEL

    def __init__(self, members: tuple[_Member, ...] = STI_MEMBERS) -> None:
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
