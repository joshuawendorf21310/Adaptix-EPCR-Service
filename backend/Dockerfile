FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip

COPY contracts/ /contracts/
RUN pip install --no-cache-dir /contracts

COPY epcr/backend/pyproject.toml ./
COPY epcr/backend/epcr_app/ ./epcr_app/

RUN pip install --no-cache-dir .

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

CMD ["uvicorn", "epcr_app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
