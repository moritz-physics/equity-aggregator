---
name: project-context
description: Overall project setup — 4-agent parallel equity-aggregator build, file boundaries, stack
metadata:
  type: project
---

4-agent parallel build of `equity-aggregator` at `~/Desktop/Projects/equity-aggregator`.

Stack: Python 3.12, uv, yfinance, httpx, Pydantic v2, SQLModel, rich.

Agent B owns: `adapters/smi.py`, `adapters/bel20.py`, `tests/test_smi.py`, `tests/test_bel20.py`.

**Why:** 4-agent division of labor to build multiple index adapters in parallel.

**How to apply:** Never touch forbidden files (`adapters/__init__.py`, `adapters/dax.py`, `scripts/doctor.py`, `scripts/test_live.py`, or any other existing file).
