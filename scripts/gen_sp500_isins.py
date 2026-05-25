"""Generate the static SP500_MEMBERS tuple for ``adapters/sp500.py``.

S&P 500 has ~503 constituents (3 dual-class companies contribute two
share-classes), and the index rebalances quarterly. We mirror the DAX
pattern (curated ``_Member`` tuples) but populate it from a published,
free source so we don't hand-type 500 ISINs:

  - **SSGA SPY holdings xlsx** — State Street publishes the daily holdings
    of the SPDR S&P 500 ETF (ticker SPY) as a free xlsx. The file includes
    ``Ticker``, ``Name``, ``Identifier`` (9-char CUSIP), ``SEDOL``, etc.
  - SPY tracks the full S&P 500 index, so its holdings == the constituent
    set. Cash and contra-account rows are filtered out.
  - **CUSIP → ISIN** is computed via the standard ISO 6166 check-digit
    algorithm (letters A-Z map to 10-35; from the rightmost digit, double
    every other digit; sum digits-of-products mod 10). For US-listed
    shares of foreign issuers (G-prefix CUSIPs / CINS codes), the derived
    ``US...`` ISIN is the canonical identifier for the US listing — not
    the issuer's domicile ISIN (e.g. ACN derives as USG1151C1011, valid
    for the NYSE listing; Accenture's Irish ISIN IE00B4BNMY34 is a
    separate identifier for the same equity).

Usage::

    uv run python scripts/gen_sp500_isins.py

Outputs Python source to stdout — paste between the BEGIN/END markers in
``src/equity_aggregator/adapters/sp500.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import openpyxl

SPY_HOLDINGS_URL = (
    "https://www.ssga.com/library-content/products/fund-data/etfs/us/"
    "holdings-daily-us-en-spy.xlsx"
)
TMP_XLSX = Path("/tmp/spy_holdings.xlsx")


def _expand_letters(s: str) -> str:
    """Convert each letter A-Z to its two-digit base-36 value; digits passthrough."""
    out: list[str] = []
    for ch in s:
        if ch.isdigit():
            out.append(ch)
        elif ch.isalpha():
            out.append(str(ord(ch.upper()) - ord("A") + 10))
        else:
            raise ValueError(f"unexpected char {ch!r}")
    return "".join(out)


def _isin_check_digit(payload: str) -> int:
    """ISO 6166 check digit for an 11-char ISIN base (country + national code)."""
    digits = _expand_letters(payload)
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 0:  # rightmost = position 1 (1-indexed), doubled
            n *= 2
        total += n // 10 + n % 10
    return (10 - total % 10) % 10


def cusip_to_us_isin(cusip: str) -> str:
    cusip = cusip.strip().upper()
    if len(cusip) != 9:
        raise ValueError(f"CUSIP must be 9 chars, got {len(cusip)}: {cusip!r}")
    base = f"US{cusip}"
    return base + str(_isin_check_digit(base))


def _self_test() -> None:
    # Known good: AAPL, MSFT, NVDA (US-domiciled).
    assert cusip_to_us_isin("037833100") == "US0378331005"
    assert cusip_to_us_isin("594918104") == "US5949181045"
    assert cusip_to_us_isin("67066G104") == "US67066G1040"
    print("self-test OK", file=sys.stderr)


def main() -> None:
    _self_test()
    if not TMP_XLSX.exists() or TMP_XLSX.stat().st_size < 10_000:
        print(f"downloading {SPY_HOLDINGS_URL}", file=sys.stderr)
        with httpx.Client(follow_redirects=True, timeout=30.0) as client:
            r = client.get(SPY_HOLDINGS_URL, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            TMP_XLSX.write_bytes(r.content)

    wb = openpyxl.load_workbook(TMP_XLSX, read_only=True, data_only=True)
    ws = wb.active
    if ws is None:
        raise RuntimeError("SPY xlsx has no active worksheet")
    rows = list(ws.iter_rows(values_only=True))

    header_idx: int | None = None
    for i, row in enumerate(rows):
        if row and row[0] == "Name" and "Ticker" in row:
            header_idx = i
            break
    if header_idx is None:
        raise RuntimeError("Couldn't find header row in SPY xlsx")

    header = list(rows[header_idx])
    name_i = header.index("Name")
    tic_i = header.index("Ticker")
    id_i = header.index("Identifier")

    members: list[tuple[str, str, str]] = []
    skipped: list[str] = []
    for row in rows[header_idx + 1 :]:
        if not row or not row[name_i] or not row[tic_i]:
            continue
        name = str(row[name_i]).strip()
        ticker_raw = str(row[tic_i]).strip()
        ident = str(row[id_i]).strip() if row[id_i] is not None else ""

        # Cash sleeve, contra/settlement accounts → not real equities.
        if ticker_raw == "-" or "CONTRA" in name.upper():
            skipped.append(ticker_raw or name)
            continue
        if len(ident) != 9:
            skipped.append(ticker_raw)
            continue
        try:
            isin = cusip_to_us_isin(ident)
        except ValueError:
            skipped.append(ticker_raw)
            continue
        # yfinance share-class normalisation: BRK.B → BRK-B
        yf_ticker = ticker_raw.replace(".", "-")
        members.append((yf_ticker, name, isin))

    members.sort(key=lambda t: t[0])

    print(f"# {len(members)} S&P 500 constituents (generated from SSGA SPY xlsx).",
          file=sys.stderr)
    if skipped:
        print(f"# skipped {len(skipped)}: {skipped}", file=sys.stderr)

    print("SP500_MEMBERS: tuple[_Member, ...] = (")
    for tic, name, isin in members:
        safe_name = name.replace('"', '\\"')
        print(f'    _Member("{tic}", "{safe_name}", "{isin}"),')
    print(")")
    print(f"# total: {len(members)}", file=sys.stderr)


if __name__ == "__main__":
    main()
