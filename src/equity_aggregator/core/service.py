"""Service layer: cache-aware async fan-out across registered adapters.

``AggregationService.fetch(["DAX", ...])`` checks the cache for each
requested index, fans out concurrent fetches for the misses, writes
fresh results back to the cache, and returns a single ``QueryResult``.
"""

from __future__ import annotations

import asyncio
import logging
import time

from equity_aggregator.adapters import ADAPTER_REGISTRY
from equity_aggregator.adapters.base import IndexAdapter
from equity_aggregator.core.cache import ConstituentCache
from equity_aggregator.core.models import Index, QueryResult

logger = logging.getLogger(__name__)


class UnknownIndexError(KeyError):
    """Raised when no adapter is registered for the requested index name."""


class AggregationService:
    """Cache-aware async aggregator over the registered adapter set."""

    def __init__(self, cache: ConstituentCache | None = None) -> None:
        self._cache = cache if cache is not None else ConstituentCache()

    def _adapter_for(self, index_name: str) -> IndexAdapter:
        try:
            cls = ADAPTER_REGISTRY[index_name]
        except KeyError as exc:
            raise UnknownIndexError(
                f"No adapter registered for index {index_name!r}. "
                f"Known: {sorted(ADAPTER_REGISTRY)}"
            ) from exc
        return cls()

    async def _fetch_one(self, index_name: str) -> Index:
        adapter = self._adapter_for(index_name)
        index = await adapter.fetch_constituents()
        self._cache.set(index)
        logger.info(
            "Fetched %s: %d constituents (cached)",
            index_name,
            len(index.constituents),
        )
        return index

    async def fetch(
        self,
        index_names: list[str],
        force_refresh: bool = False,
    ) -> QueryResult:
        start = time.perf_counter()

        cached: dict[str, Index] = {}
        misses: list[str] = []
        for name in index_names:
            if not force_refresh:
                hit = self._cache.get(name)
                if hit is not None:
                    cached[name] = hit
                    logger.info("Cache hit for %s", name)
                    continue
            logger.info(
                "Cache %s for %s — fetching",
                "bypass (force_refresh)" if force_refresh else "miss",
                name,
            )
            misses.append(name)

        fetched: list[Index] = []
        if misses:
            fetched = list(
                await asyncio.gather(*(self._fetch_one(n) for n in misses))
            )

        by_name: dict[str, Index] = {idx.name: idx for idx in fetched}
        by_name.update(cached)
        indices: list[Index] = [by_name[n] for n in index_names if n in by_name]

        duration = time.perf_counter() - start
        return QueryResult(
            indices=indices,
            total_constituents=sum(len(i.constituents) for i in indices),
            fetch_duration_seconds=duration,
        )
