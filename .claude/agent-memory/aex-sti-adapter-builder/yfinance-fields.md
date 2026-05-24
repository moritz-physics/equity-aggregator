---
name: yfinance-fields-aex-sti
description: yfinance field names, value shapes, and quirks for AEX (.AS) and STI (.SI) tickers
metadata:
  type: project
---

# yfinance Field Mapping: AEX and STI (probed 2026-05-24)

## Ticker suffix conventions
- AEX (Euronext Amsterdam): `.AS` suffix — e.g. `ASML.AS`, `HEIA.AS`, `INGA.AS`
- STI (Singapore Exchange): `.SI` suffix — e.g. `D05.SI`, `O39.SI`, `U11.SI`

## Working field names (same as DAX)
Both `.AS` and `.SI` tickers use identical yfinance field names:
- `longName` — full company name (preferred)
- `shortName` — abbreviated name (fallback)
- `currentPrice` — latest price (primary)
- `regularMarketPrice` — fallback price #1
- `previousClose` — fallback price #2
- `currency` — ISO currency code (EUR for AEX, SGD for most STI, USD for H78.SI/J36.SI)
- `sector` — sector classification string
- `beta` — beta coefficient (float or None)
- `marketCap` — market cap in native currency (float)
- `dividendYield` — expressed as PERCENTAGE (e.g. `0.77` = 0.77% for ASML, `5.22` = 5.22% for DBS)
- `exDividendDate` — Unix epoch in seconds (convert with `datetime.fromtimestamp`)

## ISIN absence
- `info.get("isin")` returns `None` for ALL AEX (.AS) and STI (.SI) tickers probed.
- `yf.Ticker(...).isin` property was not tested but expected to return `"-"` sentinel (see DAX findings).
- Static map is the only reliable ISIN source for both exchanges.

## Return count
- ASML.AS returned 170 info fields
- D05.SI returned 161 info fields

## Exchange quirks
- Two STI members (H78.SI = Hongkong Land, J36.SI = Jardine Matheson) are priced in USD on SGX.
  Their `currency` field will be `"USD"`, not `"SGD"`. Do not override — it is correct.
- `info.get("country")` returns `"Netherlands"` for AEX tickers, `"Singapore"` for most STI tickers.
  Adapter ignores this and sets `country` from the index constant (`NL` or `SG`) to reflect listing venue.

## How to apply
When building new adapters, these field names are stable across exchanges. Always fall through:
`currentPrice` → `regularMarketPrice` → `previousClose`. Always treat `dividendYield` as a
percentage value (not a ratio), consistent with DAX adapter convention.
