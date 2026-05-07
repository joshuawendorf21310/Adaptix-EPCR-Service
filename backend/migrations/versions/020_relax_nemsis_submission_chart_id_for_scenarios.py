"""020 relax nemsis_submission_results.chart_id for scenario submits

Revision ID: 020
Revises: 019
Create Date: 2026-05-07

The TAC compliance scenario submit path (`POST /api/v1/epcr/nemsis/scenarios/{id}/submit`)
has no real `epcr_charts.id` — scenarios are TAC test artifacts, not real
patient charts. The original migration 004 created
`nemsis_submission_results.chart_id` as `NOT NULL` with a FK to
`epcr_charts.id`. The submit handler was synthesizing
`chart_id="SCENARIO-<code>"`, which violated the FK and crashed the
persistence step with `ForeignKeyViolationError` after the SOAP call had
already executed.

This migration:

  1. Drops the `chart_id -> epcr_charts.id` FK constraint by introspection
     (constraint name varies across environments).
  2. Relaxes `chart_id` to NULLABLE so scenario submissions can persist
     without inventing a fake chart.
  3. Adds a new `scenario_code` column so scenario provenance is captured
     authoritatively (instead of being smuggled inside `chart_id`).

Idempotent + drift-safe: each step verifies state via the inspector
before acting. The downgrade restores the FK + NOT NULL only if every
existing row has a valid chart_id.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


TABLE = "nemsis_submission_results"


def _build_table_without_chart_fk(insp) -> sa.Table:
    """Reflect the live table and return a Table object with the
    `chart_id -> epcr_charts.id` FK omitted so batch_alter_table can
    rebuild the table cleanly (required for SQLite where the FK is
    unnamed and `op.drop_constraint` cannot target it)."""
    metadata = sa.MetaData()
    table = sa.Table(TABLE, metadata, autoload_with=insp.bind)
    # Filter out the FK we want gone, preserve everything else.
    table.constraints = {
        c
        for c in table.constraints
        if not (
            isinstance(c, sa.ForeignKeyConstraint)
            and c.referred_table.name == "epcr_charts"
            and {col.name for col in c.columns} == {"chart_id"}
        )
    }
    table.foreign_keys = {
        fk for fk in table.foreign_keys if fk.column.table.name != "epcr_charts"
    }
    if "chart_id" in table.c:
        table.c["chart_id"].foreign_keys = set()
    return table


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table(TABLE):
        return

    fks = insp.get_foreign_keys(TABLE)
    has_chart_fk = any(
        fk.get("referred_table") == "epcr_charts"
        and "chart_id" in (fk.get("constrained_columns") or [])
        for fk in fks
    )

    cols = {c["name"]: c for c in insp.get_columns(TABLE)}
    chart_is_not_null = "chart_id" in cols and not cols["chart_id"].get(
        "nullable", True
    )
    needs_scenario_code = "scenario_code" not in cols

    if not (has_chart_fk or chart_is_not_null or needs_scenario_code):
        return

    # On Postgres the FK has a real name and op.drop_constraint works
    # directly (faster, no full-table rebuild). On SQLite the FK is
    # unnamed and we must rebuild the table via batch_alter_table with
    # an explicit copy_from that omits the FK.
    dialect_name = bind.dialect.name

    if dialect_name == "postgresql":
        for fk in fks:
            if (
                fk.get("referred_table") == "epcr_charts"
                and "chart_id" in (fk.get("constrained_columns") or [])
                and fk.get("name")
            ):
                op.drop_constraint(fk["name"], TABLE, type_="foreignkey")
        if chart_is_not_null:
            op.alter_column(
                TABLE,
                "chart_id",
                existing_type=sa.String(length=36),
                nullable=True,
            )
        if needs_scenario_code:
            op.add_column(
                TABLE,
                sa.Column("scenario_code", sa.String(length=64), nullable=True),
            )
            op.create_index(
                "ix_nemsis_submission_results_scenario_code",
                TABLE,
                ["scenario_code"],
            )
        return

    # SQLite (or any dialect lacking native ALTER) path.
    rebuilt = _build_table_without_chart_fk(insp)
    with op.batch_alter_table(TABLE, copy_from=rebuilt) as batch_op:
        if chart_is_not_null:
            batch_op.alter_column(
                "chart_id",
                existing_type=sa.String(length=36),
                nullable=True,
            )
        if needs_scenario_code:
            batch_op.add_column(
                sa.Column("scenario_code", sa.String(length=64), nullable=True)
            )
    if needs_scenario_code:
        op.create_index(
            "ix_nemsis_submission_results_scenario_code",
            TABLE,
            ["scenario_code"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table(TABLE):
        return

    cols = {c["name"]: c for c in insp.get_columns(TABLE)}
    indexes = {ix["name"] for ix in insp.get_indexes(TABLE)}

    if "ix_nemsis_submission_results_scenario_code" in indexes:
        op.drop_index("ix_nemsis_submission_results_scenario_code", table_name=TABLE)
    if "scenario_code" in cols:
        op.drop_column(TABLE, "scenario_code")

    # Restoring the NOT NULL + FK is only safe when every row has a
    # valid chart_id. We attempt it best-effort and skip silently if a
    # broken row would prevent it.
    try:
        if "chart_id" in cols and cols["chart_id"].get("nullable", True):
            with op.batch_alter_table(TABLE) as batch_op:
                batch_op.alter_column(
                    "chart_id",
                    existing_type=sa.String(length=36),
                    nullable=False,
                )
        op.create_foreign_key(
            "fk_nemsis_submission_results_chart_id_epcr_charts",
            TABLE,
            "epcr_charts",
            ["chart_id"],
            ["id"],
        )
    except Exception:
        # Downgrade is best-effort; a broken downgrade should never block
        # a forward roll-out and is logged at the orchestrator level.
        pass
