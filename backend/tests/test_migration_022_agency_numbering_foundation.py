"""Schema regression for migration 022 agency numbering foundation."""
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
    db_file = tmp_path / "alembic_022.db"
    url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    monkeypatch.setenv("EPCR_DATABASE_URL", url)
    monkeypatch.delenv("CARE_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    return db_file


def _alembic_config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    return cfg


def test_migration_022_adds_agency_numbering_foundation(fresh_sqlite_db: Path) -> None:
    cfg = _alembic_config()
    command.upgrade(cfg, "022")

    engine = sa.create_engine(f"sqlite:///{fresh_sqlite_db.as_posix()}")
    try:
        insp = sa.inspect(engine)
        tables = set(insp.get_table_names())
        assert "agency_profiles" in tables
        assert "epcr_numbering_sequences" in tables
        assert "epcr_charts" in tables

        agency_cols = {col["name"] for col in insp.get_columns("agency_profiles")}
        assert {"tenant_id", "agency_code", "agency_name", "numbering_policy_json", "activated_at"}.issubset(agency_cols)

        sequence_cols = {col["name"] for col in insp.get_columns("epcr_numbering_sequences")}
        assert {"tenant_id", "agency_code", "sequence_year", "next_incident_sequence"}.issubset(sequence_cols)

        chart_cols = {col["name"] for col in insp.get_columns("epcr_charts")}
        assert {
            "agency_code",
            "incident_year",
            "incident_sequence",
            "response_sequence",
            "pcr_sequence",
            "billing_sequence",
            "incident_number",
            "response_number",
            "pcr_number",
            "billing_case_number",
            "cad_incident_number",
            "external_incident_number",
        }.issubset(chart_cols)

        index_names = {ix["name"] for ix in insp.get_indexes("epcr_charts")}
        assert "uq_epcr_charts_incident_number" in index_names
        assert "uq_epcr_charts_response_number" in index_names
        assert "uq_epcr_charts_pcr_number" in index_names
        assert "uq_epcr_charts_billing_case_number" in index_names
    finally:
        engine.dispose()


def test_migration_022_is_idempotent(fresh_sqlite_db: Path) -> None:
    cfg = _alembic_config()
    command.upgrade(cfg, "022")
    command.upgrade(cfg, "022")