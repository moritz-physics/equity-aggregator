"""Unit tests for AggregationService (no network)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from equity_aggregator.adapters.base import IndexAdapter
from equity_aggregator.core import service as service_module
from equity_aggregator.core.cache import ConstituentCache
from equity_aggregator.core.models import Constituent, Index, QueryResult
from equity_aggregator.core.service import AggregationService, UnknownIndexError


def _make_index(name: str = "DAX", tag: str = "v1") -> Index:
    return Index(
        name=name,
        country="DE",
        constituents=[
            Constituent(ticker=f"{name}.X", name=f"{name} {tag}", country="DE")
        ],
        fetched_at=datetime(2026, 5, 24, tzinfo=UTC),
        source="test",
    )


class _StubAdapter(IndexAdapter):
    """Adapter that returns a pre-canned Index and counts invocations."""

    def __init__(self, index: Index) -> None:
        self._index = index
        self.calls = 0

    async def fetch_constituents(self) -> Index:
        self.calls += 1
        await asyncio.sleep(0)  # yield to the loop so gather() is real fan-out
        return self._index


def _factory_for(stub: _StubAdapter) -> type[IndexAdapter]:
    """Wrap a stub instance in a no-arg-constructible adapter class.

    The service does ``ADAPTER_REGISTRY[name]()`` — so we need a class, not
    an instance. The wrapper just delegates to the captured stub.
    """

    class _Factory(IndexAdapter):
        async def fetch_constituents(self) -> Index:
            return await stub.fetch_constituents()

    return _Factory


def _install_adapters(
    monkeypatch: pytest.MonkeyPatch, adapters: dict[str, _StubAdapter]
) -> None:
    fake = {name: _factory_for(stub) for name, stub in adapters.items()}
    monkeypatch.setattr(service_module, "ADAPTER_REGISTRY", fake)


@pytest.mark.asyncio
async def test_cache_hit_skips_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    cached = _make_index("DAX", "cached")
    stub = _StubAdapter(_make_index("DAX", "fresh"))
    _install_adapters(monkeypatch, {"DAX": stub})

    cache = MagicMock(spec=ConstituentCache)
    cache.get.return_value = cached

    result = await AggregationService(cache=cache).fetch(["DAX"])

    assert stub.calls == 0, "adapter must not be called on cache hit"
    cache.set.assert_not_called()
    assert result.total_constituents == 1
    assert result.indices[0].constituents[0].name == "DAX cached"


@pytest.mark.asyncio
async def test_cache_miss_calls_adapter_and_writes_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubAdapter(_make_index("DAX", "fresh"))
    _install_adapters(monkeypatch, {"DAX": stub})

    cache = MagicMock(spec=ConstituentCache)
    cache.get.return_value = None

    result = await AggregationService(cache=cache).fetch(["DAX"])

    assert stub.calls == 1
    cache.set.assert_called_once()
    written = cache.set.call_args.args[0]
    assert written.name == "DAX"
    assert result.indices[0].constituents[0].name == "DAX fresh"


@pytest.mark.asyncio
async def test_force_refresh_bypasses_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubAdapter(_make_index("DAX", "fresh"))
    _install_adapters(monkeypatch, {"DAX": stub})

    cache = MagicMock(spec=ConstituentCache)
    cache.get.return_value = _make_index("DAX", "cached")

    result = await AggregationService(cache=cache).fetch(
        ["DAX"], force_refresh=True
    )

    cache.get.assert_not_called()
    assert stub.calls == 1
    cache.set.assert_called_once()
    assert result.indices[0].constituents[0].name == "DAX fresh"


@pytest.mark.asyncio
async def test_multiple_indices_fan_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dax = _StubAdapter(_make_index("DAX", "fresh"))
    cac = _StubAdapter(_make_index("CAC", "fresh"))
    _install_adapters(monkeypatch, {"DAX": dax, "CAC": cac})

    cache = MagicMock(spec=ConstituentCache)
    cache.get.return_value = None

    result = await AggregationService(cache=cache).fetch(["DAX", "CAC"])

    assert dax.calls == 1
    assert cac.calls == 1
    assert cache.set.call_count == 2
    assert [i.name for i in result.indices] == ["DAX", "CAC"]
    assert result.total_constituents == 2
    assert result.fetch_duration_seconds >= 0


@pytest.mark.asyncio
async def test_unknown_index_raises() -> None:
    cache = MagicMock(spec=ConstituentCache)
    cache.get.return_value = None
    with pytest.raises(UnknownIndexError):
        await AggregationService(cache=cache).fetch(["NIKKEI"])


@pytest.mark.asyncio
async def test_returns_query_result_with_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubAdapter(_make_index("DAX", "fresh"))
    _install_adapters(monkeypatch, {"DAX": stub})

    cache = MagicMock(spec=ConstituentCache)
    cache.get.return_value = None

    result = await AggregationService(cache=cache).fetch(["DAX"])
    assert isinstance(result, QueryResult)
    assert result.fetch_duration_seconds >= 0
