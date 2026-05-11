"""Schema regression for migration 023 patient registry foundation."""
from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config


REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


@pytest.fixture
def fresh_sqlite_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_file = tmp_path / "alembic_023.db"
    url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    monkeypatch.setenv("EPCR_DATABASE_URL", url)
    monkeypatch.delenv("CARE_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    return db_file


def _alembic_config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    return cfg


def test_migration_023_adds_patient_registry_foundation(fresh_sqlite_db: Path) -> None:
    cfg = _alembic_config()
    command.upgrade(cfg, "023")

    engine = sa.create_engine(f"sqlite:///{fresh_sqlite_db.as_posix()}")
    try:
        insp = sa.inspect(engine)
        tables = set(insp.get_table_names())
        assert {
            "patient_registry_profiles",
            "patient_registry_identifiers",
            "patient_registry_chart_links",
            "epcr_charting_accelerator_imports",
            "patient_registry_merge_candidates",
            "patient_registry_merge_audit",
            "patient_registry_aliases",
        }.issubset(tables)

        profile_cols = {col["name"] for col in insp.get_columns("patient_registry_profiles")}
        assert {
            "tenant_id",
            "canonical_patient_key",
            "first_name_norm",
            "last_name_norm",
            "primary_phone_hash",
            "merged_into_patient_id",
        }.issubset(profile_cols)

        identifier_cols = {col["name"] for col in insp.get_columns("patient_registry_identifiers")}
        assert {
            "patient_registry_profile_id",
            "identifier_type",
            "identifier_hash",
            "identifier_last4",
            "source_chart_id",
        }.issubset(identifier_cols)

        link_cols = {col["name"] for col in insp.get_columns("patient_registry_chart_links")}
        assert {"patient_registry_profile_id", "chart_id", "link_status", "confidence_status"}.issubset(link_cols)
    finally:
        engine.dispose()


def test_migration_023_is_idempotent(fresh_sqlite_db: Path) -> None:
    cfg = _alembic_config()
    command.upgrade(cfg, "023")
    command.upgrade(cfg, "023")