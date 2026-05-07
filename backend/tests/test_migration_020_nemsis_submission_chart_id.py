"""Schema regression for migration 020.

Migration 020 relaxes `nemsis_submission_results.chart_id` so TAC
compliance scenario submissions (which have no real `epcr_charts.id`)
can persist without violating the FK that migration 004 originally
created. It also introduces a `scenario_code` column so scenario
provenance is captured authoritatively.

This test asserts, against a fresh sqlite DB upgraded through migration
020, that:

  * `nemsis_submission_results.chart_id` is nullable.
  * No FK from `nemsis_submission_results.chart_id` to `epcr_charts.id`
    remains.
  * `scenario_code` column exists.
  * `ix_nemsis_submission_results_scenario_code` index exists.
  * Re-running `upgrade 020` is idempotent.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config


REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

TABLE = "nemsis_submission_results"


@pytest.fixture
def fresh_sqlite_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_file = tmp_path / "alembic_020.db"
    url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    monkeypatch.setenv("EPCR_DATABASE_URL", url)
    monkeypatch.delenv("CARE_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    return db_file


def _alembic_config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    return cfg


def test_migration_020_relaxes_chart_id_and_adds_scenario_code(
    fresh_sqlite_db: Path,
) -> None:
    cfg = _alembic_config()
    command.upgrade(cfg, "020")

    sync_url = f"sqlite:///{fresh_sqlite_db.as_posix()}"
    engine = sa.create_engine(sync_url)
    try:
        insp = sa.inspect(engine)

        cols = {c["name"]: c for c in insp.get_columns(TABLE)}
        assert "chart_id" in cols, "chart_id must still exist"
        assert cols["chart_id"]["nullable"] is True, (
            "migration 020 must make chart_id nullable for scenario submits"
        )
        assert "scenario_code" in cols, (
            "migration 020 must add scenario_code column"
        )
        assert cols["scenario_code"]["nullable"] is True

        fks = insp.get_foreign_keys(TABLE)
        for fk in fks:
            if fk.get("referred_table") == "epcr_charts" and "chart_id" in (
                fk.get("constrained_columns") or []
            ):
                pytest.fail(
                    "migration 020 must drop the chart_id -> epcr_charts FK"
                )

        index_names = {ix["name"] for ix in insp.get_indexes(TABLE)}
        assert (
            "ix_nemsis_submission_results_scenario_code" in index_names
        ), "migration 020 must add scenario_code index"
    finally:
        engine.dispose()


def test_migration_020_is_idempotent(fresh_sqlite_db: Path) -> None:
    cfg = _alembic_config()
    command.upgrade(cfg, "020")
    command.upgrade(cfg, "020")
