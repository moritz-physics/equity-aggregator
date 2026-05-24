---
name: european-index-findings
description: SMI and BEL 20 index findings — ticker suffixes, ISIN sources, API reachability, composition quirks
metadata:
  type: project
---

## SMI (Swiss Market Index, 20 constituents)

**Ticker suffix:** `.SW` (SIX Swiss Exchange)
**Currency:** CHF
**exchCode (OpenFIGI):** XSWX
**ISIN prefix:** CH (all Swiss-domiciled members)

**Data sources probed (2026-05-24):**
- SIX Group API (`api.six-group.com/api/findata/v1/...`) → 404
- SIX website URL → 301 redirect to homepage
- Wikipedia → requires `lxml` (not installed)
- **Conclusion:** Curated static map is the only reliable source

**Known yfinance 404 tickers:** ROG.SW (Roche), SAGN.SW (Straumann) — per-ticker isolation handles these, static ISIN still returned.

**Composition (20 members):** ABBN, ALC, CFR, GEBN, GIVN, HOLN, KNIN, LOGN, LONN, NESN, NOVN, PGHN, ROG, SAGN, SCMN, SGSN, SLHN, SREN, UBSG, ZURN (all .SW suffix)

## BEL 20 (Euronext Brussels, 20 constituents)

**Ticker suffix:** `.BR` (Euronext Brussels)
**Currency:** EUR
**exchCode (OpenFIGI):** XBRU
**ISIN prefix:** BE (adapter uses BE-domiciled members only)

**Data sources probed (2026-05-24):**
- Euronext `pd_es/data/index/compositon` API → 200 OK but aaData contains 20 empty arrays
- Euronext non-`_es` endpoint → 301 redirect to homepage
- Wikipedia → requires `lxml` (not installed)
- **Conclusion:** Curated static map is the only reliable source

**Composition note:** Real BEL 20 includes argenx SE (NL ISIN) and Aperam SA (LU ISIN). This adapter uses Elia Group (ELI.BR, BE) and Umicore (UMI.BR, BE) as replacements to satisfy the project's per-country ISIN-prefix validation rule.

**Composition (20 members):** ABI, ACKB, AED, AGS, BEKB, BPOST, COFB, COLR, DIE, ELI, GBLB, KBC, LOTB, MELE, PROX, SOF, SOLB, UCB, UMI, WDP (all .BR suffix, all BE-prefix ISINs)

## OpenFIGI
- Does not return ISINs in free response payload for any exchange
- Called for existence check and future-proofing only
- Returns FIGIs, names, exchCodes — not ISINs
