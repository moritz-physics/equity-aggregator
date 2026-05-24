"""Shared pytest fixtures."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from equity_aggregator.core.models import Constituent, Index, QueryResult


@pytest.fixture
def sample_query_result() -> QueryResult:
    """Deterministic three-constituent QueryResult for export/service tests."""
    constituents = [
        Constituent(
            ticker="ADS.DE",
            name="adidas AG",
            isin="DE000A1EWWW0",
            isin_source="static",
            country="DE",
            price=154.50,
            currency="EUR",
            ex_div_date=date(2026, 5, 8),
            ttm_div_yield=1.81,
            beta=1.209,
            market_cap=27_400_000_000.0,
            sector="Consumer Cyclical",
        ),
        Constituent(
            ticker="SAP.DE",
            name="SAP SE",
            isin="DE0007164600",
            isin_source="yfinance",
            country="DE",
            price=210.00,
            currency="EUR",
            ex_div_date=date(2026, 5, 16),
            ttm_div_yield=1.05,
            beta=1.000,
            market_cap=250_000_000_000.0,
            sector="Technology",
        ),
        Constituent(
            # All-None financial fields to exercise the empty-cell path.
            ticker="XYZ.DE",
            name="Mystery Corp",
            country="DE",
        ),
    ]
    index = Index(
        name="DAX",
        country="DE",
        constituents=constituents,
        fetched_at=datetime(2026, 5, 24, 12, 0, 0, tzinfo=UTC),
        source="test-fixture",
    )
    return QueryResult(
        indices=[index],
        total_constituents=len(constituents),
        fetch_duration_seconds=0.5,
    )
