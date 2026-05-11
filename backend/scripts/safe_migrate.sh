#!/usr/bin/env bash
# safe_migrate.sh — stamp epcr_alembic_version to 040 if empty, then upgrade to head.
#
# Background: the production DB was bootstrapped before epcr_alembic_version was
# introduced as a custom version table.  All migrations 001-040 ran successfully
# against the default alembic_version table (or were applied manually), but
# epcr_alembic_version is empty.  Alembic therefore tries to re-run from 001,
# hitting DuplicateTableError on epcr_charts and exiting 1.
#
# This script detects the empty-version-table state and stamps to 040 before
# running upgrade head.  Subsequent runs see 040 already applied and proceed
# normally.
set -euo pipefail

echo "=== Adaptix EPCR safe migration ==="

# Guard: if no database URL is configured, skip migration entirely so that
# the container can still start (healthz returns 200 from the in-memory app).
# This handles staging environments where DATABASE_URL is not yet provisioned.
if [ -z "${DATABASE_URL:-}" ] && [ -z "${EPCR_DATABASE_URL:-}" ] && [ -z "${CARE_DATABASE_URL:-}" ]; then
    echo "WARNING: No database URL env var found (DATABASE_URL / EPCR_DATABASE_URL / CARE_DATABASE_URL)."
    echo "Skipping Alembic migrations. The service will start but DB operations will be unavailable."
    exit 0
fi

CURRENT=$(alembic current 2>&1 || true)
echo "alembic current output:"
echo "${CURRENT}"

# If current output contains a revision hash, the version table has entries.
# Otherwise (empty output or error), we need to stamp.
if echo "${CURRENT}" | grep -qE "^[0-9a-f]{3,}|^[0-9]{3,}"; then
    echo "Version table is populated. Running upgrade head..."
else
    echo "Version table is empty or missing — stamping to 040 (last known-good state)..."
    alembic stamp --purge 040
    echo "Stamp complete. Running upgrade head..."
fi

alembic upgrade head
echo "=== Migration complete ==="
