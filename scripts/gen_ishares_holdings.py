"""Generate static constituent maps from iShares ETF holdings.

iShares publishes the daily holdings of every ETF as JSON at a stable
``.ajax?tab=all&fileType=json`` endpoint. The JSON ``aaData`` array has one
row per holding with columns:

  0 Ticker, 1 Name, 2 Sector, 3 Asset Class, 4 Market Value,
  5 Weight (%) [{display, raw}], 6 Notional, 7 Shares,
  8 ISIN, 9 Price, 10 Location, 11 Exchange, 12 Currency

We pull only ``Asset Class == "Equity"`` rows (skips cash, futures, etc.)
and emit a Python ``_Member`` tuple to stdout. Output is sorted by weight
(highest first), so the constituent order matches the index's
market-cap-weighted positioning — the UI displays them in this order.

Usage::

    uv run python scripts/gen_ishares_holdings.py ftse100
    uv run python scripts/gen_ishares_holdings.py aex

Paste the output between the BEGIN/END markers in the adapter file.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import httpx

# Fund-id, product-slug, ticker-suffix (yfinance), name in output, expected size.
FUNDS: dict[str, dict[str, Any]] = {
    "ftse100": {
        "fund_id": "251795",
        "slug": "ishares-core-ftse-100-ucits-etf-inc-fund",
        "suffix": ".L",
        "var_name": "FTSE100_MEMBERS",
        "min_size": 95,
    },
    "aex": {
        "fund_id": "251712",
        "slug": "ishares-aex-ucits-etf",
        "suffix": ".AS",
        "var_name": "AEX_MEMBERS",
        "min_size": 20,
    },
}


def _url(fund_id: str, slug: str) -> str:
    return (
        f"https://www.ishares.com/uk/individual/en/products/{fund_id}/"
        f"{slug}/1506575576011.ajax?tab=all&fileType=json"
    )


def _fetch(fund_id: str, slug: str) -> list[Any]:
    url = _url(fund_id, slug)
    with httpx.Client(timeout=30.0) as client:
        r = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        text = r.text.lstrip("﻿")
        body: Any = json.loads(text)
    rows: Any = body.get("aaData", []) if isinstance(body, dict) else []
    if not isinstance(rows, list):
        raise RuntimeError(f"unexpected aaData type: {type(rows)}")
    return rows


def _yf_ticker(raw: str, suffix: str) -> str:
    """LSE EPICs sometimes have a trailing '.' (e.g. RR., BP., NG.). yfinance
    treats the dot as the suffix delimiter, so RR. becomes RR.L (not RR..L).
    Also normalise share-class separators (BRK.B → BRK-B).
    """
    base = raw.strip().rstrip(".")
    base = base.replace(".", "-")  # share-class normalisation
    return f"{base}{suffix}"


def main(key: str) -> int:
    cfg = FUNDS.get(key)
    if cfg is None:
        print(f"unknown fund: {key}", file=sys.stderr)
        return 2

    rows = _fetch(cfg["fund_id"], cfg["slug"])
    print(f"# fetched {len(rows)} rows", file=sys.stderr)

    members: list[tuple[str, str, str, float]] = []
    skipped: list[str] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 13:
            continue
        raw_ticker = str(row[0]).strip()
        name = str(row[1]).strip()
        asset_class = str(row[3]).strip()
        weight_obj = row[5]
        isin = str(row[8]).strip() if row[8] is not None else ""

        if asset_class != "Equity":
            skipped.append(f"{raw_ticker} ({asset_class})")
            continue
        if not isin or len(isin) != 12 or isin == "-":
            skipped.append(f"{raw_ticker} (no ISIN)")
            continue
        weight = 0.0
        if isinstance(weight_obj, dict):
            raw_w = weight_obj.get("raw")
            if isinstance(raw_w, (int, float)):
                weight = float(raw_w)

        yf_t = _yf_ticker(raw_ticker, cfg["suffix"])
        members.append((yf_t, name, isin, weight))

    members.sort(key=lambda m: m[3], reverse=True)

    if skipped:
        print(f"# skipped {len(skipped)}: {skipped[:5]}...", file=sys.stderr)
    print(f"# total equities: {len(members)}", file=sys.stderr)
    if len(members) < cfg["min_size"]:
        print(
            f"# WARNING: got {len(members)} equities, expected >= {cfg['min_size']}",
            file=sys.stderr,
        )

    print(f"{cfg['var_name']}: tuple[_Member, ...] = (")
    for tic, name, isin, weight in members:
        safe_name = name.replace('"', '\\"')
        print(f'    _Member("{tic}", "{safe_name}", "{isin}", {weight:.4f}),')
    print(")")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "ftse100"))
