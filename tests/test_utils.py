"""Unit tests for ui/utils.py — Streamlit-free."""

from __future__ import annotations

import pandas as pd

from equity_aggregator.core.models import Constituent
from equity_aggregator.ui.utils import (
    DASH,
    DATAFRAME_COLUMNS,
    apply_advanced_filters,
    constituents_to_dataframe,
    filter_constituents,
    format_market_cap,
    format_yield,
)


def _c(
    ticker: str,
    *,
    name: str | None = None,
    isin: str | None = None,
    sector: str | None = None,
    ttm: float | None = None,
) -> Constituent:
    return Constituent(
        ticker=ticker,
        name=name if name is not None else ticker,
        isin=isin,
        country="DE",
        sector=sector,
        ttm_div_yield=ttm,
    )


# ── format_market_cap ──────────────────────────────────────────────────────


def test_format_market_cap_none() -> None:
    assert format_market_cap(None) == DASH


def test_format_market_cap_zero() -> None:
    assert format_market_cap(0) == "€ 0"


def test_format_market_cap_millions() -> None:
    assert format_market_cap(1_200_000) == "€ 1.2M"


def test_format_market_cap_billions() -> None:
    assert format_market_cap(82_400_000_000) == "€ 82.4B"


def test_format_market_cap_trillions() -> None:
    assert format_market_cap(1_200_000_000_000) == "€ 1.2T"


# ── format_yield ───────────────────────────────────────────────────────────


def test_format_yield_none() -> None:
    assert format_yield(None) == DASH


def test_format_yield_zero() -> None:
    assert format_yield(0.0) == "0.00%"


def test_format_yield_value() -> None:
    assert format_yield(2.45) == "2.45%"


# ── filter_constituents ────────────────────────────────────────────────────


def test_filter_constituents_search_matches_ticker() -> None:
    a = _c("SAP.DE", name="SAP SE")
    b = _c("ADS.DE", name="adidas AG")
    out = filter_constituents([a, b], search="sap")
    assert [c.ticker for c in out] == ["SAP.DE"]


def test_filter_constituents_search_matches_isin_case_insensitive() -> None:
    a = _c("SAP.DE", name="SAP SE", isin="DE0007164600")
    b = _c("ADS.DE", name="adidas AG", isin="DE000A1EWWW0")
    out = filter_constituents([a, b], search="de000a1ewww0")
    assert [c.ticker for c in out] == ["ADS.DE"]


def test_filter_constituents_search_matches_company_substring() -> None:
    a = _c("ADS.DE", name="adidas AG")
    b = _c("BMW.DE", name="Bayerische Motoren Werke AG")
    out = filter_constituents([a, b], search="motoren")
    assert [c.ticker for c in out] == ["BMW.DE"]


def test_filter_constituents_sector_filter() -> None:
    a = _c("SAP.DE", sector="Technology")
    b = _c("ADS.DE", sector="Consumer Cyclical")
    c = _c("BAS.DE", sector="Basic Materials")
    out = filter_constituents([a, b, c], sectors=["Technology", "Basic Materials"])
    assert {x.ticker for x in out} == {"SAP.DE", "BAS.DE"}


def test_filter_constituents_div_only_excludes_none_and_zero() -> None:
    a = _c("SAP.DE", ttm=2.5)
    b = _c("ZAL.DE", ttm=0.0)
    c = _c("XYZ.DE", ttm=None)
    out = filter_constituents([a, b, c], div_only=True)
    assert [x.ticker for x in out] == ["SAP.DE"]


def test_filter_constituents_combined() -> None:
    a = _c("SAP.DE", name="SAP SE", sector="Technology", ttm=1.2)
    b = _c("ADS.DE", name="adidas AG", sector="Consumer Cyclical", ttm=1.8)
    c = _c("IFX.DE", name="Infineon", sector="Technology", ttm=None)
    out = filter_constituents(
        [a, b, c], search="s", sectors=["Technology"], div_only=True
    )
    assert [x.ticker for x in out] == ["SAP.DE"]


def test_filter_constituents_empty_inputs_passthrough() -> None:
    members = [_c("A.DE"), _c("B.DE")]
    out = filter_constituents(members)
    assert [x.ticker for x in out] == ["A.DE", "B.DE"]


# ── constituents_to_dataframe ──────────────────────────────────────────────


def test_constituents_to_dataframe_columns_and_count() -> None:
    members = [_c("A.DE"), _c("B.DE"), _c("C.DE")]
    df = constituents_to_dataframe(members)
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == list(DATAFRAME_COLUMNS)
    assert len(df) == 3


def test_constituents_to_dataframe_empty() -> None:
    df = constituents_to_dataframe([])
    assert list(df.columns) == list(DATAFRAME_COLUMNS)
    assert len(df) == 0


def test_constituents_to_dataframe_preserves_values() -> None:
    c = Constituent(
        ticker="SAP.DE",
        name="SAP SE",
        isin="DE0007164600",
        country="DE",
        price=210.0,
        currency="EUR",
        ttm_div_yield=1.05,
        beta=1.0,
        market_cap=250_000_000_000.0,
        sector="Technology",
    )
    df = constituents_to_dataframe([c])
    row = df.iloc[0]
    assert row["Ticker"] == "SAP.DE"
    assert row["ISIN"] == "DE0007164600"
    assert row["Price"] == 210.0
    assert row["Sector"] == "Technology"


# ── apply_advanced_filters ─────────────────────────────────────────────────


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Company": "SAP SE",   "Ticker": "SAP.DE", "Sector": "Technology",
             "Market Cap": 250_000_000_000, "Price": 210.0, "TTM Div Yield": 1.05},
            {"Company": "Adidas",   "Ticker": "ADS.DE", "Sector": "Consumer",
             "Market Cap": 30_000_000_000,  "Price": 180.0, "TTM Div Yield": 0.0},
            {"Company": "BNP",      "Ticker": "BNP.PA", "Sector": "Financials",
             "Market Cap": 80_000_000_000,  "Price": 65.0,  "TTM Div Yield": 5.5},
            {"Company": "Infineon", "Ticker": "IFX.DE", "Sector": "Technology",
             "Market Cap": 40_000_000_000,  "Price": 35.0,  "TTM Div Yield": None},
        ]
    )


def test_adv_empty_rules_returns_df_unchanged() -> None:
    df = _sample_df()
    out = apply_advanced_filters(df, [])
    assert len(out) == len(df)


def test_adv_contains_matches() -> None:
    df = _sample_df()
    out = apply_advanced_filters(
        df, [{"connector": None, "field": "Company", "operator": "contains",
              "value": "sap", "value2": None}]
    )
    assert out["Ticker"].tolist() == ["SAP.DE"]


def test_adv_not_contains_excludes() -> None:
    df = _sample_df()
    out = apply_advanced_filters(
        df, [{"connector": None, "field": "Company", "operator": "not contains",
              "value": "sap", "value2": None}]
    )
    assert "SAP.DE" not in out["Ticker"].tolist()


def test_adv_is_exact_sector() -> None:
    df = _sample_df()
    out = apply_advanced_filters(
        df, [{"connector": None, "field": "Sector", "operator": "is",
              "value": "Technology", "value2": None}]
    )
    assert set(out["Ticker"].tolist()) == {"SAP.DE", "IFX.DE"}


def test_adv_is_not_excludes_sector() -> None:
    df = _sample_df()
    out = apply_advanced_filters(
        df, [{"connector": None, "field": "Sector", "operator": "is not",
              "value": "Financials", "value2": None}]
    )
    assert "BNP.PA" not in out["Ticker"].tolist()


def test_adv_gt_on_market_cap() -> None:
    df = _sample_df()
    out = apply_advanced_filters(
        df, [{"connector": None, "field": "Market Cap", "operator": ">",
              "value": 100_000_000_000, "value2": None}]
    )
    assert out["Ticker"].tolist() == ["SAP.DE"]


def test_adv_between_price() -> None:
    df = _sample_df()
    out = apply_advanced_filters(
        df, [{"connector": None, "field": "Price", "operator": "between",
              "value": 50.0, "value2": 200.0}]
    )
    assert set(out["Ticker"].tolist()) == {"ADS.DE", "BNP.PA"}


def test_adv_no_dividend() -> None:
    df = _sample_df()
    out = apply_advanced_filters(
        df, [{"connector": None, "field": "TTM Div Yield",
              "operator": "no dividend", "value": None, "value2": None}]
    )
    # ADS has 0, IFX has None (treated as 0).
    assert set(out["Ticker"].tolist()) == {"ADS.DE", "IFX.DE"}


def test_adv_and_combination() -> None:
    df = _sample_df()
    rules = [
        {"connector": None, "field": "Sector", "operator": "is",
         "value": "Technology", "value2": None},
        {"connector": "AND", "field": "Market Cap", "operator": ">",
         "value": 100_000_000_000, "value2": None},
    ]
    out = apply_advanced_filters(df, rules)
    assert out["Ticker"].tolist() == ["SAP.DE"]


def test_adv_or_combination() -> None:
    df = _sample_df()
    rules = [
        {"connector": None, "field": "Sector", "operator": "is",
         "value": "Financials", "value2": None},
        {"connector": "OR", "field": "Sector", "operator": "is",
         "value": "Consumer", "value2": None},
    ]
    out = apply_advanced_filters(df, rules)
    assert set(out["Ticker"].tolist()) == {"BNP.PA", "ADS.DE"}


def test_adv_rule_with_none_value_does_not_crash() -> None:
    df = _sample_df()
    rules = [
        {"connector": None, "field": "Company", "operator": "contains",
         "value": None, "value2": None},
    ]
    out = apply_advanced_filters(df, rules)
    # None value is a pass-through, so all rows remain.
    assert len(out) == len(df)
