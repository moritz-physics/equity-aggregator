FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install uv --no-cache-dir

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
COPY data/ ./data/
COPY scripts/ ./scripts/

RUN uv sync --frozen --no-dev

RUN mkdir -p data

EXPOSE 8502

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:8502/_stcore/health || exit 1

CMD ["uv", "run", "streamlit", "run", \
     "src/equity_aggregator/ui/app.py", \
     "--server.port=8502", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
