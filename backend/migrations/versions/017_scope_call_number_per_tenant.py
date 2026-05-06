"""017 scope epcr_charts.call_number uniqueness by tenant

Revision ID: 017_chart_call_number_tenant_scope
Revises: 016_add_smart_text_finding_methods
Create Date: 2026-05-06

The original `epcr_charts.call_number` column was created with a global
UNIQUE constraint (auto-named `epcr_charts_call_number_key` by
PostgreSQL). That constraint is wrong for a multi-tenant chart store:
it allows a single tenant collision to surface across the whole
deployment, and it causes legitimate cross-tenant call numbers to be
rejected with `IntegrityError` -> 500 in the API.

This migration:
  1. Drops the global UNIQUE constraint on `call_number` (using
     introspection to find the actual constraint name, since older
     environments may have a non-default name).
  2. Adds a composite UNIQUE constraint on `(tenant_id, call_number)`
     named `uq_epcr_charts_tenant_call_number`.

Idempotent + drift-safe: each step verifies the constraint exists or
does not exist before acting.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


TABLE = "epcr_charts"
NEW_CONSTRAINT = "uq_epcr_charts_tenant_call_number"
LEGACY_CONSTRAINT = "epcr_charts_call_number_key"


def _global_unique_constraint_names(insp) -> list[str]:
    """Return all UNIQUE constraints on `epcr_charts` that cover only
    `call_number`."""
    if not insp.has_table(TABLE):
        return []
    out: list[str] = []
    for uc in insp.get_unique_constraints(TABLE):
        cols = [c for c in uc.get("column_names") or []]
        if cols == ["call_number"]:
            name = uc.get("name") or LEGACY_CONSTRAINT
            out.append(name)
    return out


def _composite_constraint_exists(insp) -> bool:
    if not insp.has_table(TABLE):
        return False
    for uc in insp.get_unique_constraints(TABLE):
        cols = list(uc.get("column_names") or [])
        if sorted(cols) == sorted(["tenant_id", "call_number"]):
            return True
    return False


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table(TABLE):
        return

    legacy_names = _global_unique_constraint_names(insp)
    composite_already = _composite_constraint_exists(insp)

    if not legacy_names and composite_already:
        return  # already migrated

    # Use batch_alter_table so this works on both SQLite (test/dev) and
    # PostgreSQL (production). On PostgreSQL batch mode is a no-op
    # passthrough; on SQLite it does the copy-and-move strategy required
    # for constraint ALTER.
    with op.batch_alter_table(TABLE) as batch_op:
        for name in legacy_names:
            batch_op.drop_constraint(name, type_="unique")
        if not composite_already:
            batch_op.create_unique_constraint(
                NEW_CONSTRAINT,
                ["tenant_id", "call_number"],
            )

    # Defensive: drop any leftover plain unique index on `call_number`
    # that survived (some PostgreSQL deployments may have a separate
    # index in addition to the constraint).
    insp = sa.inspect(bind)
    for ix in insp.get_indexes(TABLE):
        if (
            ix.get("unique")
            and list(ix.get("column_names") or []) == ["call_number"]
            and ix.get("name")
        ):
            try:
                op.drop_index(ix["name"], table_name=TABLE)
            except Exception:
                pass


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table(TABLE):
        return

    composite_present = _composite_constraint_exists(insp)
    legacy_present = bool(_global_unique_constraint_names(insp))

    if not composite_present and legacy_present:
        return

    with op.batch_alter_table(TABLE) as batch_op:
        if composite_present:
            batch_op.drop_constraint(NEW_CONSTRAINT, type_="unique")
        if not legacy_present:
            batch_op.create_unique_constraint(
                LEGACY_CONSTRAINT,
                ["call_number"],
            )
