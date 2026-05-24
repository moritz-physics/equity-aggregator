---
name: yfinance-fields
description: Verified yfinance field names for price, yield, beta, mktcap, sector, ex-div date across European listings
metadata:
  type: reference
---

Verified field names from `yf.Ticker(t).info` for European equities:

| Field | yfinance key | Notes |
|-------|-------------|-------|
| Price | `currentPrice` → `regularMarketPrice` → `previousClose` | Fallback chain |
| Yield | `dividendYield` | Already as percentage (e.g. 3.94 means 3.94%) |
| Beta | `beta` | Float |
| Market cap | `marketCap` | Float, in local currency |
| Sector | `sector` | String |
| Ex-div date | `exDividendDate` | Unix epoch seconds — use `_epoch_to_date()` |
| Name | `longName` → `shortName` | Fallback chain |
| Currency | `currency` | CHF for .SW, EUR for .BR, .AS, .DE |
| ISIN | `info.get("isin")` | Returns None or absent — NEVER reliable for EU listings |

**ISIN finding:** yfinance does NOT return ISINs for Swiss (.SW) or Belgian (.BR) listings. The `isin` key is entirely missing from info dict for .BR tickers. For .SW tickers, the key exists but returns None. Static map is the only reliable source.

**Why:** Verified by live probe on 2026-05-24 against NESN.SW and ABI.BR.
