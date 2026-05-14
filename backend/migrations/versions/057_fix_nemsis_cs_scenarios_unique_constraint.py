"""057 fix nemsis_cs_scenarios unique constraint to be tenant-scoped.

Revision ID: 057
Revises: 056
Create Date: 2026-05-13

The original uniqueness was declared as a unique INDEX
(``ix_nemsis_cs_scenarios_scenario_code``) on ``scenario_code`` alone in
migration 004; that caused UniqueViolationError when multiple tenants
submitted the same scenario. Replace it with a composite unique index on
(tenant_id, scenario_code). The earlier revision of this file tried to
drop a UNIQUE constraint by name (``nemsis_cs_scenarios_scenario_code_key``)
that never existed — uniqueness was always implemented via an index — so
``upgrade head`` failed on both SQLite and Postgres.
"""

from __future__ import annotations

from alembic import op

revision = "057"
down_revision = "056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index(
        "ix_nemsis_cs_scenarios_scenario_code",
        table_name="nemsis_cs_scenarios",
    )
    op.create_index(
        "ix_nemsis_cs_scenarios_tenant_scenario_code",
        "nemsis_cs_scenarios",
        ["tenant_id", "scenario_code"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_nemsis_cs_scenarios_tenant_scenario_code",
        table_name="nemsis_cs_scenarios",
    )
    op.create_index(
        "ix_nemsis_cs_scenarios_scenario_code",
        "nemsis_cs_scenarios",
        ["scenario_code"],
        unique=True,
    )
