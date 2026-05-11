"""040 merge — unify the 16 NEMSIS v3.5.1 vertical-slice branches.

Revision ID: 040
Revises: 024, 025, 026, 027, 028, 029, 030, 031, 032, 033, 034, 035, 036, 037, 038, 039
Create Date: 2026-05-10

Each slice migration (024 eTimes, 025 eDispatch, 026 eCrew, 027 eResponse
meta + delays, 028 eScene, 029 eSituation, 030 eHistory, 031 eInjury +
ACN, 032 eArrest, 033 eDisposition, 034 ePayment, 035 eOutcome, 036
patient_profile_ext, 037 vitals_ext, 038 medication_admin_ext, 039
intervention_ext) was authored with ``down_revision = "023"`` so the
slices could be developed in parallel without head conflicts.

This migration fans them back into a single head by declaring a tuple
``down_revision`` containing all sixteen slice revisions. Alembic
expresses this in DAG form. No new schema is created here — it is a
pure merge.
"""
from __future__ import annotations


revision = "040"
down_revision = (
    "024",
    "025",
    "026",
    "027",
    "028",
    "029",
    "030",
    "031",
    "032",
    "033",
    "034",
    "035",
    "036",
    "037",
    "038",
    "039",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No schema changes — the per-slice migrations already ran."""


def downgrade() -> None:
    """No schema changes to reverse."""
