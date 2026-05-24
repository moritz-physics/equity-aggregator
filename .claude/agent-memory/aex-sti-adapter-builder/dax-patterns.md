---
name: dax-patterns-reuse
description: Which patterns from dax.py transferred cleanly to AEX/STI adapters and which needed adaptation
metadata:
  type: project
---

# DAX Patterns: Reuse in AEX and STI Adapters

## Transferred cleanly (copy-paste with constant substitutions)
- `_Member` frozen dataclass with `(ticker, name, isin)` fields
- `_epoch_to_date()` — defensive Unix epoch → `date` conversion
- `_coerce_float()` — NaN-safe float coercion
- `_coerce_str()` — strip-and-None string coercion
- `_resolve_isin_from_yfinance()` — handles None, "-", whitespace
- `_fetch_yf_info()` — asyncio.to_thread wrapper with try/except
- `_fetch_openfigi()` — best-effort call, 4xx → None, non-200 → None
- `_build_constituent()` — three-tier ISIN resolution (yfinance → openfigi → static)
- `_fetch_member()` — asyncio.gather + try/except fallback to static-only Constituent
- `AEXAdapter/STIAdapter` class structure — `name`, `country`, `source` class attrs, `__init__` + `fetch_constituents`
- Module-level docstring structure — findings, field list, yfinance warning

## What changed per adapter
- `INDEX_COUNTRY`: `"DE"` → `"NL"` (AEX) / `"SG"` (STI)
- `OPENFIGI_EXCH_CODE`: `"GS"` → `"XAMS"` (AEX) / `"XSES"` (STI)
- `INDEX_NAME`: `"DAX"` → `"AEX"` / `"STI"`
- `DAX_MEMBERS` tuple: 40 entries → 25 (AEX) / 30 (STI)
- Fallback currency in `_fetch_member` except clause: `"EUR"` (AEX) / `"SGD"` (STI)
- Assert count: `== 40` → `== 25` / `== 30`
- Added `AEX_ISINS` / `STI_ISINS` convenience dicts (derived from member tuple, exposed for test assertions)

## Naming difference: DAX uses tuple of _Member; AEX/STI use the same pattern
DAX exposes `DAX_MEMBERS: tuple[_Member, ...]`. AEX/STI expose both:
- `AEX_MEMBERS: tuple[_Member, ...]` / `STI_MEMBERS: tuple[_Member, ...)`
- `AEX_ISINS: dict[str, str]` / `STI_ISINS: dict[str, str]` — convenience dicts for test assertions

## How to apply
Future index adapters should be built by starting from dax.py and doing a global substitution
of constants. The only structural decision is: what is the OpenFIGI exchCode for this exchange?
Look it up in OpenFIGI's exchange code list. Everything else follows the same pattern.
