"""Pre-migration stamp helper.

When the production database has existing tables (deployed before Alembic
was introduced) but no epcr_alembic_version entries, this script stamps
the database to revision '022' so that 'alembic upgrade head' only runs
the new migrations (023+) rather than trying to re-create tables that
already exist.

Usage (typically via ECS task override before alembic upgrade head):
    python3 migrations/pre_stamp_if_untracked.py && alembic upgrade head
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import urllib.parse as _up

from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine


_LIBPQ_ONLY = {
    "sslmode", "sslcert", "sslkey", "sslrootcert", "sslcrl",
    "sslcompression", "channel_binding", "gssencmode", "target_session_attrs",
}

# Last migration that was deployed BEFORE Alembic version tracking was added.
# The production database has tables equivalent to this state.
_STAMP_TARGET = "022"

_VERSION_TABLE = os.environ.get("EPCR_ALEMBIC_VERSION_TABLE", "epcr_alembic_version")


def _normalize_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    p = _up.urlparse(url)
    qs = _up.parse_qs(p.query, keep_blank_values=True)
    qs2 = {k: v for k, v in qs.items() if k not in _LIBPQ_ONLY}
    return _up.urlunparse(p._replace(query=_up.urlencode({k: v[0] for k, v in qs2.items()})))


async def _check_and_stamp() -> None:
    raw_url = (
        os.environ.get("EPCR_DATABASE_URL")
        or os.environ.get("CARE_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
    )
    if not raw_url:
        print("pre_stamp: no DB URL env var found — skipping", flush=True)
        return

    url = _normalize_url(raw_url)
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as conn:
            # Check whether epcr_alembic_version exists and has entries.
            ver_count = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM information_schema.tables "
                        f"WHERE table_schema = current_schema() AND table_name = '{_VERSION_TABLE}'"
                    )
                )
            ).scalar_one()

            if ver_count > 0:
                rows = (await conn.execute(text(f"SELECT version_num FROM {_VERSION_TABLE}"))).fetchall()
                if rows:
                    print(
                        f"pre_stamp: version table has {len(rows)} entr(ies) — "
                        f"no stamp needed ({[r[0] for r in rows]})",
                        flush=True,
                    )
                    return

            # Version table missing or empty. Check if core tables exist.
            charts_count = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM information_schema.tables "
                        "WHERE table_schema = current_schema() AND table_name = 'epcr_charts'"
                    )
                )
            ).scalar_one()

            if charts_count == 0:
                print("pre_stamp: fresh database — no stamp needed", flush=True)
                return

            print(
                f"pre_stamp: epcr_charts exists but {_VERSION_TABLE} is empty; "
                f"stamping to {_STAMP_TARGET!r} so upgrade only runs new migrations",
                flush=True,
            )
    finally:
        await engine.dispose()

    result = subprocess.run(
        ["alembic", "stamp", _STAMP_TARGET],
        capture_output=False,
    )
    if result.returncode != 0:
        print(f"pre_stamp: 'alembic stamp {_STAMP_TARGET}' failed with exit {result.returncode}", flush=True)
        sys.exit(result.returncode)

    print(f"pre_stamp: stamped to {_STAMP_TARGET!r} — ready for upgrade", flush=True)


if __name__ == "__main__":
    asyncio.run(_check_and_stamp())
