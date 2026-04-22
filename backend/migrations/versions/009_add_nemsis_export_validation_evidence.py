"""Add deterministic validator evidence to NEMSIS export attempts.

Revision ID: 009
Revises: 008
Create Date: 2026-04-21
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add validator evidence columns to export attempts."""
    op.add_column("epcr_nemsis_export_attempts", sa.Column("xsd_valid", sa.Boolean(), nullable=True))
    op.add_column("epcr_nemsis_export_attempts", sa.Column("schematron_valid", sa.Boolean(), nullable=True))
    op.add_column(
        "epcr_nemsis_export_attempts",
        sa.Column("validator_errors", sa.JSON() if hasattr(sa, "JSON") else sa.Text(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "epcr_nemsis_export_attempts",
        sa.Column("validator_warnings", sa.JSON() if hasattr(sa, "JSON") else sa.Text(), nullable=False, server_default="[]"),
    )
    op.add_column("epcr_nemsis_export_attempts", sa.Column("validator_asset_version", sa.Text(), nullable=True))


def downgrade() -> None:
    """Remove validator evidence columns from export attempts."""
    op.drop_column("epcr_nemsis_export_attempts", "validator_asset_version")
    op.drop_column("epcr_nemsis_export_attempts", "validator_warnings")
    op.drop_column("epcr_nemsis_export_attempts", "validator_errors")
    op.drop_column("epcr_nemsis_export_attempts", "schematron_valid")
    op.drop_column("epcr_nemsis_export_attempts", "xsd_valid")