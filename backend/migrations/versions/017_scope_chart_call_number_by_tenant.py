"""Scope ePCR chart call_number uniqueness by tenant.

Revision ID: 017
Revises: 016
Create Date: 2026-05-06

The chart workspace create path is tenant-scoped. A globally unique
``epcr_charts.call_number`` blocks valid cross-tenant call numbers and can
surface as HTTP 500 when the database raises an IntegrityError. This
migration removes any single-column unique constraint/index on
``call_number`` and creates an explicit tenant-scoped unique constraint.

The migration is drift-tolerant: it inspects live PostgreSQL constraints
and indexes instead of assuming the generated constraint name.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


TABLE_NAME = "epcr_charts"
SCOPED_CONSTRAINT = "uq_epcr_charts_tenant_call_number"


def _unique_constraints_for_columns(insp: sa.Inspector, columns: list[str]) -> list[str]:
    matches: list[str] = []
    for constraint in insp.get_unique_constraints(TABLE_NAME):
        if constraint.get("column_names") == columns and constraint.get("name"):
            matches.append(str(constraint["name"]))
    return matches


def _unique_indexes_for_columns(insp: sa.Inspector, columns: list[str]) -> list[str]:
    matches: list[str] = []
    for index in insp.get_indexes(TABLE_NAME):
        if index.get("unique") and index.get("column_names") == columns and index.get("name"):
            matches.append(str(index["name"]))
    return matches


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(TABLE_NAME):
        return

    for name in _unique_constraints_for_columns(insp, ["call_number"]):
        op.drop_constraint(name, TABLE_NAME, type_="unique")

    # Some PostgreSQL schemas expose a column-level unique=True artifact as
    # a unique index instead of a named unique constraint. Drop only indexes
    # that are unique on call_number alone; keep the normal non-unique index.
    for name in _unique_indexes_for_columns(insp, ["call_number"]):
        op.drop_index(name, table_name=TABLE_NAME)

    scoped_exists = bool(_unique_constraints_for_columns(insp, ["tenant_id", "call_number"]))
    if not scoped_exists:
        op.create_unique_constraint(
            SCOPED_CONSTRAINT,
            TABLE_NAME,
            ["tenant_id", "call_number"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(TABLE_NAME):
        return

    for name in _unique_constraints_for_columns(insp, ["tenant_id", "call_number"]):
        op.drop_constraint(name, TABLE_NAME, type_="unique")

    global_exists = bool(_unique_constraints_for_columns(insp, ["call_number"]))
    if not global_exists:
        op.create_unique_constraint(
            "uq_epcr_charts_call_number",
            TABLE_NAME,
            ["call_number"],
        )
