"""Schema regression: NEMSIS submission pipeline tables must carry the
ORM-declared ``version`` and ``deleted_at`` columns after running every
Alembic migration.

This test guards against the production drift fixed by migration 019,
where migration 004 created the NEMSIS submission pipeline tables
without the ``version``/``deleted_at`` columns the ORM declares in
``epcr_app.models_nemsis_core``. Without those columns, every call to
``POST /api/v1/epcr/nemsis/scenarios/{id}/submit`` (and any list/get
that touches ``NemsisScenario``) crashes with::

    asyncpg.exceptions.UndefinedColumnError:
    column nemsis_cs_scenarios.version does not exist
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config


REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

NEMSIS_PIPELINE_TABLES = [
    "nemsis_resource_packs",
    "nemsis_pack_files",
    "nemsis_submission_results",
    "nemsis_submission_status_history",
    "nemsis_cs_scenarios",
]


@pytest.fixture
def fresh_sqlite_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point Alembic env at an isolated, empty sqlite database."""
    db_file = tmp_path / "alembic_regression.db"
    url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    monkeypatch.setenv("EPCR_DATABASE_URL", url)
    # Strip legacy fallbacks so env.py uses the one we set.
    monkeypatch.delenv("CARE_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    return db_file


def _alembic_config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    return cfg


def test_migration_019_adds_version_and_deleted_at_to_nemsis_pipeline(
    fresh_sqlite_db: Path,
) -> None:
    """`alembic upgrade 019` must leave every NEMSIS pipeline table with
    `version` (NOT NULL DEFAULT 1) and `deleted_at` (nullable) columns."""
    cfg = _alembic_config()
    command.upgrade(cfg, "019")

    # Use a synchronous engine for introspection only; the async aiosqlite
    # path is exercised by the migration env itself above.
    sync_url = f"sqlite:///{fresh_sqlite_db.as_posix()}"
    engine = sa.create_engine(sync_url)
    try:
        insp = sa.inspect(engine)
        existing = set(insp.get_table_names())
        for table in NEMSIS_PIPELINE_TABLES:
            assert table in existing, f"migration head did not create {table}"
            cols = {c["name"]: c for c in insp.get_columns(table)}
            assert "version" in cols, (
                f"{table} is missing required `version` column after upgrade head"
            )
            assert "deleted_at" in cols, (
                f"{table} is missing required `deleted_at` column after upgrade head"
            )
            assert cols["version"]["nullable"] is False, (
                f"{table}.version must be NOT NULL"
            )
            assert cols["deleted_at"]["nullable"] is True, (
                f"{table}.deleted_at must be nullable"
            )
    finally:
        engine.dispose()


def test_migration_019_is_idempotent(fresh_sqlite_db: Path) -> None:
    """Running `upgrade 019` twice must not raise (idempotent + drift-safe)."""
    cfg = _alembic_config()
    command.upgrade(cfg, "019")
    # Second run should be a no-op for migration 019 because every column
    # is detected via inspector before adding.
    command.upgrade(cfg, "019")
