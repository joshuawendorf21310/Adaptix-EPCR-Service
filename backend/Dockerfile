FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl netcat-openbsd git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /app/pyproject.toml

RUN pip install --no-cache-dir --upgrade "pip>=24.0" "setuptools>=70.0" "wheel>=0.43.0" && \
    pip install --no-cache-dir --no-build-isolation .

COPY . /app

RUN if [ -f /app/entrypoint.sh ]; then chmod +x /app/entrypoint.sh; fi

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz', timeout=3).status == 200 else 1)"


# Run as non-root user for security
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid appgroup --shell /bin/bash --create-home appuser
USER appuser
CMD ["/app/entrypoint.sh"]
