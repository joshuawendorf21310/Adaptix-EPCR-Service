"""NEMSIS eMedications additions ORM models.

Backs the ``epcr_medication_admin_ext`` (1:1) and
``epcr_medication_complications`` (1:M) tables created by migration
``038``. These tables extend the existing
:class:`epcr_app.models.MedicationAdministration` row with NEMSIS
v3.5.1 eMedications elements that the legacy model does not capture.

The existing ``MedicationAdministration`` model already covers:

    eMedications.01 / .03 / .04 / .05 / .06 / .07 / .09

These extension tables add the remaining NEMSIS v3.5.1 eMedications
elements as a per-medication-row aggregate:

    eMedications.02  Medication Administered Prior to this Unit's EMS
                     Care Indicator
    eMedications.08  Medication Complication (1:M repeating group)
    eMedications.10  EMS Professional Type Providing Medication
    eMedications.11  Medication Authorization
    eMedications.12  Medication Authorizing Physician (last/first name)
    eMedications.13  Medication Administered by Another Unit Indicator

The extension is keyed by ``medication_admin_id`` so the existing
``MedicationAdministration`` row is never modified.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship

from epcr_app.models import Base


class MedicationAdminExt(Base):
    """NEMSIS eMedications 1:1 extension for a MedicationAdministration row.

    All NEMSIS-additive columns are nullable. The chart-finalization
    gate enforces NEMSIS Required-at-National elements (eMedications.02
    and eMedications.10) via the registry-driven validator, not in the
    ORM layer.
    """

    __tablename__ = "epcr_medication_admin_ext"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "medication_admin_id",
            name="uq_epcr_medication_admin_ext_tenant_med",
        ),
    )

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    chart_id = Column(
        String(36),
        ForeignKey("epcr_charts.id"),
        nullable=False,
        index=True,
    )
    medication_admin_id = Column(
        String(36),
        ForeignKey("epcr_medication_administrations.id"),
        nullable=False,
        unique=True,
        index=True,
    )

    # eMedications.02 — Medication Administered Prior to EMS Indicator
    prior_to_ems_indicator_code = Column(String(16), nullable=True)
    # eMedications.10 — EMS Professional Type Providing Medication
    ems_professional_type_code = Column(String(16), nullable=True)
    # eMedications.11 — Medication Authorization
    authorization_code = Column(String(16), nullable=True)
    # eMedications.12 — Medication Authorizing Physician (structured name)
    authorizing_physician_last_name = Column(String(120), nullable=True)
    authorizing_physician_first_name = Column(String(120), nullable=True)
    # eMedications.13 — Medication Administered by Another Unit Indicator
    by_another_unit_indicator_code = Column(String(16), nullable=True)

    created_by_user_id = Column(String(64), nullable=True)
    updated_by_user_id = Column(String(64), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    chart = relationship("Chart", foreign_keys=[chart_id])


class MedicationComplication(Base):
    """NEMSIS eMedications.08 Medication Complication (1:M repeating).

    Each row records one complication code observed against a specific
    MedicationAdministration. NEMSIS marks eMedications.08 as
    Required-at-National with 1:M cardinality, so this is a separate
    repeating-group child of the medication row.
    """

    __tablename__ = "epcr_medication_complications"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "medication_admin_id",
            "complication_code",
            name="uq_epcr_medication_complications_tenant_med_code",
        ),
    )

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    chart_id = Column(
        String(36),
        ForeignKey("epcr_charts.id"),
        nullable=False,
        index=True,
    )
    medication_admin_id = Column(
        String(36),
        ForeignKey("epcr_medication_administrations.id"),
        nullable=False,
        index=True,
    )
    complication_code = Column(String(16), nullable=False)
    sequence_index = Column(Integer, nullable=False, server_default=text("0"))

    created_by_user_id = Column(String(64), nullable=True)
    updated_by_user_id = Column(String(64), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    chart = relationship("Chart", foreign_keys=[chart_id])


__all__ = ["MedicationAdminExt", "MedicationComplication"]
