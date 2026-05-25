"""Domain models for equities and index constituents."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Constituent(BaseModel):
    """A single security inside an index.

    Fields are largely optional because upstream sources (yfinance, OpenFIGI)
    have inconsistent coverage. The adapter layer fills what it can and
    leaves the rest None.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    ticker: str
    name: str
    isin: str | None = None
    # Source of the ISIN value. Empirically:
    #   "yfinance" — info.get("isin") returned a real ISIN (rare; yfinance
    #                returns the sentinel "-" for most German tickers).
    #   "openfigi" — recovered from OpenFIGI response (also rare; the
    #                /v3/mapping endpoint does not normally surface ISIN).
    #   "static"   — taken from a curated, hardcoded constituent map. This is
    #                the practical fallback for indices where neither upstream
    #                API exposes ISIN reliably.
    isin_source: str | None = None
    country: str
    price: float | None = None
    currency: str | None = None
    ex_div_date: date | None = None
    ttm_div_yield: float | None = Field(
        default=None,
        description="Trailing 12m dividend yield as percent (e.g. 2.5 for 2.5%).",
    )
    beta: float | None = None
    market_cap: float | None = None
    sector: str | None = None
    # Index weight as a percent (e.g. 9.23 for 9.23%). Sourced from the
    # authoritative provider (ETF holdings file or index methodology page) at
    # the time the static map was last regenerated. None for indices where we
    # do not yet curate weights — the UI then falls back to market-cap sort.
    weight: float | None = None

    @field_validator("ttm_div_yield")
    @classmethod
    def _clamp_yield(cls, value: float | None) -> float | None:
        if value is None:
            return None
        return max(0.0, min(100.0, value))


class Index(BaseModel):
    """A named equity index with a snapshot of its constituents."""

    name: str
    country: str
    constituents: list[Constituent]
    fetched_at: datetime
    source: str


class QueryResult(BaseModel):
    """Aggregate result returned by the service layer for one or more indices."""

    indices: list[Index]
    total_constituents: int
    fetch_duration_seconds: float
