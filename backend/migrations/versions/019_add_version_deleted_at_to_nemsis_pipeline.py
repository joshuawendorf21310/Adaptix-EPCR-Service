"""019 add version + deleted_at to NEMSIS submission pipeline tables

Revision ID: 019
Revises: 017
Create Date: 2026-05-07

(Migration file 018 exists in the local working tree but is not yet
committed to the repository; the deployed migration chain therefore
ends at 017. This migration chains directly off 017 so the production
container's bundled migrations resolve cleanly. When 018 lands later,
its `down_revision` should be updated to chain after 019, or 019's
`down_revision` revisited as part of that change set.)

Migration 004 created the four NEMSIS submission pipeline tables
(`nemsis_resource_packs`, `nemsis_pack_files`, `nemsis_submission_results`,
`nemsis_submission_status_history`, `nemsis_cs_scenarios`) without the
`version` (Integer NOT NULL DEFAULT 1) and `deleted_at` (timestamptz NULL)
columns that the ORM in ``epcr_app.models_nemsis_core`` declares.

Migration 013 fixed the same drift for chart-scoped tables but did not
cover the NEMSIS pipeline tables. As a result, every authenticated call
to ``POST /api/v1/epcr/nemsis/scenarios/{id}/submit`` (and any list/get
that touches ``NemsisScenario``) crashes in production with::

    asyncpg.exceptions.UndefinedColumnError:
    column nemsis_cs_scenarios.version does not exist

This migration introspects each table and adds only the columns that are
actually missing (idempotent + drift-safe), matching the conventions used
by migration 013.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "019"
down_revision = "017"
branch_labels = None
depends_on = None


NEMSIS_PIPELINE_TABLES = [
    "nemsis_resource_packs",
    "nemsis_pack_files",
    "nemsis_submission_results",
    "nemsis_submission_status_history",
    "nemsis_cs_scenarios",
]


def _ensure_column(insp, table: str, column_name: str, column: sa.Column) -> None:
    if not insp.has_table(table):
        return
    cols = {c["name"] for c in insp.get_columns(table)}
    if column_name in cols:
        return
    op.add_column(table, column)


def _drop_column_if_exists(insp, table: str, column_name: str) -> None:
    if not insp.has_table(table):
        return
    cols = {c["name"] for c in insp.get_columns(table)}
    if column_name not in cols:
        return
    op.drop_column(table, column_name)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    for table in NEMSIS_PIPELINE_TABLES:
        _ensure_column(
            insp,
            table,
            "version",
            sa.Column(
                "version",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            ),
        )
        _ensure_column(
            insp,
            table,
            "deleted_at",
            sa.Column(
                "deleted_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    for table in reversed(NEMSIS_PIPELINE_TABLES):
        _drop_column_if_exists(insp, table, "deleted_at")
        _drop_column_if_exists(insp, table, "version")
