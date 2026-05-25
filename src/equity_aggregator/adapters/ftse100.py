"""FTSE 100 index adapter (100 constituents).

Aggregates per-constituent data for the FTSE 100 from:

  - **iShares Core FTSE 100 UCITS ETF (ISF) holdings** — authoritative
    source for the constituent list, ISINs, and index weights. The JSON
    endpoint at ``ishares.com/.../<fund>/<id>.ajax?tab=all&fileType=json``
    is updated daily and serves a structured ``aaData`` array.
  - **yfinance** — unofficial Yahoo Finance scraper. Used for price,
    currency, sector, beta, market cap, dividend yield, ex-dividend date.

Exploration findings (live probes, 2026-05-24):

  * The earlier Wikipedia-driven adapter populated the constituent list at
    runtime but had **no ISIN coverage at all** (``isin=None`` for every
    row). yfinance returns the sentinel ``-`` for LSE listings, and
    Wikipedia's FTSE 100 page has no ISIN column. For a finance
    application this is unacceptable — every row now ships with a
    verified ISIN derived from the iShares holdings file.
  * LSE quotes most equities in pence, and yfinance faithfully returns
    ``currency="GBp"`` with the price in pence (e.g. SHEL.L:
    ``currentPrice=3205.0 GBp`` ≡ £32.05). We always normalise to GBP at
    the adapter boundary so downstream code never has to remember the
    pence convention. Tickers already quoted in ``"GBP"`` are passed
    through unchanged (no double-conversion).
  * ``currentPrice`` and ``regularMarketPrice`` are populated identically
    for every sampled LSE ticker; we prefer ``currentPrice`` and fall
    back to ``regularMarketPrice``.
  * iShares' aaData row layout (positional indices, never named):
    ``0 Ticker, 1 Name, 2 Sector, 3 Asset Class, 4 MV, 5 Weight, 6 Notional,
    7 Shares, 8 ISIN, 9 Price, 10 Location, 11 Exchange, 12 Currency``.
  * Trailing-dot tickers (RR., BP., NG., BA., BT.A) become valid yfinance
    symbols by stripping the dot, then appending ``.L``. The share-class
    separator ``.`` (BT.A → BT-A) is converted to ``-`` per yfinance's
    convention.
  * Regenerate ``FTSE100_MEMBERS`` after each FTSE Russell rebalance:

        uv run python scripts/gen_ishares_holdings.py ftse100

    …and paste the output between the BEGIN/END markers below.

⚠️  yfinance is **unofficial**. Yahoo changes endpoints, field shapes, and
    rate limits without notice. iShares can also lag rebalances by a day
    or two. Cache aggressively, fail loudly on schema drift, and never
    use this as a system of record.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, cast

from equity_aggregator.adapters.base import IndexAdapter
from equity_aggregator.core.models import Constituent, Index

logger = logging.getLogger(__name__)

SOURCE_LABEL = "yfinance (unofficial)"
INDEX_NAME = "FTSE 100"
INDEX_COUNTRY = "GB"


@dataclass(frozen=True, slots=True)
class _Member:
    ticker: str
    name: str
    isin: str
    weight: float  # index weight as %, sourced from iShares ISF holdings


# ---------------------------------------------------------------------------
# BEGIN GENERATED — scripts/gen_ishares_holdings.py ftse100
# Regenerate via:  uv run python scripts/gen_ishares_holdings.py ftse100
# Source:          iShares Core FTSE 100 UCITS ETF (fund id 251795)
#                  Filtered to Equity asset class; cash/futures stripped.
# ---------------------------------------------------------------------------
FTSE100_MEMBERS: tuple[_Member, ...] = (
    _Member("HSBA.L", "HSBC HOLDINGS PLC", "GB0005405286", 9.2314),
    _Member("AZN.L", "ASTRAZENECA PLC", "GB0009895292", 8.3110),
    _Member("SHEL.L", "SHELL PLC", "GB00BP6MXD84", 7.2976),
    _Member("BATS.L", "BRITISH AMERICAN TOBACCO", "GB0002875804", 4.0765),
    _Member("RR.L", "ROLLS-ROYCE HOLDINGS PLC", "GB00B63H8491", 4.0565),
    _Member("ULVR.L", "UNILEVER PLC", "GB00BVZK7T90", 3.6251),
    _Member("BP.L", "BP PLC", "GB0007980591", 3.5086),
    _Member("RIO.L", "RIO TINTO PLC", "GB0007188757", 3.1791),
    _Member("GSK.L", "GLAXOSMITHKLINE", "GB00BN7SWP63", 3.0284),
    _Member("NG.L", "NATIONAL GRID PLC", "GB00BDR05C01", 2.5071),
    _Member("BARC.L", "BARCLAYS PLC", "GB0031348658", 2.4318),
    _Member("GLEN.L", "GLENCORE PLC", "JE00B4T3BW64", 2.3880),
    _Member("BA.L", "BAE SYSTEMS PLC", "GB0002634946", 2.3245),
    _Member("LLOY.L", "LLOYDS BANKING GROUP PLC", "GB0008706128", 2.3080),
    _Member("NWG.L", "NATWEST GROUP PLC", "GB00BM8PJY71", 1.8408),
    _Member("LSEG.L", "LONDON STOCK EXCHANGE GROUP PLC", "GB00B0SWJX34", 1.7820),
    _Member("REL.L", "RELX PLC", "GB00B2B0DG97", 1.7758),
    _Member("AAL.L", "ANGLO AMERICAN PLC", "GB00BTK05J60", 1.6003),
    _Member("CPG.L", "COMPASS GROUP PLC", "GB00BD6K4575", 1.5800),
    _Member("DGE.L", "DIAGEO PLC", "GB0002374006", 1.3968),
    _Member("STAN.L", "STANDARD CHARTERED PLC", "GB0004082847", 1.3844),
    _Member("RKT.L", "RECKITT BENCKISER GROUP PLC", "GB00BSZBP530", 1.2243),
    _Member("HLN.L", "HALEON PLC", "GB00BMX86B70", 1.2063),
    _Member("PRU.L", "PRUDENTIAL PLC", "GB0007099541", 1.1506),
    _Member("SSE.L", "SSE PLC", "GB0007908733", 1.1491),
    _Member("TSCO.L", "TESCO PLC", "GB00BLGZ9862", 1.1463),
    _Member("EXPN.L", "EXPERIAN PLC", "GB00B19NLV48", 0.9605),
    _Member("III.L", "3I GROUP PLC", "GB00B1YW4409", 0.8836),
    _Member("IMB.L", "IMPERIAL BRANDS PLC", "GB0004544929", 0.8325),
    _Member("VOD.L", "VODAFONE GROUP PLC", "GB00BH4HKS39", 0.8106),
    _Member("AV.L", "AVIVA PLC", "GB00BPQY8M80", 0.7527),
    _Member("HLMA.L", "HALMA PLC", "GB0004052071", 0.6644),
    _Member("IHG.L", "INTERCONTINENTAL HOTELS GROUP PLC", "GB00BHJYC057", 0.6421),
    _Member("SMT.L", "SCOTTISH MORTGAGE INVESTMENT TRUST", "GB00BLDYK618", 0.6313),
    _Member("NXT.L", "NEXT PLC", "GB0032089863", 0.5944),
    _Member("LGEN.L", "LEGAL AND GENERAL GROUP PLC", "GB0005603997", 0.5934),
    _Member("CCEP.L", "COCA COLA EUROPACIFIC PARTNERS PLC", "GB00BDCPN049", 0.5760),
    _Member("ANTO.L", "ANTOFAGASTA PLC", "GB0000456144", 0.5255),
    _Member("IAG.L", "INTERNATIONAL AIRLINES GROUP SA", "ES0177542018", 0.5248),
    _Member("BT-A.L", "BT GROUP PLC", "GB0030913577", 0.4901),
    _Member("RTO.L", "RENTOKIL INITIAL PLC", "GB00B082RF11", 0.4640),
    _Member("INF.L", "INFORMA PLC", "GB00BMJ6DW54", 0.4126),
    _Member("UU.L", "UNITED UTILITIES GROUP PLC", "GB00B39J2M42", 0.4021),
    _Member("SN.L", "SMITH AND NEPHEW PLC", "GB0009223206", 0.3855),
    _Member("SGRO.L", "SEGRO REIT PLC", "GB00B5ZN1N88", 0.3811),
    _Member("DPLM.L", "DIPLOMA PLC", "GB0001826634", 0.3633),
    _Member("CNA.L", "CENTRICA PLC", "GB00B033F229", 0.3547),
    _Member("EDV.L", "ENDEAVOUR MINING", "GB00BL6K5J42", 0.3494),
    _Member("ADM.L", "ADMIRAL GROUP PLC", "GB00B02J6398", 0.3444),
    _Member("CCH.L", "COCA COLA HBC AG", "CH0198251305", 0.3411),
    _Member("ITRK.L", "INTERTEK GROUP PLC", "GB0031638363", 0.3341),
    _Member("SGE.L", "THE SAGE GROUP PLC", "GB00B8C3BL03", 0.3284),
    _Member("SVT.L", "SEVERN TRENT PLC", "GB00B1FH8J72", 0.3270),
    _Member("SMIN.L", "SMITHS GROUP PLC", "GB00B1WY2338", 0.3089),
    _Member("BNZL.L", "BUNZL", "GB00B0744B38", 0.3047),
    _Member("BEZ.L", "BEAZLEY PLC", "GB00BYQ0JC66", 0.2945),
    _Member("PCT.L", "POLAR CAPITAL TECHNOLOGY TRUST PLC", "GB00BR3YV268", 0.2862),
    _Member("PSON.L", "PEARSON PLC", "GB0006776081", 0.2859),
    _Member("MKS.L", "MARKS AND SPENCER GROUP PLC", "GB0031274896", 0.2836),
    _Member("MNG.L", "M&G PLC", "GB00BKFB1C65", 0.2644),
    _Member("IMI.L", "IMI PLC", "GB00BGLP8L22", 0.2641),
    _Member("WEIR.L", "WEIR GROUP PLC", "GB0009465807", 0.2520),
    _Member("FCIT.L", "F&C INVESTMENT TRUST PLC", "GB00BS88V647", 0.2511),
    _Member("GAW.L", "GAMES WORKSHOP GROUP PLC", "GB0003718474", 0.2468),
    _Member("MRO.L", "MELROSE INDUSTRIES PLC", "GB00BNGDN821", 0.2466),
    _Member("STJ.L", "ST JAMESS PLACE PLC", "GB0007669376", 0.2423),
    _Member("FRES.L", "FRESNILLO PLC", "GB00B2QPKJ12", 0.2387),
    _Member("HSX.L", "HISCOX LTD", "BMG4593F1389", 0.2363),
    _Member("IGG.L", "IG GROUP HOLDINGS PLC", "GB00B06QFB75", 0.2327),
    _Member("SDLF.L", "STANDARD LIFE PLC", "GB00BGXQNP29", 0.2284),
    _Member("ABF.L", "ASSOCIATED BRITISH FOODS PLC", "GB0006731235", 0.2121),
    _Member("ICG.L", "ICG PLC", "GB00BYT1DJ19", 0.2120),
    _Member("BAB.L", "BABCOCK INTERNATIONAL GROUP PLC", "GB0009697037", 0.2102),
    _Member("DCC.L", "DCC PLC", "IE0002424939", 0.2102),
    _Member("SBRY.L", "SAINSBURY(J) PLC", "GB00B019KW72", 0.2094),
    _Member("KGF.L", "KINGFISHER PLC", "GB0033195214", 0.1996),
    _Member("SPX.L", "SPIRAX GROUP PLC", "GB00BWFGQN14", 0.1993),
    _Member("ALW.L", "ALLIANCE WITAN PLC", "GB00B11V7W98", 0.1936),
    _Member("LAND.L", "LAND SECURITIES GROUP REIT PLC", "GB00BYW0PQ60", 0.1822),
    _Member("SDR.L", "SCHRODERS PLC", "GB00BP9LHF23", 0.1690),
    _Member("LMP.L", "LONDONMETRIC PROPERTY REIT PLC", "GB00B4WFW713", 0.1689),
    _Member("HWDN.L", "HOWDEN JOINERY GROUP PLC", "GB0005576813", 0.1613),
    _Member("WTB.L", "WHITBREAD PLC", "GB00B1KJJ408", 0.1586),
    _Member("BRBY.L", "BURBERRY GROUP PLC", "GB0031743007", 0.1586),
    _Member("CTEC.L", "CONVATEC GROUP PLC", "GB00BD3VFW73", 0.1560),
    _Member("CRDA.L", "CRODA INTERNATIONAL PLC", "GB00BJFFLV09", 0.1546),
    _Member("BLND.L", "BRITISH LAND REIT PLC", "GB0001367019", 0.1523),
    _Member("AUTO.L", "AUTOTRADER GROUP PLC", "GB00BVYVFW23", 0.1509),
    _Member("MTLN.L", "METLEN ENERGY & METALS PLC", "GB00BTQGS779", 0.1452),
    _Member("BGEO.L", "LION FINANCE GROUP PLC", "GB00BF4HYT85", 0.1436),
    _Member("BBOX.L", "TRITAX BIG BOX REIT PLC", "GB00BG49KP99", 0.1417),
    _Member("BTRW.L", "BARRATT REDROW PLC", "GB0000811801", 0.1343),
    _Member("ENT.L", "ENTAIN PLC", "IM00B5VQMV65", 0.1292),
    _Member("PSN.L", "PERSIMMON PLC", "GB0006825383", 0.1292),
    _Member("RMV.L", "RIGHTMOVE PLC", "GB00BGDT3G23", 0.1265),
    _Member("MNDI.L", "MONDI PLC", "GB00BMWC6P49", 0.1247),
    _Member("BKG.L", "BERKELEY GROUP HOLDINGS (THE) PLC", "GB00BP0RGD03", 0.1194),
    _Member("AAF.L", "AIRTEL AFRICA PLC", "GB00BKDRYJ47", 0.0898),
    _Member("JD.L", "JD SPORTS FASHION PLC", "GB00BM8Q5M07", 0.0721),
    _Member("EVR.L", "EVRAZ", "GB00B71N6K86", 0.0002),
)
# ---------------------------------------------------------------------------
# END GENERATED
# ---------------------------------------------------------------------------

assert 95 <= len(FTSE100_MEMBERS) <= 110, (
    f"FTSE100_MEMBERS has {len(FTSE100_MEMBERS)} entries, expected ~100"
)

FTSE100_ISINS: dict[str, str] = {m.ticker: m.isin for m in FTSE100_MEMBERS}


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
    so downstream code only sees a single canonical unit.
    """
    if currency == "GBp":
        converted = round(price / 100, 4) if price is not None else None
        return converted, "GBP"
    return price, currency or "GBP"


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


def _build_constituent(member: _Member, info: dict[str, Any]) -> Constituent:
    """Build a Constituent, normalising GBp prices to GBP. The static map is
    the source of truth for ISIN; yfinance just provides live financial fields.
    """
    name = (
        _coerce_str(info.get("longName"))
        or _coerce_str(info.get("shortName"))
        or member.name
    )

    raw_price = _coerce_float(info.get("currentPrice"))
    if raw_price is None:
        raw_price = _coerce_float(info.get("regularMarketPrice"))
    if raw_price is None:
        raw_price = _coerce_float(info.get("previousClose"))

    price, currency = _normalise_price(raw_price, _coerce_str(info.get("currency")))

    return Constituent(
        ticker=member.ticker,
        name=name,
        isin=member.isin,
        isin_source="static",
        country=INDEX_COUNTRY,
        price=price,
        currency=currency,
        ex_div_date=_epoch_to_date(info.get("exDividendDate")),
        ttm_div_yield=_coerce_float(info.get("dividendYield")),
        beta=_coerce_float(info.get("beta")),
        market_cap=_coerce_float(info.get("marketCap")),
        sector=_coerce_str(info.get("sector")),
        weight=member.weight,
    )


async def _fetch_member(member: _Member) -> Constituent:
    """Fetch yfinance data for one FTSE 100 member; never raises."""
    try:
        info = await _fetch_yf_info(member.ticker)
        return _build_constituent(member, info)
    except Exception as exc:
        logger.warning("FTSE 100: failed to fetch %s: %s", member.ticker, exc)
        return Constituent(
            ticker=member.ticker,
            name=member.name,
            isin=member.isin,
            isin_source="static",
            country=INDEX_COUNTRY,
            currency="GBP",
            weight=member.weight,
        )


class FTSE100Adapter(IndexAdapter):
    """Adapter for the FTSE 100 index."""

    name: str = INDEX_NAME
    country: str = INDEX_COUNTRY
    source: str = SOURCE_LABEL

    def __init__(self, members: tuple[_Member, ...] = FTSE100_MEMBERS) -> None:
        self._members = members

    async def fetch_constituents(self) -> Index:
        constituents = await asyncio.gather(
            *(_fetch_member(m) for m in self._members)
        )
        return Index(
            name=self.name,
            country=self.country,
            constituents=list(constituents),
            fetched_at=datetime.now(tz=UTC),
            source=self.source,
        )
