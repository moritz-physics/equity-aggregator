# equity-aggregator

## Purpose

Aggregate equity index constituent data from public sources into a single,
queryable, exportable dataset. Sibling project to `bond-aggregator`; mirrors
its architecture (adapters → core service → cache → export, plus FastAPI and
Streamlit front-ends).

## Target Indices

| # | Index | Region | Constituents | Adapter |
|---|---|---|---|---|
| 1 | DAX 40 | Germany | 40 | ✅ |
| 2 | MDAX | Germany | 50 | — |
| 3 | SDAX | Germany | 70 | — |
| 4 | TecDAX | Germany | 30 | — |
| 5 | Euro Stoxx 50 | Eurozone | 50 | — |
| 6 | Stoxx Europe 600 | Europe | 600 | — |
| 7 | FTSE 100 | UK | 100 | ✅ |
| 8 | CAC 40 | France | 40 | ✅ |
| 9 | IBEX 35 | Spain | 35 | ✅ |
| 10 | FTSE MIB | Italy | 40 | — |
| 11 | AEX | Netherlands | 25 | ✅ |
| 12 | SMI | Switzerland | 20 | ✅ |
| 13 | BEL 20 | Belgium | 20 | ✅ |
| 14 | WIG20 | Poland | 20 | ✅ |
| 15 | STI | Singapore | 30 | ✅ |
| 16 | S&P 500 | USA | 500 | ✅ |
| 17 | Nasdaq-100 | USA | 100 | — |

## Data Sources

- **yfinance** — Yahoo Finance scraper. See `data/sources.yaml`.
- **OpenFIGI** — Bloomberg identifier mapping. See `data/sources.yaml`.

## Known Limitations

> ⚠️ **yfinance is unofficial.** It scrapes Yahoo Finance and has no SLA,
> stable schema, or rate-limit contract. Yahoo can (and does) change
> endpoints without notice. This project treats yfinance as best-effort:
> cache aggressively, validate every field, fail loudly on schema drift,
> and never use yfinance as a system of record for anything that matters.

## Project Structure

```
src/equity_aggregator/
  adapters/    # per-source ingestion (base, dax, cac40, ftse100, …)
  core/        # models, service, cache, export
  api/         # FastAPI app
  ui/          # Streamlit app
data/          # sources.yaml, cache.db (gitignored)
tests/         # pytest suite
scripts/       # doctor.py, test_live.py
```

## Quickstart (local)

```bash
just install     # uv sync
just doctor      # verify environment
just test        # run unit tests
just lint        # ruff + pyright
just fmt         # ruff format
just api         # FastAPI on :8000
just ui          # Streamlit UI on :8501
just live-test   # exercise adapters against live sources
```

`make` targets mirror `just` one-to-one if you prefer Make.

## Quickstart (Docker)

The container ships a Streamlit UI on port **8502** (chosen to avoid
collision with a bare-metal `just ui` on 8501 and with bond-aggregator's
8501 container).

```bash
just docker-build   # docker build -t equity-aggregator .
just docker-run     # docker compose up
just docker-stop    # docker compose down
just docker-clean   # docker compose down -v   (also drops the cache volume)
```

Then open <http://localhost:8502>.

### Compose layout

- `docker-compose.yml` — production-shaped service: builds the image,
  exposes 8502, mounts a named volume `equity_cache` at `/app/data`,
  reads `CACHE_TTL_HOURS` from the environment, restarts unless stopped.
- `docker-compose.override.yml` — dev convenience: bind-mounts the repo
  root at `/app` so edits are picked up without rebuilding the image.
  Loaded automatically by `docker compose up`.

> ⚠️ **Dev override re-installs dependencies on every container start.**
> The bind-mount in `docker-compose.override.yml` shadows the image's
> baked-in `.venv` with the host directory, so `uv` rebuilds the venv
> inside the container on each start (~20 s before the health check goes
> green). This is fine for local iteration but **not** what you want in
> production — deploy with the base compose only:
>
> ```bash
> docker compose -f docker-compose.yml up -d
> ```
>
> In that mode the container starts in a second or two using the venv
> baked into the image at build time.

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `CACHE_TTL_HOURS` | `24` | How long cached constituent payloads stay fresh. |

### Health & data persistence

- Health endpoint: `GET http://localhost:8502/_stcore/health` (Streamlit
  built-in). The compose service is wired up with the same check.
- Cache lives in the `equity_cache` named volume mounted at `/app/data`.
  `just docker-stop` keeps it; `just docker-clean` drops it.
