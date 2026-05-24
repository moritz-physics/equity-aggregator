---
name: data-sources-aex-sti
description: Which APIs work for AEX and STI constituent lists, and why static maps are the authoritative source
metadata:
  type: project
---

# Data Source Findings: AEX and STI (probed 2026-05-24)

## AEX (Amsterdam Exchange Index)

**Euronext Live API** (`live.euronext.com/en/pd/data/index/compositon?index_id=QS0011052587-XAMS&indexname=AEX`):
- Returns HTTP 301 redirect to the homepage. Requires session cookies to access machine-readable data.
- **Verdict: unusable without authentication.**

**Wikipedia** (`en.wikipedia.org/wiki/AEX_index`):
- `pandas.read_html` requires `lxml` or `html5lib`, neither installed in this project.
- **Verdict: unusable without adding dependencies.**

**Conclusion**: Curated static tuple of `_Member(ticker, name, isin)` is the most reliable AEX source.
Review when Euronext rebalances (typically quarterly).

## STI (Straits Times Index)

**SGX JSON API** (`api2.sgx.com/sites/default/files/ngah/api/index-constituent/STI.json`):
- Returns HTTP 404.
- **Verdict: endpoint no longer exists.**

**SGX Web Page** (`www.sgx.com/indices/products/sti`):
- Returns 200 but is a JavaScript SPA — no HTML tables parseable without a headless browser.
- **Verdict: unusable without Playwright/Selenium.**

**Conclusion**: Curated static tuple of `_Member(ticker, name, isin)` is the most reliable STI source.
Review when FTSE/SGX rebalances (typically quarterly).

## Why static maps beat live scraping

Both Euronext and SGX protect their data behind authentication or JS rendering. For well-known,
fixed-size indices (AEX=25, STI=30) the static map approach is more robust, faster, and simpler
than maintaining fragile scrapers. The review cadence (quarterly rebalancing) matches normal
maintenance cycles.

**How to apply**: For any new index adapter where the exchange API is blocked or JS-rendered,
start with a static `_Member` tuple rather than spending time on scraper infra.
