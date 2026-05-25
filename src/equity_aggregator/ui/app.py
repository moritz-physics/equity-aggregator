"""Streamlit entry point — EQ·IDX·AGG.

Sibling to bond-aggregator's UI; replicates the dark-navy + accent-blue
design language. Imports the service and export layers directly (no HTTP
round-trip). Streamlit's own ``@st.cache_data`` sits above our SQLite cache
to suppress re-fetches inside a single browser session.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, cast

import pandas as pd  # pyright: ignore[reportMissingTypeStubs]
import streamlit as st

from equity_aggregator.core.cache import ConstituentCache
from equity_aggregator.core.export import to_csv, to_json, to_xlsx
from equity_aggregator.core.models import QueryResult
from equity_aggregator.core.service import AggregationService
from equity_aggregator.ui.utils import (
    apply_advanced_filters,
    constituents_to_dataframe,
    filter_constituents,
)

# ── Bloomberg terminal palette ────────────────────────────────────────────
BG = "#000000"
SURFACE = "#111111"
ORANGE = "#F07800"
ORANGE_DIM = "#A05000"
WHITE = "#FFFFFF"
GRAY = "#888888"
SUCCESS = "#00AA00"
ERROR = "#FF3333"

ACTIVE_INDICES: tuple[tuple[str, str, int], ...] = (
    ("DE", "DAX", 40),
    ("FR", "CAC 40", 40),
    ("CH", "SMI", 20),
    ("BE", "BEL 20", 20),
    ("NL", "AEX", 25),
    ("SG", "STI", 30),
    ("PL", "WIG20", 20),
    ("ES", "IBEX 35", 35),
    ("US", "S&P 500", 503),
    ("GB", "FTSE 100", 99),
)
AVAILABLE_INDICES: tuple[str, ...] = tuple(name for _, name, _ in ACTIVE_INDICES)
DISABLED_INDICES: tuple[str, ...] = (
    "Nikkei 225",
    "ASX 200",
    "TSX 60",
    "FTSE MIB",
)

FILTER_FIELDS: dict[str, dict[str, Any]] = {
    "Company":       {"type": "text",   "operators": ["contains", "not contains"]},
    "Ticker":        {"type": "text",   "operators": ["contains", "not contains"]},
    "Country":       {"type": "select", "operators": ["is", "is not"]},
    "Sector":        {"type": "select", "operators": ["is", "is not"]},
    "Currency":      {"type": "select", "operators": ["is", "is not"]},
    "Market Cap":    {"type": "number", "operators": ["<", ">", "between"]},
    "Price":         {"type": "number", "operators": ["<", ">", "between"]},
    "TTM Div Yield": {"type": "number",
                      "operators": ["<", ">", "=", "no dividend"]},
    "Beta":          {"type": "number", "operators": ["<", ">", "between"]},
}


st.set_page_config(
    page_title="EQ·IDX·AGG",
    page_icon="BB",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def _inject_css() -> None:
    st.markdown(
        f"""
        <style>
            #MainMenu {{visibility: hidden;}}
            footer {{visibility: hidden;}}
            header {{visibility: hidden;}}

            html, body, [class*="css"] {{
                font-family: "Courier New", "Lucida Console", monospace;
                background-color: {BG};
                color: {WHITE};
            }}
            .stApp {{
                background-color: {BG};
                color: {WHITE};
            }}
            /* Sidebar / block containers */
            section[data-testid="stSidebar"],
            div[data-testid="stVerticalBlock"] {{
                background-color: {BG};
            }}
            .eq-header {{
                font-family: "Courier New", monospace;
                font-size: 2.8rem;
                font-weight: 700;
                color: {ORANGE};
                letter-spacing: 0.12em;
                margin: 0;
                padding: 0;
                text-shadow: 0 0 12px rgba(240,120,0,0.4);
            }}
            .eq-subtitle {{
                font-family: "Courier New", monospace;
                font-size: 0.88rem;
                color: {GRAY};
                letter-spacing: 0.25em;
                margin-top: -0.15rem;
                margin-bottom: 1.5rem;
            }}
            .eq-section {{
                color: {ORANGE};
                font-size: 0.80rem;
                letter-spacing: 0.2em;
                text-transform: uppercase;
                border-bottom: 1px solid {ORANGE_DIM};
                padding-bottom: 0.15rem;
                margin-top: 1.4rem;
                margin-bottom: 0.5rem;
            }}
            .eq-disclaimer {{
                color: {ORANGE_DIM};
                font-size: 0.75rem;
                line-height: 1.6;
                margin-top: 2rem;
                font-family: "Courier New", monospace;
            }}
            .eq-index-chip {{
                display: inline-block;
                padding: 0.35rem 0.75rem;
                margin: 0.25rem 0.35rem 0.25rem 0;
                border-radius: 0;
                background-color: {SURFACE};
                border: 1px solid #333333;
                font-family: "Courier New", monospace;
                font-size: 0.88rem;
                color: {GRAY};
                letter-spacing: 0.05em;
            }}
            /* Streamlit checkbox labels */
            .stCheckbox label p {{
                font-family: "Courier New", monospace !important;
                font-size: 0.92rem !important;
                color: {WHITE} !important;
            }}
            /* Input / select widgets */
            .stTextInput input, .stMultiSelect div {{
                background-color: {SURFACE} !important;
                color: {WHITE} !important;
                border-color: #444444 !important;
                font-family: "Courier New", monospace !important;
            }}
            .eq-mono {{ font-family: "Courier New", monospace; }}
            /* Dataframe header */
            .stDataFrame thead tr th {{
                background-color: {SURFACE} !important;
                color: {ORANGE} !important;
                font-family: "Courier New", monospace !important;
                border-bottom: 1px solid {ORANGE_DIM} !important;
            }}
            .stDataFrame tbody tr td {{
                font-family: "Courier New", monospace !important;
                color: {WHITE} !important;
            }}
            .stDataFrame tbody tr:hover td {{
                background-color: #1A1A1A !important;
            }}
            /* Download / primary buttons */
            .stDownloadButton button {{
                background-color: {SURFACE} !important;
                color: {ORANGE} !important;
                border: 1px solid {ORANGE} !important;
                border-radius: 0 !important;
                font-family: "Courier New", monospace !important;
                font-weight: 700;
                letter-spacing: 0.1em;
            }}
            .stDownloadButton button:hover {{
                background-color: {ORANGE} !important;
                color: {BG} !important;
            }}
            .stButton button[kind="primary"] {{
                background-color: {ORANGE} !important;
                color: {BG} !important;
                border: 1px solid {ORANGE} !important;
                border-radius: 0 !important;
                font-family: "Courier New", monospace !important;
                font-weight: 700;
                letter-spacing: 0.1em;
            }}
            .stButton button[kind="primary"]:hover {{
                background-color: {ORANGE_DIM} !important;
            }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _header() -> None:
    st.markdown(
        '<div class="eq-header">EQ · IDX · AGG</div>'
        '<div class="eq-subtitle">EQUITY INDEX CONSTITUENT AGGREGATOR</div>',
        unsafe_allow_html=True,
    )


def _index_selector() -> tuple[list[str], bool, bool]:
    st.markdown(
        '<div class="eq-section">Index Selection</div>',
        unsafe_allow_html=True,
    )

    # Initialise per-chip session state (DAX selected by default).
    for _, name, _ in ACTIVE_INDICES:
        key = f"idx_{name}"
        if key not in st.session_state:
            st.session_state[key] = name == "DAX"

    # Bulk toggle row.
    bulk1, bulk2, _spacer = st.columns([1, 1, 8])
    with bulk1:
        if st.button("Select All", key="select_all", width="stretch"):
            for _, name, _ in ACTIVE_INDICES:
                st.session_state[f"idx_{name}"] = True
            st.rerun()
    with bulk2:
        if st.button("Clear", key="clear_all", width="stretch"):
            for _, name, _ in ACTIVE_INDICES:
                st.session_state[f"idx_{name}"] = False
            st.rerun()

    # Chip grid — 5 per row.
    selected: list[str] = []
    per_row = 5
    rows = (len(ACTIVE_INDICES) + per_row - 1) // per_row
    for r in range(rows):
        cols = st.columns(per_row)
        for i, col in enumerate(cols):
            idx = r * per_row + i
            if idx >= len(ACTIVE_INDICES):
                continue
            iso, name, count = ACTIVE_INDICES[idx]
            key = f"idx_{name}"
            is_sel = bool(st.session_state.get(key, False))
            label = f"{iso}  |  {name}  ({count})"
            with col:
                if st.button(
                    label,
                    key=f"chip_btn_{name}",
                    type="primary" if is_sel else "secondary",
                    width="stretch",
                ):
                    st.session_state[key] = not is_sel
                    st.rerun()
            if st.session_state.get(key):
                selected.append(name)

    if DISABLED_INDICES:
        chips_html = ""
        for label in DISABLED_INDICES:
            chips_html += (
                f'<div class="eq-index-chip" title="Coming soon">{label}</div>'
            )
        st.markdown(chips_html, unsafe_allow_html=True)

    if "S&P 500" in selected:
        st.warning(
            "S&P 500 includes 503 securities. "
            "First fetch takes ~20s — subsequent loads are cached and instant.",
            icon="⏱️",
        )

    col1, col2 = st.columns([1, 3])
    with col1:
        fetch_clicked = st.button(
            "FETCH / REFRESH", type="primary", width="stretch"
        )
    with col2:
        force_refresh = st.checkbox(
            "Force refresh (bypass cache)", value=False
        )
    return selected, fetch_clicked, force_refresh


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_fetch(index_names: tuple[str, ...], force_refresh: bool) -> QueryResult:
    service = AggregationService()
    return asyncio.run(service.fetch(list(index_names), force_refresh=force_refresh))


def _do_fetch(
    selected: list[str], force_refresh: bool
) -> QueryResult | None:
    if force_refresh:
        _cached_fetch.clear()
    try:
        with st.spinner(f"Fetching constituents for {', '.join(selected)}…"):
            result = _cached_fetch(tuple(selected), force_refresh)
    except Exception as exc:  # noqa: BLE001 — UI must never crash
        st.error(f"Fetch failed: {exc}")
        return None
    st.session_state["last_fetch_at"] = datetime.now().isoformat(timespec="seconds")
    return result


def _filters_row(df: pd.DataFrame) -> tuple[str, list[str], bool]:
    col_search, col_sector, col_div = st.columns([2, 2, 1])
    with col_search:
        search = st.text_input(
            "Search (ticker / company / ISIN)", value="", placeholder="e.g. SAP"
        )
    with col_sector:
        raw_sectors = cast(
            list[Any],
            df["Sector"].tolist(),  # pyright: ignore[reportUnknownMemberType]
        )
        seen: set[str] = set()
        for v in raw_sectors:
            if isinstance(v, str) and v:
                seen.add(v)
        sector_values: list[str] = sorted(seen)
        sectors = st.multiselect("Sector", sector_values, default=[])
    with col_div:
        st.markdown("&nbsp;", unsafe_allow_html=True)
        div_only = st.checkbox("Dividend payers only", value=False)
    return search, sectors, div_only


def _unique_values(df: pd.DataFrame, column: str) -> list[str]:
    vals = cast(list[Any], df[column].tolist())  # pyright: ignore[reportUnknownMemberType]
    seen: set[str] = set()
    for v in vals:
        if isinstance(v, str) and v:
            seen.add(v)
    return sorted(seen)


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _empty_rule() -> dict[str, Any]:
    next_id = int(st.session_state.get("adv_rule_seq", 0)) + 1
    st.session_state["adv_rule_seq"] = next_id
    return {
        "id": next_id,
        "connector": "AND",
        "field": "Sector",
        "operator": "is",
        "value": None,
        "value2": None,
    }


def _render_rule_row(
    df: pd.DataFrame, rule: dict[str, Any], idx: int
) -> None:
    """Render a single rule row; mutate `rule` in-place via session state."""
    rid = int(rule.get("id", idx))
    if idx == 0:
        cols = st.columns([2, 2, 3, 1])
        conn_col = None
        field_col, op_col, val_col, del_col = cols
    else:
        cols = st.columns([1, 2, 2, 3, 1])
        conn_col, field_col, op_col, val_col, del_col = cols

    if conn_col is not None:
        with conn_col:
            connector = st.selectbox(
                "Join",
                options=["AND", "OR"],
                index=0 if rule.get("connector", "AND") == "AND" else 1,
                key=f"adv_conn_{rid}",
                label_visibility="collapsed",
            )
            rule["connector"] = connector
    else:
        rule["connector"] = None

    field_names = list(FILTER_FIELDS.keys())
    with field_col:
        current_field = rule.get("field", field_names[0])
        if current_field not in field_names:
            current_field = field_names[0]
        field = st.selectbox(
            "Field",
            options=field_names,
            index=field_names.index(current_field),
            key=f"adv_field_{rid}",
            label_visibility="collapsed",
        )
        # Reset stale value when field changes — old value belongs to a
        # different column/type and would either crash or prefill garbage.
        if field != rule.get("field"):
            rule["value"] = None
            rule["value2"] = None
            for suffix in ("val", "val2"):
                st.session_state.pop(f"adv_{suffix}_{rid}", None)
        rule["field"] = field

    spec = FILTER_FIELDS[field]
    ops: list[str] = spec["operators"]
    with op_col:
        current_op = rule.get("operator", ops[0])
        if current_op not in ops:
            current_op = ops[0]
        op = st.selectbox(
            "Operator",
            options=ops,
            index=ops.index(current_op),
            key=f"adv_op_{rid}",
            label_visibility="collapsed",
        )
        rule["operator"] = op

    with val_col:
        ftype = spec["type"]
        if op == "no dividend":
            st.caption("(no value)")
            rule["value"] = None
            rule["value2"] = None
        elif ftype == "text":
            rule["value"] = st.text_input(
                "Value",
                value=str(rule.get("value") or ""),
                key=f"adv_val_{rid}",
                label_visibility="collapsed",
                placeholder="text…",
            )
            rule["value2"] = None
        elif ftype == "select":
            options = [""] + _unique_values(df, field)
            cur = rule.get("value") or ""
            if cur not in options:
                cur = ""
            picked = st.selectbox(
                "Value",
                options=options,
                index=options.index(cur),
                key=f"adv_val_{rid}",
                label_visibility="collapsed",
            )
            rule["value"] = picked or None
            rule["value2"] = None
        else:  # number
            if op == "between":
                c1, c2 = st.columns(2)
                with c1:
                    v1 = st.number_input(
                        "Min",
                        value=_safe_float(rule.get("value")),
                        key=f"adv_val_{rid}",
                        label_visibility="collapsed",
                        placeholder="min",
                    )
                with c2:
                    v2 = st.number_input(
                        "Max",
                        value=_safe_float(rule.get("value2")),
                        key=f"adv_val2_{rid}",
                        label_visibility="collapsed",
                        placeholder="max",
                    )
                rule["value"] = v1
                rule["value2"] = v2
            else:
                v = st.number_input(
                    "Value",
                    value=_safe_float(rule.get("value")),
                    key=f"adv_val_{rid}",
                    label_visibility="collapsed",
                    placeholder="number",
                )
                rule["value"] = v
                rule["value2"] = None

    with del_col:
        if st.button("Remove", key=f"adv_del_{rid}", width="stretch"):
            rules = cast(list[dict[str, Any]], st.session_state.get("adv_rules", []))
            new_rules = [r for r in rules if int(r.get("id", -1)) != rid]
            st.session_state["adv_rules"] = new_rules
            for suffix in ("conn", "field", "op", "val", "val2", "del"):
                st.session_state.pop(f"adv_{suffix}_{rid}", None)
            st.rerun()


def _advanced_filters(df: pd.DataFrame) -> list[dict[str, Any]]:
    rules = cast(list[dict[str, Any]], st.session_state.get("adv_rules", []))
    # Migrate any pre-existing rules without an id (older session state).
    for r in rules:
        if "id" not in r:
            next_id = int(st.session_state.get("adv_rule_seq", 0)) + 1
            st.session_state["adv_rule_seq"] = next_id
            r["id"] = next_id
    label = "Advanced Filters"
    if rules:
        label = f"Advanced Filters  ({len(rules)} active)"
    with st.expander(label, expanded=bool(rules)):
        if not rules:
            st.caption("No rules. Add one to build a multi-condition filter.")
        for i, rule in enumerate(rules):
            _render_rule_row(df, rule, i)

        add_col, clear_col, _sp = st.columns([1, 1, 6])
        with add_col:
            if st.button(
                "Add rule",
                key="adv_add",
                width="stretch",
                disabled=len(rules) >= 10,
            ):
                rules.append(_empty_rule())
                st.session_state["adv_rules"] = rules
                st.rerun()
        with clear_col:
            if st.button(
                "Clear all rules",
                key="adv_clear",
                width="stretch",
                disabled=not rules,
            ):
                for r in rules:
                    rid = int(r.get("id", -1))
                    for suffix in ("conn", "field", "op", "val", "val2", "del"):
                        st.session_state.pop(f"adv_{suffix}_{rid}", None)
                st.session_state["adv_rules"] = []
                st.rerun()
    return rules


def _render_table(df: pd.DataFrame) -> None:
    st.dataframe(
        df,
        width="stretch",
        hide_index=True,
        column_config={
            "Ticker": st.column_config.TextColumn("Ticker", width="small"),
            "Company": st.column_config.TextColumn("Company"),
            "ISIN": st.column_config.TextColumn("ISIN", width="medium"),
            "Country": st.column_config.TextColumn("Country", width="small"),
            "Weight %": st.column_config.NumberColumn(
                "Index Wt %", format="%.2f%%", width="small",
                help="Position in the index (authoritative provider weight).",
            ),
            "Price": st.column_config.NumberColumn(
                "Price", format="%.2f", width="small"
            ),
            "Currency": st.column_config.TextColumn("Currency", width="small"),
            "Ex-Div Date": st.column_config.DateColumn("Ex-Div Date", width="small"),
            "TTM Div Yield": st.column_config.NumberColumn(
                "TTM Div Yield", format="%.2f%%", width="small"
            ),
            "Beta": st.column_config.NumberColumn(
                "Beta", format="%.2f", width="small"
            ),
            "Market Cap": st.column_config.NumberColumn(
                "Market Cap", format="%d", width="medium"
            ),
            "Sector": st.column_config.TextColumn("Sector"),
        },
    )


def _download_row(result: QueryResult) -> None:
    st.markdown(
        '<div class="eq-section">Download</div>', unsafe_allow_html=True
    )
    index_slug = "_".join(
        i.name.lower().replace(" ", "").replace("&", "").replace("/", "")
        for i in result.indices
    )
    date_str = datetime.now().strftime("%Y-%m-%d")
    base_filename = f"{index_slug}_constituents_{date_str}"
    col_csv, col_json, col_xlsx = st.columns(3)
    with col_csv:
        st.download_button(
            "CSV",
            data=to_csv(result),
            file_name=f"{base_filename}.csv",
            mime="text/csv",
            width="stretch",
        )
    with col_json:
        st.download_button(
            "JSON",
            data=to_json(result),
            file_name=f"{base_filename}.json",
            mime="application/json",
            width="stretch",
        )
    with col_xlsx:
        st.download_button(
            "EXCEL",
            data=to_xlsx(result),
            file_name=f"{base_filename}.xlsx",
            mime=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            width="stretch",
        )


def _data_sources_expander() -> None:
    with st.expander("Data Sources", expanded=False):
        st.markdown(
            """
            - **Yahoo Finance (yfinance)** — unofficial Python library. May break
              without warning.
            - **ISIN data** — static curated map (v1). yfinance and OpenFIGI do
              not return ISINs for DE tickers.
            - **OpenFIGI** — queried for FIGI mapping (not ISIN). Rate limited.
            """
        )


def _cache_status_expander() -> None:
    with st.expander("Cache Status", expanded=False):
        ttl = st.select_slider(
            "Cache TTL",
            options=[1800, 3600, 21600, 86400],
            value=3600,
            format_func=lambda s: {
                1800: "30 min",
                3600: "1 hr",
                21600: "6 hr",
                86400: "24 hr",
            }[s],
            key="cache_ttl",
        )
        stats: dict[str, dict[str, object]] = ConstituentCache(
            ttl_seconds=ttl
        ).stats()
        if not stats:
            st.caption("Cache is empty.")
            return
        rows: list[dict[str, Any]] = []
        for index_name, meta in stats.items():
            hit = bool(meta.get("hit"))
            fetched_at = meta.get("fetched_at")
            expires_at = meta.get("expires_at")
            rows.append(
                {
                    "Index": index_name,
                    "Fetched At": (
                        fetched_at.isoformat(timespec="seconds")
                        if isinstance(fetched_at, datetime)
                        else str(fetched_at)
                    ),
                    "Expires At": (
                        expires_at.isoformat(timespec="seconds")
                        if isinstance(expires_at, datetime)
                        else str(expires_at)
                    ),
                    "Status": "LIVE" if hit else "STALE",
                }
            )
        st.dataframe(
            pd.DataFrame(rows), width="stretch", hide_index=True
        )


def _disclaimer() -> None:
    st.markdown(
        '<div class="eq-disclaimer">'
        "DATA SOURCED FROM YAHOO FINANCE (UNOFFICIAL API). "
        "Prices may be delayed. TTM dividend yield is historical, not a "
        "forward estimate.<br/>"
        "Not financial advice. For informational purposes only."
        "</div>",
        unsafe_allow_html=True,
    )


def main() -> None:
    _inject_css()
    _header()

    selected, fetch_clicked, force_refresh = _index_selector()

    if "result" not in st.session_state:
        st.session_state["result"] = None
    if fetch_clicked:
        if not selected:
            st.warning("Select at least one index above")
        else:
            st.session_state["result"] = _do_fetch(selected, force_refresh)

    if not selected:
        st.info("Select at least one index above")
        _data_sources_expander()
        _cache_status_expander()
        _disclaimer()
        return

    result_obj: object = st.session_state.get("result")
    if not isinstance(result_obj, QueryResult):
        st.info(
            "Select an index and click **Fetch / Refresh** to load constituents."
        )
        _data_sources_expander()
        _cache_status_expander()
        _disclaimer()
        return

    all_constituents = [c for idx in result_obj.indices for c in idx.constituents]

    full_df = constituents_to_dataframe(all_constituents)
    search, sectors, div_only = _filters_row(full_df)

    filtered = filter_constituents(
        all_constituents, search=search, sectors=sectors, div_only=div_only
    )
    filtered_df = constituents_to_dataframe(filtered)

    adv_rules = _advanced_filters(full_df)
    if adv_rules:
        filtered_df = apply_advanced_filters(filtered_df, adv_rules)

    st.markdown(
        f'<div class="eq-section">Constituents — '
        f"Showing {len(filtered_df)} of {len(all_constituents)}</div>",
        unsafe_allow_html=True,
    )
    for index in result_obj.indices:
        st.caption(
            f"📅 {index.name}: last fetched "
            f"{index.fetched_at.strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )

    # Default to Index Weight when available — that's the "position in the
    # index" the user expects to see. Falls back to Market Cap for indices
    # without curated weights (yfinance market_cap is the next-best proxy).
    if "sort_column" not in st.session_state:
        st.session_state.sort_column = "Weight %"
    if "sort_ascending" not in st.session_state:
        st.session_state.sort_ascending = False

    col1, col2 = st.columns([3, 1])
    with col1:
        st.session_state.sort_column = st.selectbox(
            "Sort by",
            options=[
                "Weight %",
                "Market Cap",
                "Price",
                "TTM Div Yield",
                "Beta",
                "Company",
                "Ticker",
            ],
            index=0,
            key="sort_col_select",
            label_visibility="collapsed",
        )
    with col2:
        st.session_state.sort_ascending = st.toggle(
            "Ascending", value=False, key="sort_asc_toggle"
        )

    filtered_df = filtered_df.sort_values(
        st.session_state.sort_column,
        ascending=st.session_state.sort_ascending,
        na_position="last",
    )
    _render_table(filtered_df)

    _download_row(result_obj)
    _data_sources_expander()
    _cache_status_expander()
    _disclaimer()


# Streamlit invokes the script via runpy, so `__name__ == "__main__"` runs
# the UI. Importing the module (e.g. from doctor.py) does not, which keeps
# the smoke test side-effect free.
if __name__ == "__main__":
    main()
