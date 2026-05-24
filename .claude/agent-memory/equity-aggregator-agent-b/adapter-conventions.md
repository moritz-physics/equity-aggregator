---
name: adapter-conventions
description: Established adapter pattern — IndexAdapter ABC, asyncio.to_thread, per-ticker isolation, three-tier ISIN resolution
metadata:
  type: project
---

All adapters in this project follow `adapters/dax.py` and `adapters/aex.py` as canonical patterns.

**Structure:**
- Module-level docstring MUST flag yfinance as unofficial
- Adapter class inherits `IndexAdapter` ABC from `adapters/base.py`
- `_Member` dataclass: `ticker, name, isin` (frozen, slots=True)
- `MEMBERS: tuple[_Member, ...]` with `assert len(...) == N`
- `ISINS: dict[str, str]` convenience dict derived from MEMBERS
- `_epoch_to_date`, `_coerce_float`, `_coerce_str` helper functions (identical across adapters)
- `_resolve_isin_from_yfinance` — treats "-" and None as missing
- `_fetch_yf_info` — wraps yfinance in `asyncio.to_thread`
- `_fetch_openfigi` — best-effort, silent on 4xx, logs debug on non-200
- `_build_constituent` — ISIN priority: yfinance → OpenFIGI → static
- `_fetch_member` — `asyncio.gather(yf, figi)`, try/except around `_build_constituent`, fallback to static-only row
- `Adapter` class: `name`, `country`, `source` as class attrs; `__init__` takes `members` param; `fetch_constituents` uses `asyncio.gather(*(_fetch_member(...) for m in members))`

**Why:** Consistency across adapters is more valuable than personal style. Mirror, don't innovate.

**How to apply:** Copy the pattern exactly. Do not vary helper function signatures or error handling patterns.
