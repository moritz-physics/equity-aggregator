# Agent Memory — AEX & STI Adapter Builder

- [Data source findings for AEX and STI](data-sources.md) — which APIs work, which fail, and why static maps win
- [yfinance field mapping and quirks per exchange](yfinance-fields.md) — exact field names, value shapes, ISIN absence
- [ISIN conventions and non-standard members](isin-conventions.md) — prefix rules, foreign-incorporated members
- [dax.py patterns reused in AEX/STI adapters](dax-patterns.md) — what transferred cleanly, what needed notes
- [Test mocking patterns](test-patterns.md) — how to mock yfinance and httpx, failure isolation structure
