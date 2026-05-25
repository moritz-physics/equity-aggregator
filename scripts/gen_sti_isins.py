"""Generate the static STI_MEMBERS tuple for ``adapters/sti.py``.

The Straits Times Index has 30 constituents tracked by the SPDR STI ETF
(SGX:ES3). State Street publishes the daily holdings as a free xlsx that
includes ``ISIN, SEDOL, Ticker, Security Name, Weight %`` per row.

Why this file (and not Wikipedia, Euronext, OpenFIGI)?

  - Wikipedia's STI page has no ISIN column.
  - OpenFIGI's free tier does not surface ISIN in its mapping response, and
    rate-limits any ID_ISIN reverse-lookup attempt for 30 names.
  - SGX itself doesn't expose a free ISIN download for the index.
  - The SPDR ETF's holdings file is the authoritative, daily-refreshed
    list — it's what the index tracks.

Earlier hand-curated map carried 16 ISINs that fail the ISO 6166 check
digit (and were therefore *guaranteed* to be wrong, regardless of company
identity). This generator replaces them with values published by the ETF
issuer.

Usage::

    uv run python scripts/gen_sti_isins.py

Outputs Python source to stdout — paste between the BEGIN/END markers in
``src/equity_aggregator/adapters/sti.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import httpx
import openpyxl

ES3_HOLDINGS_URL = (
    "https://www.ssga.com/library-content/products/fund-data/etfs/apac/"
    "holdings-daily-sg-en-es3.xlsx"
)
TMP_XLSX = Path("/tmp/sti_es3_holdings.xlsx")


def _download() -> None:
    if TMP_XLSX.exists() and TMP_XLSX.stat().st_size > 5_000:
        return
    print(f"downloading {ES3_HOLDINGS_URL}", file=sys.stderr)
    with httpx.Client(follow_redirects=True, timeout=30.0) as client:
        r = client.get(ES3_HOLDINGS_URL, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        TMP_XLSX.write_bytes(r.content)


def _yf_ticker(raw: str) -> str:
    """SSGA writes 'D05-SG', 'BUOU-SG', etc. yfinance wants 'D05.SI'."""
    raw = raw.strip()
    if raw.endswith("-SG"):
        raw = raw[: -len("-SG")]
    return f"{raw}.SI"


def main() -> int:
    _download()
    wb = openpyxl.load_workbook(TMP_XLSX, read_only=True, data_only=True)
    ws: Any = wb.active
    if ws is None:
        raise RuntimeError("ES3 xlsx has no active worksheet")
    rows = list(ws.iter_rows(values_only=True))

    header_idx: int | None = None
    for i, row in enumerate(rows):
        if row and row[0] == "ISIN" and row[2] == "Ticker":
            header_idx = i
            break
    if header_idx is None:
        raise RuntimeError("Couldn't find header row in ES3 xlsx")

    members: list[tuple[str, str, str, float]] = []
    skipped: list[str] = []
    for row in rows[header_idx + 1 :]:
        if not row or not row[0]:
            continue
        isin = str(row[0]).strip()
        ticker_raw = str(row[2]).strip() if row[2] else ""
        name = str(row[5]).strip() if row[5] else ""
        try:
            weight = float(row[10]) if row[10] is not None else 0.0
        except (TypeError, ValueError):
            weight = 0.0

        # Skip cash sleeves, money-market funds, anything without an ISIN
        # of the expected 12-char ISO 6166 shape.
        if isin == "Unassigned" or len(isin) != 12 or not isin[:2].isalpha():
            skipped.append(f"{ticker_raw or name} ({isin})")
            continue
        # JPMorgan Liquidity Funds SICAV is a cash-management sleeve, not
        # an STI constituent.
        if "LIQUIDITY" in name.upper() or "JPMORGAN" in name.upper():
            skipped.append(f"{ticker_raw} ({name})")
            continue

        members.append((_yf_ticker(ticker_raw), name, isin, weight))

    members.sort(key=lambda m: m[3], reverse=True)

    if skipped:
        print(f"# skipped {len(skipped)}: {skipped[:5]}...", file=sys.stderr)
    print(f"# total equity constituents: {len(members)}", file=sys.stderr)

    print("STI_MEMBERS: tuple[_Member, ...] = (")
    for tic, name, isin, weight in members:
        safe_name = name.replace('"', '\\"')
        print(f'    _Member("{tic}", "{safe_name}", "{isin}", {weight:.4f}),')
    print(")")
    return 0


if __name__ == "__main__":
    sys.exit(main())
