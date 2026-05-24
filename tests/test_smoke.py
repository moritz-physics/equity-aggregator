"""Phase 0 smoke tests: package importable, modules load, data files present."""

from __future__ import annotations

import importlib
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_package_version() -> None:
    import equity_aggregator

    assert equity_aggregator.__version__ == "0.1.0"


def test_all_modules_importable() -> None:
    modules = [
        "equity_aggregator",
        "equity_aggregator.adapters",
        "equity_aggregator.adapters.base",
        "equity_aggregator.adapters.dax",
        "equity_aggregator.core",
        "equity_aggregator.core.models",
        "equity_aggregator.core.service",
        "equity_aggregator.core.cache",
        "equity_aggregator.core.export",
        "equity_aggregator.api",
        "equity_aggregator.api.main",
        "equity_aggregator.ui",
        "equity_aggregator.ui.app",
        "equity_aggregator.ui.utils",
    ]
    for name in modules:
        importlib.import_module(name)


def test_sources_yaml_valid() -> None:
    sources_path = PROJECT_ROOT / "data" / "sources.yaml"
    assert sources_path.exists(), f"missing {sources_path}"
    parsed = yaml.safe_load(sources_path.read_text())
    assert isinstance(parsed, dict)
    assert "sources" in parsed
