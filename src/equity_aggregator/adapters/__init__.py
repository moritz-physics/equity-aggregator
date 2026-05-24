"""Data source adapters for equity index constituents.

``ADAPTER_REGISTRY`` is the service-layer lookup of index name → adapter
class. Adding a new index means registering its adapter here.
"""

from __future__ import annotations

from equity_aggregator.adapters.aex import AEXAdapter
from equity_aggregator.adapters.base import IndexAdapter
from equity_aggregator.adapters.bel20 import BEL20Adapter
from equity_aggregator.adapters.cac40 import CAC40Adapter
from equity_aggregator.adapters.dax import DAXAdapter
from equity_aggregator.adapters.ftse100 import FTSE100Adapter
from equity_aggregator.adapters.ibex35 import IBEX35Adapter
from equity_aggregator.adapters.smi import SMIAdapter
from equity_aggregator.adapters.sp500 import SP500Adapter
from equity_aggregator.adapters.sti import STIAdapter
from equity_aggregator.adapters.wig20 import WIG20Adapter

ADAPTER_REGISTRY: dict[str, type[IndexAdapter]] = {
    "DAX": DAXAdapter,
    "CAC 40": CAC40Adapter,
    "SMI": SMIAdapter,
    "BEL 20": BEL20Adapter,
    "AEX": AEXAdapter,
    "STI": STIAdapter,
    "WIG20": WIG20Adapter,
    "IBEX 35": IBEX35Adapter,
    "S&P 500": SP500Adapter,
    "FTSE 100": FTSE100Adapter,
}

__all__ = [
    "ADAPTER_REGISTRY",
    "AEXAdapter",
    "BEL20Adapter",
    "CAC40Adapter",
    "DAXAdapter",
    "FTSE100Adapter",
    "IBEX35Adapter",
    "IndexAdapter",
    "SMIAdapter",
    "SP500Adapter",
    "STIAdapter",
    "WIG20Adapter",
]
