"""Unit tests for core.models."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from equity_aggregator.core.models import Constituent, Index, QueryResult


def test_constituent_valid_creation() -> None:
    c = Constituent(
        ticker="ADS.DE",
        name="adidas AG",
        isin="DE000A1EWWW0",
        isin_source="static",
        country="DE",
        price=154.5,
        currency="EUR",
        ex_div_date=date(2025, 5, 8),
        ttm_div_yield=1.81,
        beta=1.209,
        market_cap=27_400_000_000.0,
        sector="Consumer Cyclical",
    )
    assert c.ticker == "ADS.DE"
    assert c.name == "adidas AG"
    assert c.isin == "DE000A1EWWW0"
    assert c.price == pytest.approx(154.5)
    assert c.currency == "EUR"


def test_constituent_isin_accepts_none() -> None:
    c = Constituent(ticker="XYZ.DE", name="Mystery Corp", country="DE")
    assert c.isin is None
    assert c.isin_source is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (-5.0, 0.0),
        (0.0, 0.0),
        (50.0, 50.0),
        (100.0, 100.0),
        (150.0, 100.0),
        (None, None),
    ],
)
def test_constituent_ttm_yield_clamped(
    raw: float | None, expected: float | None
) -> None:
    c = Constituent(
        ticker="X.DE",
        name="X",
        country="DE",
        ttm_div_yield=raw,
    )
    assert c.ttm_div_yield == expected


def test_constituent_strips_whitespace() -> None:
    c = Constituent(
        ticker="  ADS.DE  ",
        name="  adidas AG  ",
        country=" DE ",
    )
    assert c.ticker == "ADS.DE"
    assert c.name == "adidas AG"
    assert c.country == "DE"


def test_index_and_query_result() -> None:
    c = Constituent(ticker="ADS.DE", name="adidas AG", country="DE")
    idx = Index(
        name="DAX",
        country="DE",
        constituents=[c],
        fetched_at=datetime(2025, 1, 1, tzinfo=UTC),
        source="yfinance (unofficial)",
    )
    qr = QueryResult(
        indices=[idx],
        total_constituents=1,
        fetch_duration_seconds=0.42,
    )
    assert qr.total_constituents == 1
    assert qr.indices[0].constituents[0].ticker == "ADS.DE"
