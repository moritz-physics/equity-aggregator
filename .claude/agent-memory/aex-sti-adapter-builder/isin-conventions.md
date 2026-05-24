---
name: isin-conventions-aex-sti
description: ISIN prefix rules for AEX and STI, including foreign-incorporated members that break the dominant prefix
metadata:
  type: project
---

# ISIN Conventions: AEX and STI (verified 2026-05-24)

## AEX — Netherlands (dominant prefix: NL)
Most AEX members have ISINs starting with `NL`. Exceptions (foreign-incorporated but Amsterdam-listed):
- `MT.AS` (ArcelorMittal) — ISIN `LU1598757687` (Luxembourg-incorporated)
- `REN.AS` (RELX PLC) — ISIN `GB00B2B0DG97` (UK-incorporated)
- `SHELL.AS` (Shell plc) — ISIN `GB00BP6MXD84` (UK-incorporated)
- `UNA.AS` (Unilever PLC) — ISIN `GB00B10RZP78` (UK-incorporated)

So 21/25 AEX members have NL ISINs; 4 have GB or LU ISINs.

## STI — Singapore (dominant prefix: SG)
Most STI members have ISINs starting with `SG`. Exceptions (foreign-incorporated but SGX-listed):
- `H78.SI` (Hongkong Land Holdings) — ISIN `BMG4587L1067` (Bermuda-incorporated)
- `J36.SI` (Jardine Matheson Holdings) — ISIN `KYG4762E1059` (Cayman Islands-incorporated)
- `Y92.SI` (Thai Beverage) — ISIN `TH0737010Z08` (Thailand-incorporated)

So 27/30 STI members have SG ISINs; 3 have BM/KY/TH ISINs.

## Impact on acceptance test assertions
The spec's `assert all(c.isin.startswith(isin_prefix) for c in result.constituents if c.isin)` will
FAIL if applied literally for AEX (4 non-NL) and STI (3 non-SG). The adapter correctly stores the
real ISINs for these members. The acceptance script's separate note confirms this is expected behavior.

The count and isin_count assertions both pass:
- AEX: 25 constituents, 25 ISINs (all have ISINs from static map)
- STI: 30 constituents, 30 ISINs (all have ISINs from static map)

## How to apply
When building static ISIN maps, do not assume all members of an index are incorporated in that
country. Check each member's actual ISIN from an authoritative source (Euronext, SGX, or issuer
IR pages). The listing country (exchange) != the ISIN country prefix for multinational companies.
