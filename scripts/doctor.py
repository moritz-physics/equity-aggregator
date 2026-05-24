"""Diagnostics: verify the local dev environment is wired correctly."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from rich.console import Console

console = Console()
PROJECT_ROOT = Path(__file__).resolve().parent.parent

REQUIRED_PACKAGES = [
    "yfinance",
    "httpx",
    "fastapi",
    "streamlit",
    "sqlmodel",
    "openpyxl",
    "pydantic",
    "yaml",
    "rich",
]

STUB_MODULES = [
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


def _ok(label: str) -> bool:
    console.print(f"[green]✓[/green] {label}")
    return True


def _fail(label: str, detail: str = "") -> bool:
    suffix = f" [dim]({detail})[/dim]" if detail else ""
    console.print(f"[red]✗[/red] {label}{suffix}")
    return False


def check_python_version() -> bool:
    v = sys.version_info
    label = f"Python {v.major}.{v.minor}.{v.micro} (>= 3.12 required)"
    return _ok(label) if (v.major, v.minor) >= (3, 12) else _fail(label)


def check_required_packages() -> bool:
    all_ok = True
    for pkg in REQUIRED_PACKAGES:
        try:
            importlib.import_module(pkg)
            _ok(f"import {pkg}")
        except Exception as exc:
            all_ok = False
            _fail(f"import {pkg}", str(exc))
    return all_ok


def check_package_version() -> bool:
    try:
        import equity_aggregator

        version = equity_aggregator.__version__
        return _ok(f"equity_aggregator importable (version {version})")
    except Exception as exc:
        return _fail("equity_aggregator importable", str(exc))


def check_stub_modules() -> bool:
    all_ok = True
    for name in STUB_MODULES:
        try:
            importlib.import_module(name)
            _ok(f"import {name}")
        except Exception as exc:
            all_ok = False
            _fail(f"import {name}", str(exc))
    return all_ok


def check_sources_yaml() -> bool:
    import yaml

    path = PROJECT_ROOT / "data" / "sources.yaml"
    if not path.exists():
        return _fail("data/sources.yaml present", "file missing")
    try:
        parsed = yaml.safe_load(path.read_text())
    except Exception as exc:
        return _fail("data/sources.yaml parseable", str(exc))
    if not isinstance(parsed, dict) or "sources" not in parsed:
        return _fail("data/sources.yaml has 'sources' key")
    return _ok("data/sources.yaml present and parseable")


def check_data_writable() -> bool:
    data_dir = PROJECT_ROOT / "data"
    probe = data_dir / ".write_probe"
    try:
        probe.write_text("ok")
        probe.unlink()
        return _ok("data/ directory writable")
    except Exception as exc:
        return _fail("data/ directory writable", str(exc))


def check_yfinance_reachable() -> bool:
    try:
        import yfinance as yf

        info = yf.Ticker("ADS.DE").info
        if isinstance(info, dict) and info:
            return _ok(f"yfinance reachable (ADS.DE returned {len(info)} fields)")
        return _fail("yfinance reachable", "empty info dict")
    except Exception as exc:
        return _fail("yfinance reachable", str(exc))


def check_dax_adapter_instantiable() -> bool:
    try:
        from equity_aggregator.adapters.dax import DAX_MEMBERS, DAXAdapter

        adapter = DAXAdapter()
        if not hasattr(adapter, "fetch_constituents"):
            return _fail("DAX adapter instantiable", "missing fetch_constituents")
        return _ok(
            f"DAX adapter instantiable ({len(DAX_MEMBERS)} curated members)"
        )
    except Exception as exc:
        return _fail("DAX adapter instantiable", str(exc))


def check_adapter_registry() -> bool:
    try:
        from equity_aggregator.adapters import ADAPTER_REGISTRY
        from equity_aggregator.adapters.base import IndexAdapter

        expected = {
            "DAX",
            "CAC 40",
            "SMI",
            "BEL 20",
            "AEX",
            "STI",
            "WIG20",
            "IBEX 35",
            "S&P 500",
        }
        missing = expected - set(ADAPTER_REGISTRY)
        if missing:
            return _fail(
                "ADAPTER_REGISTRY contains all 9 indices",
                f"missing: {sorted(missing)}",
            )
        for name, cls in ADAPTER_REGISTRY.items():
            instance = cls()
            if not isinstance(instance, IndexAdapter):
                return _fail(
                    "ADAPTER_REGISTRY entries instantiable",
                    f"{name} → {cls.__name__} is not an IndexAdapter",
                )
        return _ok(
            f"ADAPTER_REGISTRY has {len(ADAPTER_REGISTRY)} adapters "
            f"({', '.join(sorted(ADAPTER_REGISTRY))})"
        )
    except Exception as exc:
        return _fail("ADAPTER_REGISTRY check", str(exc))


def check_cache_instantiable() -> bool:
    try:
        from equity_aggregator.core.cache import DB_PATH, ConstituentCache

        ConstituentCache()
        if not DB_PATH.exists():
            return _fail("ConstituentCache instantiable", f"{DB_PATH} not created")
        return _ok(f"ConstituentCache instantiable ({DB_PATH.name} created)")
    except Exception as exc:
        return _fail("ConstituentCache instantiable", str(exc))


def check_service_instantiable() -> bool:
    try:
        from equity_aggregator.core.service import AggregationService

        AggregationService()
        return _ok("AggregationService instantiable")
    except Exception as exc:
        return _fail("AggregationService instantiable", str(exc))


def check_export_importable() -> bool:
    try:
        from equity_aggregator.core.export import to_csv, to_json, to_xlsx

        for fn in (to_csv, to_json, to_xlsx):
            if not callable(fn):
                return _fail("export functions importable", f"{fn} not callable")
        return _ok("export functions importable (to_csv, to_json, to_xlsx)")
    except Exception as exc:
        return _fail("export functions importable", str(exc))


def check_cache_round_trip() -> bool:
    try:
        from datetime import UTC, datetime

        from equity_aggregator.core.cache import ConstituentCache
        from equity_aggregator.core.models import Constituent, Index

        cache = ConstituentCache()
        sentinel_name = "__doctor_probe__"
        cache.invalidate(sentinel_name)

        probe = Index(
            name=sentinel_name,
            country="DE",
            constituents=[
                Constituent(ticker="PRB.DE", name="Probe AG", country="DE")
            ],
            fetched_at=datetime.now(tz=UTC),
            source="doctor",
        )
        cache.set(probe)
        readback = cache.get(sentinel_name)
        cache.invalidate(sentinel_name)

        if readback is None:
            return _fail("cache write/read round-trip", "got None back")
        if readback.name != sentinel_name:
            return _fail("cache write/read round-trip", f"name={readback.name!r}")
        if len(readback.constituents) != 1:
            return _fail(
                "cache write/read round-trip",
                f"{len(readback.constituents)} constituents",
            )
        return _ok("cache write/read round-trip")
    except Exception as exc:
        return _fail("cache write/read round-trip", str(exc))


def check_ui_utils_importable() -> bool:
    try:
        from equity_aggregator.ui import utils as ui_utils

        for name in (
            "format_market_cap",
            "format_yield",
            "filter_constituents",
            "constituents_to_dataframe",
        ):
            if not callable(getattr(ui_utils, name, None)):
                return _fail("ui.utils importable", f"{name} not callable")
        return _ok("ui.utils importable (4 helpers)")
    except Exception as exc:
        return _fail("ui.utils importable", str(exc))


def check_ui_app_importable() -> bool:
    """Import-only smoke. ``app.main()`` is gated on __name__ == "__main__"."""
    try:
        import importlib

        importlib.import_module("equity_aggregator.ui.app")
        return _ok("ui.app importable (no Streamlit run)")
    except Exception as exc:
        return _fail("ui.app importable", str(exc))


def check_ui_utils_handle_none() -> bool:
    try:
        from equity_aggregator.ui.utils import (
            constituents_to_dataframe,
            filter_constituents,
            format_market_cap,
            format_yield,
        )

        assert format_market_cap(None) == "—"
        assert format_yield(None) == "—"
        df = constituents_to_dataframe([])
        if len(df) != 0:
            return _fail("ui.utils handle None/empty inputs", "non-empty df")
        out = filter_constituents([])
        if out != []:
            return _fail("ui.utils handle None/empty inputs", "non-empty filter")
        return _ok("ui.utils handle None/empty inputs")
    except Exception as exc:
        return _fail("ui.utils handle None/empty inputs", str(exc))


def check_openfigi_reachable() -> bool:
    try:
        import httpx

        r = httpx.post(
            "https://api.openfigi.com/v3/mapping",
            json=[{"idType": "TICKER", "idValue": "ADS", "exchCode": "GS"}],
            timeout=15.0,
        )
        if r.status_code >= 500:
            return _fail("OpenFIGI reachable", f"HTTP {r.status_code}")
        return _ok(f"OpenFIGI reachable (HTTP {r.status_code})")
    except Exception as exc:
        return _fail("OpenFIGI reachable", str(exc))


def main() -> int:
    checks = [
        check_python_version,
        check_required_packages,
        check_package_version,
        check_stub_modules,
        check_sources_yaml,
        check_data_writable,
        check_yfinance_reachable,
        check_dax_adapter_instantiable,
        check_adapter_registry,
        check_cache_instantiable,
        check_service_instantiable,
        check_export_importable,
        check_cache_round_trip,
        check_openfigi_reachable,
        check_ui_utils_importable,
        check_ui_app_importable,
        check_ui_utils_handle_none,
    ]
    results = [c() for c in checks]
    passed = sum(1 for r in results if r)
    total = len(results)
    color = "green" if passed == total else "red"
    console.print(f"[{color}]{passed}/{total} checks passed.[/{color}]")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
