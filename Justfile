default:
    @just --list

install:
    uv sync

doctor:
    uv run python scripts/doctor.py

test:
    uv run pytest tests/ -v --tb=short

lint:
    uv run ruff check src/ tests/
    uv run pyright src/

fmt:
    uv run ruff format src/ tests/

api:
    uv run uvicorn equity_aggregator.api.main:app --reload

ui:
    uv run streamlit run src/equity_aggregator/ui/app.py

live-test:
    uv run python scripts/test_live.py

audit:
    @echo "No audit implemented yet"

docker-build:
    docker build -t equity-aggregator .

docker-run:
    docker compose up

docker-stop:
    docker compose down

docker-clean:
    docker compose down -v
