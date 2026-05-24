"""Export ``QueryResult`` snapshots to CSV, JSON, and XLSX.

CSV is UTF-8 with BOM (so Excel opens it cleanly). XLSX is themed to
match the UI (navy header, dark alternating rows). JSON is pretty-printed
via Pydantic's ``model_dump_json`` so dates serialise as ISO strings.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.workbook.workbook import Workbook as WorkbookT

from equity_aggregator.core.models import Constituent, QueryResult

COLUMNS: tuple[str, ...] = (
    "Ticker",
    "Company",
    "ISIN",
    "ISIN Source",
    "Country",
    "Price",
    "Currency",
    "Ex-Div Date",
    "TTM Div Yield %",
    "Beta",
    "Market Cap",
    "Sector",
)

# UI theme — kept in sync with the Streamlit dark theme.
HEADER_FILL = "1B3A6B"  # primary navy
ROW_FILL_EVEN = "0A0F1E"
ROW_FILL_ODD = "0D1526"
HEADER_FONT_COLOR = "FFFFFF"


def _csv_cell(value: Any, *, digits: int = 2) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _csv_row(c: Constituent) -> list[str]:
    return [
        c.ticker,
        c.name,
        c.isin or "",
        c.isin_source or "",
        c.country,
        _csv_cell(c.price),
        c.currency or "",
        c.ex_div_date.isoformat() if c.ex_div_date is not None else "",
        _csv_cell(c.ttm_div_yield),
        _csv_cell(c.beta, digits=3),
        f"{c.market_cap:,.0f}" if c.market_cap is not None else "",
        c.sector or "",
    ]


def to_csv(result: QueryResult) -> bytes:
    """UTF-8 BOM CSV. Excel auto-detects encoding when the BOM is present."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(COLUMNS)
    for index in result.indices:
        for constituent in index.constituents:
            writer.writerow(_csv_row(constituent))
    return b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8")


def to_json(result: QueryResult) -> str:
    """Pretty-printed JSON via Pydantic so dates serialise as ISO strings."""
    return result.model_dump_json(indent=2)


def _xlsx_row(c: Constituent) -> list[Any]:
    """Row values as native types so Excel applies number formatting."""
    return [
        c.ticker,
        c.name,
        c.isin or "",
        c.isin_source or "",
        c.country,
        c.price,
        c.currency or "",
        c.ex_div_date.isoformat() if c.ex_div_date is not None else "",
        c.ttm_div_yield,
        c.beta,
        c.market_cap,
        c.sector or "",
    ]


def _style_sheet(ws: Any, n_rows: int) -> None:
    header_font = Font(bold=True, color=HEADER_FONT_COLOR)
    header_fill = PatternFill("solid", fgColor=HEADER_FILL)
    even_fill = PatternFill("solid", fgColor=ROW_FILL_EVEN)
    odd_fill = PatternFill("solid", fgColor=ROW_FILL_ODD)
    center = Alignment(horizontal="center")

    # Header row.
    for col_index, header in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=1, column=col_index)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center

    # Number formats.
    fmt_by_column = {
        "Price": "#,##0.00",
        "TTM Div Yield %": '0.00"%"',
        "Beta": "0.000",
        "Market Cap": "#,##0",
    }
    for col_index, header in enumerate(COLUMNS, start=1):
        fmt = fmt_by_column.get(header)
        if fmt is None:
            continue
        for row in range(2, n_rows + 2):
            ws.cell(row=row, column=col_index).number_format = fmt

    # Alternating row fills.
    for row in range(2, n_rows + 2):
        fill = even_fill if row % 2 == 0 else odd_fill
        for col_index in range(1, len(COLUMNS) + 1):
            ws.cell(row=row, column=col_index).fill = fill

    # Auto-fit column widths (bounded).
    for col_index, header in enumerate(COLUMNS, start=1):
        max_len = len(header)
        for row in range(2, n_rows + 2):
            value = ws.cell(row=row, column=col_index).value
            if value is None:
                continue
            text = str(value)
            if len(text) > max_len:
                max_len = len(text)
        width = max(10, min(40, max_len + 2))
        ws.column_dimensions[get_column_letter(col_index)].width = width

    ws.freeze_panes = "A2"


def to_xlsx(result: QueryResult) -> bytes:
    """Themed, freeze-pane XLSX. One sheet per index; sheet name = index.name."""
    wb: WorkbookT = Workbook()
    # Workbook() ships with a default sheet — drop it; we add named ones.
    default_sheet = wb.active
    if default_sheet is not None:
        wb.remove(default_sheet)

    # Empty result still needs a sheet so openpyxl can save the file.
    if not result.indices:
        ws = wb.create_sheet(title="Empty")
        ws.append(list(COLUMNS))
        _style_sheet(ws, n_rows=0)
    else:
        for index in result.indices:
            ws = wb.create_sheet(title=index.name[:31])  # Excel cap
            ws.append(list(COLUMNS))
            for c in index.constituents:
                ws.append(_xlsx_row(c))
            _style_sheet(ws, n_rows=len(index.constituents))

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
