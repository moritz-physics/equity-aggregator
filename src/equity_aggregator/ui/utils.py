"""Pure helpers used by the Streamlit UI.

Kept Streamlit-free so they can be unit-tested without any UI machinery.
Display formatting (market cap, yield) and result-side filtering live here;
the Streamlit layer is a thin wiring layer on top.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, cast

import pandas as pd  # pyright: ignore[reportMissingTypeStubs]

from equity_aggregator.core.models import Constituent

DASH = "—"

DATAFRAME_COLUMNS: tuple[str, ...] = (
    "Ticker",
    "Company",
    "ISIN",
    "Country",
    "Weight %",
    "Price",
    "Currency",
    "Ex-Div Date",
    "TTM Div Yield",
    "Beta",
    "Market Cap",
    "Sector",
)


def format_market_cap(value: float | None) -> str:
    """Compact, EUR-prefixed market cap. ``None`` renders as an em-dash."""
    if value is None:
        return DASH
    abs_value = abs(value)
    if abs_value >= 1_000_000_000_000:
        return f"€ {value / 1_000_000_000_000:.1f}T"
    if abs_value >= 1_000_000_000:
        return f"€ {value / 1_000_000_000:.1f}B"
    if abs_value >= 1_000_000:
        return f"€ {value / 1_000_000:.1f}M"
    if abs_value >= 1_000:
        return f"€ {value / 1_000:.1f}K"
    return f"€ {value:.0f}"


def format_yield(value: float | None) -> str:
    """Yield is stored as a percent number (e.g. 2.45 = 2.45%)."""
    if value is None:
        return DASH
    return f"{value:.2f}%"


def filter_constituents(
    constituents: Iterable[Constituent],
    search: str = "",
    sectors: Iterable[str] | None = None,
    div_only: bool = False,
) -> list[Constituent]:
    """Apply UI filters. Empty inputs are pass-throughs."""
    sector_set = {s for s in (sectors or []) if s}
    needle = search.strip().lower()

    out: list[Constituent] = []
    for c in constituents:
        if needle:
            haystack = " ".join(
                part for part in (c.ticker, c.name, c.isin or "") if part
            ).lower()
            if needle not in haystack:
                continue
        if sector_set and (c.sector or "") not in sector_set:
            continue
        if div_only and not (c.ttm_div_yield is not None and c.ttm_div_yield > 0):
            continue
        out.append(c)
    return out


_FIELD_TO_COLUMN: dict[str, str] = {
    "Company": "Company",
    "Ticker": "Ticker",
    "Country": "Country",
    "Sector": "Sector",
    "Currency": "Currency",
    "Market Cap": "Market Cap",
    "Price": "Price",
    "TTM Div Yield": "TTM Div Yield",
    "Beta": "Beta",
}


def _to_numeric(series: Any) -> Any:
    return cast(Any, pd).to_numeric(series, errors="coerce")


def _rule_mask(df: pd.DataFrame, rule: dict[str, Any]) -> Any:
    col = _FIELD_TO_COLUMN[str(rule["field"])]
    op = str(rule["operator"])
    val = rule.get("value")
    val2 = rule.get("value2")
    series = cast(Any, df[col])
    all_true = pd.Series([True] * len(df), index=df.index)

    if op in ("contains", "not contains"):
        if val is None or val == "":
            return all_true
        mask = series.astype(str).str.contains(str(val), case=False, na=False)
        return ~mask if op == "not contains" else mask
    if op == "is":
        if val is None or val == "":
            return all_true
        return series == val
    if op == "is not":
        if val is None or val == "":
            return all_true
        return series != val
    if op in ("<", ">", "=", "between"):
        num = _to_numeric(series)
        if val is None:
            return all_true
        if op == "<":
            return num < float(val)
        if op == ">":
            return num > float(val)
        if op == "=":
            return num == float(val)
        if val2 is None:
            return all_true
        return (num >= float(val)) & (num <= float(val2))
    if op == "no dividend":
        num = _to_numeric(series).fillna(0)
        return num == 0
    return all_true


def apply_advanced_filters(
    df: pd.DataFrame, rules: list[dict[str, Any]]
) -> pd.DataFrame:
    """Apply a list of advanced filter rules. Empty rules = pass-through.

    Rule shape:
        {"connector": "AND"|"OR"|None, "field": str, "operator": str,
         "value": Any, "value2": Any | None}

    Connector on the first rule is ignored; subsequent rules combine left-to-right.
    """
    if not rules:
        return df
    mask = _rule_mask(df, rules[0])
    for rule in rules[1:]:
        m = _rule_mask(df, rule)
        if rule.get("connector") == "OR":
            mask = mask | m
        else:
            mask = mask & m
    return cast(pd.DataFrame, cast(Any, df)[mask])


def constituents_to_dataframe(
    constituents: Iterable[Constituent],
) -> pd.DataFrame:
    """Project Constituents into a display-order DataFrame.

    Numerics stay native (so st.column_config number formats apply); strings
    are left untouched. None values pass through — pandas renders them as NaN,
    which Streamlit shows as blank.
    """
    rows = [
        {
            "Ticker": c.ticker,
            "Company": c.name,
            "ISIN": c.isin or "",
            "Country": c.country,
            "Weight %": c.weight,
            "Price": c.price,
            "Currency": c.currency or "",
            "Ex-Div Date": c.ex_div_date,
            "TTM Div Yield": c.ttm_div_yield,
            "Beta": c.beta,
            "Market Cap": c.market_cap,
            "Sector": c.sector or "",
        }
        for c in constituents
    ]
    return pd.DataFrame(rows, columns=list(DATAFRAME_COLUMNS))
