FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt . 2>/dev/null || COPY requirements.txt . 2>/dev/null || true

RUN pip install --no-cache-dir -r requirements.txt 2>/dev/null || echo "No requirements.txt"

COPY backend/ ./backend/ 2>/dev/null || COPY . ./backend 2>/dev/null || true

ENV PYTHONPATH=/app/backend

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
