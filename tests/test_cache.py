"""Unit tests for ConstituentCache."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from equity_aggregator.core.cache import CachedIndex, ConstituentCache, _aware
from equity_aggregator.core.models import Constituent, Index


def _make_index(name: str = "DAX") -> Index:
    return Index(
        name=name,
        country="DE",
        constituents=[
            Constituent(
                ticker="ADS.DE",
                name="adidas AG",
                isin="DE000A1EWWW0",
                isin_source="static",
                country="DE",
                price=154.5,
                currency="EUR",
                sector="Consumer Cyclical",
            )
        ],
        fetched_at=datetime(2026, 5, 24, tzinfo=UTC),
        source="test",
    )


def _cache(tmp_path: Path, ttl: int = 3600) -> ConstituentCache:
    return ConstituentCache(
        db_path=tmp_path / "cache.db", default_ttl_seconds=ttl
    )


def test_set_then_get_round_trips(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    original = _make_index()
    cache.set(original)
    readback = cache.get("DAX")
    assert readback is not None
    assert readback.name == original.name
    assert readback.country == original.country
    assert len(readback.constituents) == 1
    assert readback.constituents[0].ticker == "ADS.DE"
    assert readback.constituents[0].isin == "DE000A1EWWW0"


def test_get_returns_none_when_missing(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    assert cache.get("DAX") is None


def test_expired_entry_returns_none(tmp_path: Path) -> None:
    cache = _cache(tmp_path, ttl=60)
    cache.set(_make_index())

    # Backdate the row so it's > TTL old.
    from sqlmodel import Session, select

    with Session(cache._engine) as session:
        row = session.exec(select(CachedIndex)).first()
        assert row is not None
        row.fetched_at = datetime.now(tz=UTC) - timedelta(seconds=120)
        session.add(row)
        session.commit()

    assert cache.get("DAX") is None


def test_set_replaces_previous_entry(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    cache.set(_make_index())
    cache.set(_make_index())  # second write

    from sqlmodel import Session, select

    with Session(cache._engine) as session:
        rows = list(session.exec(select(CachedIndex)).all())
    assert len(rows) == 1, "set() must upsert, not append"


def test_invalidate_removes_entry(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    cache.set(_make_index())
    cache.invalidate("DAX")
    assert cache.get("DAX") is None


def test_invalidate_all_clears_everything(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    cache.set(_make_index("DAX"))
    cache.set(_make_index("CAC"))
    cache.invalidate_all()
    assert cache.get("DAX") is None
    assert cache.get("CAC") is None


def test_stats_structure(tmp_path: Path) -> None:
    cache = _cache(tmp_path, ttl=3600)
    cache.set(_make_index())
    stats = cache.stats()

    assert "DAX" in stats
    entry = stats["DAX"]
    assert set(entry) == {"fetched_at", "expires_at", "ttl_seconds", "hit"}
    assert entry["ttl_seconds"] == 3600
    assert entry["hit"] is True
    fetched_at = entry["fetched_at"]
    expires_at = entry["expires_at"]
    assert isinstance(fetched_at, datetime)
    assert isinstance(expires_at, datetime)
    assert expires_at == _aware(fetched_at) + timedelta(seconds=3600)


def test_stats_marks_expired_as_hit_false(tmp_path: Path) -> None:
    cache = _cache(tmp_path, ttl=60)
    cache.set(_make_index())
    from sqlmodel import Session, select

    with Session(cache._engine) as session:
        row = session.exec(select(CachedIndex)).first()
        assert row is not None
        row.fetched_at = datetime.now(tz=UTC) - timedelta(seconds=120)
        session.add(row)
        session.commit()

    stats = cache.stats()
    assert stats["DAX"]["hit"] is False


@pytest.mark.parametrize("name", ["DAX", "CAC40", "FTSE100"])
def test_isolation_between_indices(tmp_path: Path, name: str) -> None:
    cache = _cache(tmp_path)
    cache.set(_make_index(name))
    assert cache.get(name) is not None
    for other in ("DAX", "CAC40", "FTSE100"):
        if other != name:
            assert cache.get(other) is None
