"""Live integration test runner against real upstream sources.

Phase 1: exercise the DAX adapter end-to-end, assert hard quality bars, and
print a rich table of all 40 constituents for visual inspection.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time

from openpyxl import load_workbook
from rich.console import Console
from rich.table import Table

from equity_aggregator.adapters.dax import DAXAdapter
from equity_aggregator.core.cache import ConstituentCache
from equity_aggregator.core.export import to_csv, to_json, to_xlsx
from equity_aggregator.core.models import Index, QueryResult
from equity_aggregator.core.service import AggregationService

ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{10}$")

console = Console()


def _check(label: str, ok: bool, detail: str = "") -> bool:
    marker = "[green]✓[/green]" if ok else "[red]✗[/red]"
    suffix = f" [dim]({detail})[/dim]" if detail else ""
    console.print(f"  {marker} {label}{suffix}")
    return ok


def _assertions(index: Index) -> list[bool]:
    cs = index.constituents
    results: list[bool] = []

    results.append(
        _check("exactly 40 constituents", len(cs) == 40, f"got {len(cs)}")
    )

    bad_required: list[str] = []
    for c in cs:
        if not (isinstance(c.ticker, str) and c.ticker):
            bad_required.append(f"{c.ticker}: empty ticker")
        if not (isinstance(c.name, str) and c.name):
            bad_required.append(f"{c.ticker}: empty name")
        if c.country != "DE":
            bad_required.append(f"{c.ticker}: country={c.country!r}")
        if c.currency != "EUR":
            bad_required.append(f"{c.ticker}: currency={c.currency!r}")
    results.append(
        _check(
            "every row: ticker, name, country=DE, currency=EUR",
            not bad_required,
            "; ".join(bad_required[:3]) if bad_required else "",
        )
    )

    with_price = [c for c in cs if c.price is not None and c.price > 0]
    results.append(
        _check(
            "≥ 35/40 with non-None price > 0",
            len(with_price) >= 35,
            f"{len(with_price)}/40",
        )
    )

    with_isin = [
        c for c in cs if c.isin is not None and ISIN_RE.match(c.isin) is not None
    ]
    results.append(
        _check(
            "≥ 30/40 with valid ISIN",
            len(with_isin) >= 30,
            f"{len(with_isin)}/40",
        )
    )

    with_sector = [c for c in cs if c.sector is not None and c.sector.strip()]
    results.append(
        _check(
            "≥ 30/40 with non-None sector",
            len(with_sector) >= 30,
            f"{len(with_sector)}/40",
        )
    )

    return results


def _render_table(index: Index) -> Table:
    table = Table(
        title=(
            f"{index.name} — {len(index.constituents)} constituents "
            f"(source: {index.source}, fetched "
            f"{index.fetched_at:%Y-%m-%d %H:%M:%S UTC})"
        ),
        show_lines=False,
    )
    table.add_column("Ticker", style="bold cyan", no_wrap=True)
    table.add_column("Name", overflow="fold", max_width=34)
    table.add_column("ISIN", style="dim")
    table.add_column("Src", style="dim")
    table.add_column("Price", justify="right")
    table.add_column("Sector", overflow="fold", max_width=18)
    table.add_column("TTM Yield %", justify="right")
    table.add_column("Beta", justify="right")

    def _fmt(v: float | None, digits: int = 2) -> str:
        return f"{v:,.{digits}f}" if v is not None else "—"

    for c in sorted(index.constituents, key=lambda x: x.ticker):
        table.add_row(
            c.ticker,
            c.name,
            c.isin or "—",
            c.isin_source or "—",
            _fmt(c.price),
            c.sector or "—",
            _fmt(c.ttm_div_yield),
            _fmt(c.beta, 3),
        )
    return table


def _service_assertions(
    first: QueryResult,
    first_elapsed: float,
    second: QueryResult,
    second_elapsed: float,
    refreshed: QueryResult,
) -> list[bool]:
    """Cache + force-refresh behaviour."""
    results: list[bool] = []

    results.append(
        _check(
            "service returns QueryResult with 40 DAX constituents",
            len(first.indices) == 1 and first.total_constituents == 40,
            f"indices={len(first.indices)}, total={first.total_constituents}",
        )
    )
    results.append(
        _check(
            "second call is faster than first (cache hit)",
            second_elapsed < first_elapsed,
            f"first={first_elapsed:.2f}s second={second_elapsed:.4f}s",
        )
    )
    # Same index_name → same fetched_at when served from cache.
    same_snapshot = (
        first.indices
        and second.indices
        and first.indices[0].fetched_at == second.indices[0].fetched_at
    )
    results.append(
        _check(
            "cached snapshot is byte-identical (same fetched_at)",
            bool(same_snapshot),
        )
    )
    # force_refresh must produce a *new* snapshot.
    new_snapshot = (
        first.indices
        and refreshed.indices
        and refreshed.indices[0].fetched_at != first.indices[0].fetched_at
    )
    results.append(
        _check(
            "force_refresh=True bypasses cache (new fetched_at)",
            bool(new_snapshot),
        )
    )
    return results


def _export_assertions(result: QueryResult) -> list[bool]:
    results: list[bool] = []

    csv_bytes = to_csv(result)
    csv_text = csv_bytes.decode("utf-8-sig")
    header_line = csv_text.splitlines()[0] if csv_text else ""
    results.append(
        _check(
            "to_csv: bytes, UTF-8 decodable, header contains 'Ticker'",
            isinstance(csv_bytes, bytes) and "Ticker" in header_line,
            f"len={len(csv_bytes)}",
        )
    )

    json_str = to_json(result)
    parsed_ok = False
    indices_key = False
    try:
        parsed = json.loads(json_str)
        parsed_ok = True
        indices_key = isinstance(parsed, dict) and "indices" in parsed
    except json.JSONDecodeError:
        pass
    results.append(
        _check(
            "to_json: valid JSON with top-level 'indices' key",
            parsed_ok and indices_key,
            f"len={len(json_str)}",
        )
    )

    xlsx_bytes = to_xlsx(result)
    sheet_ok = False
    try:
        from io import BytesIO

        wb = load_workbook(BytesIO(xlsx_bytes))
        sheet_ok = "DAX" in wb.sheetnames
    except Exception as exc:
        sheet_ok = False
        console.print(f"[red]xlsx load failed: {exc}[/red]")
    results.append(
        _check(
            "to_xlsx: bytes >1000, loads with openpyxl, has 'DAX' sheet",
            isinstance(xlsx_bytes, bytes) and len(xlsx_bytes) > 1000 and sheet_ok,
            f"len={len(xlsx_bytes)}",
        )
    )
    return results


def _render_cache_stats(cache: ConstituentCache) -> Table:
    table = Table(title="Cache stats", show_lines=False)
    table.add_column("Index", style="bold cyan")
    table.add_column("Fetched at")
    table.add_column("Expires at")
    table.add_column("TTL (s)", justify="right")
    table.add_column("Hit?")
    for name, entry in cache.stats().items():
        fetched_at = entry["fetched_at"]
        expires_at = entry["expires_at"]
        ttl = entry["ttl_seconds"]
        hit = entry["hit"]
        hit_str = "[green]yes[/green]" if hit else "[red]expired[/red]"
        table.add_row(
            name,
            f"{fetched_at:%Y-%m-%d %H:%M:%S %Z}",
            f"{expires_at:%Y-%m-%d %H:%M:%S %Z}",
            str(ttl),
            hit_str,
        )
    return table


async def _run() -> int:
    console.rule("[bold]DAX live integration test[/bold]")
    adapter = DAXAdapter()
    console.print("Fetching DAX 40 constituents (yfinance + OpenFIGI) …")
    index = await adapter.fetch_constituents()

    console.print()
    console.print(_render_table(index))
    console.print()

    console.rule("Adapter assertions")
    adapter_results = _assertions(index)

    # --- Service + cache ----------------------------------------------------
    console.rule("Service + cache")
    cache = ConstituentCache()
    cache.invalidate("DAX")  # start clean
    service = AggregationService(cache=cache)

    console.print("First fetch (cache miss → upstream) …")
    t0 = time.perf_counter()
    first = await service.fetch(["DAX"])
    first_elapsed = time.perf_counter() - t0
    console.print(f"  took [bold]{first_elapsed:.2f}s[/bold]")

    console.print("Second fetch (should hit cache) …")
    t0 = time.perf_counter()
    second = await service.fetch(["DAX"])
    second_elapsed = time.perf_counter() - t0
    console.print(f"  took [bold]{second_elapsed:.4f}s[/bold]")

    console.print("Third fetch (force_refresh=True) …")
    refreshed = await service.fetch(["DAX"], force_refresh=True)
    console.print()

    service_results = _service_assertions(
        first, first_elapsed, second, second_elapsed, refreshed
    )

    # --- Export round-trip --------------------------------------------------
    console.rule("Export round-trip")
    export_results = _export_assertions(first)

    # --- Cache stats --------------------------------------------------------
    console.print()
    console.print(_render_cache_stats(cache))
    console.print()

    # --- Spot-check 3 non-DAX adapters --------------------------------------
    console.rule("Spot-check non-DAX adapters")
    spot_check = ["CAC 40", "SMI", "WIG20"]
    spot_results: list[bool] = []
    for name in spot_check:
        try:
            spot_result = await service.fetch([name], force_refresh=True)
            spot_index = spot_result.indices[0]
            isin_count = sum(1 for c in spot_index.constituents if c.isin)
            total_count = len(spot_index.constituents)
            console.print(
                f"[bold]{name}[/bold]: {total_count} constituents, "
                f"{isin_count} ISINs"
            )
            spot_results.append(
                _check(
                    f"{name}: ≥ 1 constituent",
                    total_count > 0,
                    f"got {total_count}",
                )
            )
            spot_results.append(
                _check(
                    f"{name}: ≥ 90% ISIN coverage",
                    isin_count > total_count * 0.9,
                    f"{isin_count}/{total_count}",
                )
            )
            for c in spot_index.constituents[:2]:
                price = f"{c.price:.2f}" if c.price is not None else "—"
                console.print(
                    f"  {c.ticker} | {c.name} | {c.isin} | {price} | "
                    f"{c.sector or '—'}"
                )
        except Exception as exc:  # noqa: BLE001
            spot_results.append(_check(f"{name}: fetched", False, str(exc)))

    all_results = (
        adapter_results + service_results + export_results + spot_results
    )
    passed = sum(1 for r in all_results if r)
    total = len(all_results)
    color = "green" if passed == total else "red"
    console.print(
        f"\n[{color}]{passed}/{total} assertions passed[/{color}] "
        f"(fetched {len(index.constituents)} constituents)."
    )
    return 0 if passed == total else 1


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
