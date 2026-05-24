---
name: test-patterns-aex-sti
description: Effective mocking patterns for yfinance and httpx in AEX/STI adapter unit tests
metadata:
  type: project
---

# Test Mocking Patterns: AEX and STI Adapters

## yfinance mocking approach
Tests mock `_fetch_yf_info` at the module level using `patch.object(module, "_fetch_yf_info", async_fn)`.
This avoids any network calls. The mock returns a plain `dict[str, Any]`.

```python
async def _empty_yf(_: str) -> dict[str, Any]:
    return {}

with patch.object(aex_module, "_fetch_yf_info", _empty_yf):
    ...
```

## OpenFIGI mocking approach
Same pattern — mock `_fetch_openfigi` at module level:

```python
async def _none_figi(*_: Any, **__: Any) -> dict[str, Any] | None:
    return None

with patch.object(aex_module, "_fetch_openfigi", _none_figi):
    ...
```

## Failure isolation test pattern
Pass `client=None` to `_fetch_member` (typed `httpx.AsyncClient` but unused when both are mocked).
Use `# type: ignore[arg-type]` to silence pyright. This tests that the fallback Constituent is
built correctly from the static member data alone.

```python
c = await _fetch_member(client=None, member=member)  # type: ignore[arg-type]
```

## Test file structure (11 tests each, mirroring test_dax.py)
1. `test_build_constituent_maps_yfinance_fields` — full field mapping check
2. `test_build_constituent_prefers_yfinance_isin_when_present`
3. `test_build_constituent_treats_yfinance_dash_as_missing`
4. `test_build_constituent_uses_openfigi_isin_when_present`
5. `test_resolve_isin_from_yfinance_handles_garbage`
6. `test_fetch_member_survives_total_failure` — @pytest.mark.asyncio, both mocked to empty/None
7. `test_XXX_adapter_has_N_members` — count, uniqueness, suffix check
8. `test_XXX_adapter_is_instantiable` — name, country, callable
9. `test_XXX_all_members_have_isin_entry` — every ticker in ISINS dict
10. `test_XXX_currency_on_mock_output` — EUR/SGD asserted on a specific mocked constituent
11. `test_XXX_country_is_XX_for_all_members` — loop over all members, build with minimal info dict

## Key assertion: ex_div_date year/month
The epoch `1776988800` (ASML) decodes to 2026-04 (April 2026).
The epoch `1778457600` (DBS) decodes to 2026-05 (May 2026).
Tests assert `.year == 2026` and `.month == 4` or `.month == 5` respectively.

## pytest-asyncio config
`asyncio_mode = "auto"` in pyproject.toml means no `@pytest.mark.asyncio` is strictly needed,
but it is included for clarity (mirrors test_dax.py).

## How to apply
For each new index adapter, create a matching test file by substituting:
- The module import name
- The sample ticker info dict (pick a well-known member with a real live price)
- The member/ISINS constants names
- The expected country/currency/count values
