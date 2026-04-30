FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip setuptools wheel alembic

COPY pyproject.toml /app/pyproject.toml
COPY README.md /app/README.md
COPY epcr_app /app/epcr_app
COPY migrations /app/migrations
COPY alembic.ini /app/alembic.ini
COPY nemsis /app/nemsis

RUN pip install .

RUN adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:' + __import__('os').environ.get('PORT', '8000') + '/healthz').read()" || exit 1

CMD ["sh", "-c", "alembic upgrade head && uvicorn epcr_app.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
