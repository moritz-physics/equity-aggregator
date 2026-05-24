"""Base adapter interface for equity index data sources."""

from __future__ import annotations

from abc import ABC, abstractmethod

from equity_aggregator.core.models import Index


class IndexAdapter(ABC):
    """Abstract base for per-index data adapters.

    Each concrete adapter knows how to assemble an `Index` for one named
    equity index from one or more upstream sources.
    """

    @abstractmethod
    async def fetch_constituents(self) -> Index:
        """Fetch and return an `Index` populated with all constituents."""
