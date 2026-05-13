"""057 fix nemsis_cs_scenarios unique constraint to be tenant-scoped.

Revision ID: 057
Revises: 056
Create Date: 2026-05-13

The nemsis_cs_scenarios_scenario_code_key constraint was on scenario_code
alone, which caused UniqueViolationError when multiple tenants submitted
the same scenario. Replace with a composite unique constraint on
(tenant_id, scenario_code).
"""

from __future__ import annotations

from alembic import op

revision = "057"
down_revision = "056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "nemsis_cs_scenarios_scenario_code_key",
        "nemsis_cs_scenarios",
        type_="unique",
    )
    op.create_unique_constraint(
        "nemsis_cs_scenarios_tenant_scenario_key",
        "nemsis_cs_scenarios",
        ["tenant_id", "scenario_code"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "nemsis_cs_scenarios_tenant_scenario_key",
        "nemsis_cs_scenarios",
        type_="unique",
    )
    op.create_unique_constraint(
        "nemsis_cs_scenarios_scenario_code_key",
        "nemsis_cs_scenarios",
        ["scenario_code"],
    )
