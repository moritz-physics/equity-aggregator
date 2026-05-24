"""Unit tests for the export layer (CSV / JSON / XLSX)."""

from __future__ import annotations

import json
from io import BytesIO

from openpyxl import load_workbook

from equity_aggregator.core.export import COLUMNS, to_csv, to_json, to_xlsx
from equity_aggregator.core.models import QueryResult


def _decoded_csv(result: QueryResult) -> list[list[str]]:
    text = to_csv(result).decode("utf-8-sig")
    import csv

    return list(csv.reader(text.splitlines()))


def test_to_csv_has_bom_and_header(sample_query_result: QueryResult) -> None:
    raw = to_csv(sample_query_result)
    assert raw.startswith(b"\xef\xbb\xbf"), "CSV must start with UTF-8 BOM"

    rows = _decoded_csv(sample_query_result)
    assert rows[0] == list(COLUMNS)


def test_to_csv_row_count_matches_constituents(
    sample_query_result: QueryResult,
) -> None:
    rows = _decoded_csv(sample_query_result)
    expected = sum(len(i.constituents) for i in sample_query_result.indices)
    assert len(rows) - 1 == expected  # minus header


def test_to_csv_formats_numbers_and_dates(sample_query_result: QueryResult) -> None:
    rows = _decoded_csv(sample_query_result)
    # ADS row is first.
    ads = rows[1]
    headers = list(COLUMNS)
    price = ads[headers.index("Price")]
    yield_ = ads[headers.index("TTM Div Yield %")]
    market_cap = ads[headers.index("Market Cap")]
    ex_div = ads[headers.index("Ex-Div Date")]

    assert price == "154.50"
    assert yield_ == "1.81"
    assert market_cap == "27,400,000,000"
    assert ex_div == "2026-05-08"


def test_to_csv_empty_cells_for_none(sample_query_result: QueryResult) -> None:
    rows = _decoded_csv(sample_query_result)
    headers = list(COLUMNS)
    # XYZ row has no financials.
    xyz = next(r for r in rows[1:] if r[0] == "XYZ.DE")
    assert xyz[headers.index("Price")] == ""
    assert xyz[headers.index("ISIN")] == ""
    assert xyz[headers.index("Sector")] == ""


def test_to_json_is_valid_with_indices_key(
    sample_query_result: QueryResult,
) -> None:
    payload = to_json(sample_query_result)
    parsed = json.loads(payload)
    assert isinstance(parsed, dict)
    assert "indices" in parsed
    assert parsed["total_constituents"] == 3
    assert parsed["indices"][0]["name"] == "DAX"
    assert parsed["indices"][0]["constituents"][0]["ticker"] == "ADS.DE"
    # Dates serialise as ISO strings, not epoch.
    assert parsed["indices"][0]["constituents"][0]["ex_div_date"] == "2026-05-08"


def test_to_json_is_indented(sample_query_result: QueryResult) -> None:
    payload = to_json(sample_query_result)
    # Pretty-printed JSON has newlines and leading spaces.
    assert "\n" in payload
    assert "  " in payload


def test_to_xlsx_bytes_non_empty(sample_query_result: QueryResult) -> None:
    raw = to_xlsx(sample_query_result)
    assert isinstance(raw, bytes)
    assert len(raw) > 1000


def test_to_xlsx_sheet_name_and_header_and_row_count(
    sample_query_result: QueryResult,
) -> None:
    raw = to_xlsx(sample_query_result)
    wb = load_workbook(BytesIO(raw))
    assert wb.sheetnames == ["DAX"]

    ws = wb["DAX"]
    header_row = [c.value for c in ws[1]]
    assert header_row == list(COLUMNS)

    # 3 constituents → rows 2..4 populated; ws.max_row should be 4.
    assert ws.max_row == 1 + 3
    assert ws.cell(row=2, column=1).value == "ADS.DE"
    assert ws.cell(row=3, column=1).value == "SAP.DE"
    assert ws.cell(row=4, column=1).value == "XYZ.DE"


def test_to_xlsx_has_freeze_panes(sample_query_result: QueryResult) -> None:
    raw = to_xlsx(sample_query_result)
    wb = load_workbook(BytesIO(raw))
    ws = wb["DAX"]
    assert ws.freeze_panes == "A2"
