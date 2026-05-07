FROM python:3.11-slim

# Build-time identity. Populated by CI (e.g. CodeBuild / GitHub Actions) so the
# resulting image self-reports which commit it is. Surfaced at runtime via
# /api/v1/epcr/version. Defaults are intentionally "unknown" so a local docker
# build still produces a runnable image, just without verifiable identity.
ARG BUILD_COMMIT_SHA=unknown
ARG BUILD_BRANCH=unknown
ARG BUILD_TIME=unknown

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    BUILD_COMMIT_SHA=${BUILD_COMMIT_SHA} \
    BUILD_BRANCH=${BUILD_BRANCH} \
    BUILD_TIME=${BUILD_TIME}

WORKDIR /app

# git is required because backend/pyproject.toml installs:
#   adaptix-contracts @ git+https://github.com/joshuawendorf21310/Adaptix-Contracts.git
# Without git, the image can build without the contracts package and the container fails
# at runtime with: ModuleNotFoundError: No module named 'adaptix_contracts'.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip setuptools wheel alembic

COPY backend/pyproject.toml ./pyproject.toml
COPY backend/epcr_app/ ./epcr_app/
COPY backend/migrations/ ./migrations/
COPY backend/alembic.ini ./alembic.ini
COPY backend/README.md ./README.md

RUN pip install .

# Bake non-sensitive build identity into a JSON sidecar consumed by
# epcr_app.api_version at runtime. Contains only commit SHA, branch, and
# build timestamp -- no secrets, no tenant data, no env values.
RUN printf '{"commit_sha":"%s","branch":"%s","build_time":"%s"}\n' \
        "${BUILD_COMMIT_SHA}" "${BUILD_BRANCH}" "${BUILD_TIME}" \
        > /app/.build_info.json \
    && chmod 0444 /app/.build_info.json

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/healthz').read()" || exit 1


# Run as non-root user for security
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid appgroup --shell /bin/bash --create-home appuser
USER appuser
CMD ["sh", "-c", "alembic upgrade head && uvicorn epcr_app.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
