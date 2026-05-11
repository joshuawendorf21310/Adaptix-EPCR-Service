"""Schema regression for migration 021.

Migration 021 introduces ``epcr_nemsis_field_values`` for row-per-occurrence
NEMSIS persistence. This test asserts, against a fresh sqlite DB
upgraded through migration 021, that:

  * Table exists with all required columns.
  * Three covering indexes exist.
  * Uniqueness key spans (tenant_id, chart_id, element_number,
    group_path, occurrence_id) — NOT (chart_id, element_number) alone,
    so repeating groups can persist many rows for the same element.
  * Two rows with the same (chart_id, element_number) but different
    occurrence_id values can coexist (repeating-group truth).
  * Re-upserting the same occurrence triggers the unique constraint.
  * Re-running ``upgrade 021`` is idempotent.
  * Downgrade drops the table.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config


REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

TABLE = "epcr_nemsis_field_values"


@pytest.fixture
def fresh_sqlite_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_file = tmp_path / "alembic_021.db"
    url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    monkeypatch.setenv("EPCR_DATABASE_URL", url)
    monkeypatch.delenv("CARE_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    return db_file


def _alembic_config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    return cfg


def test_migration_021_creates_field_values_table(fresh_sqlite_db: Path) -> None:
    cfg = _alembic_config()
    command.upgrade(cfg, "021")

    sync_url = f"sqlite:///{fresh_sqlite_db.as_posix()}"
    engine = sa.create_engine(sync_url)
    try:
        insp = sa.inspect(engine)
        assert insp.has_table(TABLE), f"{TABLE} not created"

        cols = {c["name"] for c in insp.get_columns(TABLE)}
        required = {
            "id",
            "tenant_id",
            "chart_id",
            "section",
            "element_number",
            "element_name",
            "group_path",
            "occurrence_id",
            "sequence_index",
            "value_json",
            "attributes_json",
            "source",
            "validation_status",
            "validation_issues_json",
            "created_by_user_id",
            "updated_by_user_id",
            "created_at",
            "updated_at",
            "deleted_at",
        }
        missing = required - cols
        assert not missing, f"missing columns: {missing}"

        idx_names = {ix["name"] for ix in insp.get_indexes(TABLE)}
        assert "idx_epcr_nemsis_field_values_tenant_chart" in idx_names
        assert "idx_epcr_nemsis_field_values_element" in idx_names
        assert "idx_epcr_nemsis_field_values_group" in idx_names

        # Uniqueness key must span the full occurrence identity, NOT
        # just (chart_id, element_number) which would break repeating groups.
        uqs = insp.get_unique_constraints(TABLE)
        names = {uq["name"] for uq in uqs}
        assert "uq_epcr_nemsis_field_values_occurrence" in names
        target = next(
            uq for uq in uqs if uq["name"] == "uq_epcr_nemsis_field_values_occurrence"
        )
        assert set(target["column_names"]) == {
            "tenant_id",
            "chart_id",
            "element_number",
            "group_path",
            "occurrence_id",
        }
    finally:
        engine.dispose()


def test_migration_021_repeating_group_rows_coexist(fresh_sqlite_db: Path) -> None:
    cfg = _alembic_config()
    command.upgrade(cfg, "021")

    sync_url = f"sqlite:///{fresh_sqlite_db.as_posix()}"
    engine = sa.create_engine(sync_url)
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    f"INSERT INTO {TABLE} "
                    "(id, tenant_id, chart_id, section, element_number, "
                    "element_name, group_path, occurrence_id, sequence_index, "
                    "attributes_json, source, validation_status, validation_issues_json, "
                    "created_at, updated_at) "
                    "VALUES (:id, :t, :c, :s, :en, :nm, :gp, :oc, :si, :a, :src, :vs, :vi, :ca, :ua)"
                ),
                {
                    "id": "row-1",
                    "t": "tenant-A",
                    "c": "chart-1",
                    "s": "EMS",
                    "en": "eVitals.01",
                    "nm": "VitalSignsTakenDateTime",
                    "gp": "eVitals",
                    "oc": "occ-1",
                    "si": 0,
                    "a": "{}",
                    "src": "manual",
                    "vs": "unvalidated",
                    "vi": "[]",
                    "ca": "2026-05-09T00:00:00+00:00",
                    "ua": "2026-05-09T00:00:00+00:00",
                },
            )
            # Same chart + same element_number, different occurrence_id -> MUST succeed.
            conn.execute(
                sa.text(
                    f"INSERT INTO {TABLE} "
                    "(id, tenant_id, chart_id, section, element_number, "
                    "element_name, group_path, occurrence_id, sequence_index, "
                    "attributes_json, source, validation_status, validation_issues_json, "
                    "created_at, updated_at) "
                    "VALUES (:id, :t, :c, :s, :en, :nm, :gp, :oc, :si, :a, :src, :vs, :vi, :ca, :ua)"
                ),
                {
                    "id": "row-2",
                    "t": "tenant-A",
                    "c": "chart-1",
                    "s": "EMS",
                    "en": "eVitals.01",
                    "nm": "VitalSignsTakenDateTime",
                    "gp": "eVitals",
                    "oc": "occ-2",
                    "si": 1,
                    "a": "{}",
                    "src": "manual",
                    "vs": "unvalidated",
                    "vi": "[]",
                    "ca": "2026-05-09T00:00:00+00:00",
                    "ua": "2026-05-09T00:00:00+00:00",
                },
            )

        with engine.connect() as conn:
            count = conn.execute(
                sa.text(f"SELECT COUNT(*) FROM {TABLE} WHERE chart_id = 'chart-1'")
            ).scalar()
            assert count == 2

        # Re-inserting with the same occurrence identity MUST violate uniqueness.
        with pytest.raises(sa.exc.IntegrityError):
            with engine.begin() as conn:
                conn.execute(
                    sa.text(
                        f"INSERT INTO {TABLE} "
                        "(id, tenant_id, chart_id, section, element_number, "
                        "element_name, group_path, occurrence_id, sequence_index, "
                        "attributes_json, source, validation_status, validation_issues_json, "
                        "created_at, updated_at) "
                        "VALUES (:id, :t, :c, :s, :en, :nm, :gp, :oc, :si, :a, :src, :vs, :vi, :ca, :ua)"
                    ),
                    {
                        "id": "row-3",
                        "t": "tenant-A",
                        "c": "chart-1",
                        "s": "EMS",
                        "en": "eVitals.01",
                        "nm": "VitalSignsTakenDateTime",
                        "gp": "eVitals",
                        "oc": "occ-1",  # duplicate occurrence
                        "si": 2,
                        "a": "{}",
                        "src": "manual",
                        "vs": "unvalidated",
                        "vi": "[]",
                        "ca": "2026-05-09T00:00:00+00:00",
                        "ua": "2026-05-09T00:00:00+00:00",
                    },
                )
    finally:
        engine.dispose()


def test_migration_021_is_idempotent(fresh_sqlite_db: Path) -> None:
    cfg = _alembic_config()
    command.upgrade(cfg, "021")
    # Second invocation through the head must be a no-op.
    command.upgrade(cfg, "head")

    sync_url = f"sqlite:///{fresh_sqlite_db.as_posix()}"
    engine = sa.create_engine(sync_url)
    try:
        insp = sa.inspect(engine)
        assert insp.has_table(TABLE)
    finally:
        engine.dispose()


def test_migration_021_downgrade_drops_table(fresh_sqlite_db: Path) -> None:
    cfg = _alembic_config()
    command.upgrade(cfg, "021")

    sync_url = f"sqlite:///{fresh_sqlite_db.as_posix()}"
    engine = sa.create_engine(sync_url)
    try:
        insp = sa.inspect(engine)
        assert insp.has_table(TABLE)
    finally:
        engine.dispose()

    command.downgrade(cfg, "-1")

    engine = sa.create_engine(sync_url)
    try:
        insp = sa.inspect(engine)
        assert not insp.has_table(TABLE)
    finally:
        engine.dispose()
