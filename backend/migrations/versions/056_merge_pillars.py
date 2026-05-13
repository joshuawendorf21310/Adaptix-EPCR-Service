"""056 merge all 11 pillar heads off revision 043.

Revision ID: 056
Revises: 045, 046, 047, 048, 049, 050, 051, 052, 053, 054, 055
Create Date: 2026-05-12

Merge migration that linearises the 11 parallel heads produced by the
pillar agents (045–055) into a single head so that ``alembic upgrade
head`` and ``alembic downgrade -1`` function correctly on a fresh
database and on any existing deployment that has already applied some
or all of the parallel migrations.

No schema changes are performed; all DDL lives in the sibling revisions.
"""
from __future__ import annotations

from alembic import op  # noqa: F401  (imported for the Alembic env contract)


# revision identifiers, used by Alembic.
revision = "056"
down_revision = (
    "045",
    "046",
    "047",
    "048",
    "049",
    "050",
    "051",
    "052",
    "053",
    "054",
    "055",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op merge — all schema changes live in the sibling revisions."""
    pass


def downgrade() -> None:
    """No-op — downgrade is handled by reversing the sibling revisions."""
    pass
