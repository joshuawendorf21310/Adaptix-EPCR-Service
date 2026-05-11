"""NEMSIS eOutcome (chart hospital outcome linkage) ORM model.

Backs the ``epcr_chart_outcome`` table created by migration ``035``.
Represents the NEMSIS v3.5.1 eOutcome section as a 1:1 child aggregate
of :class:`Chart`. Every column is nullable because outcome data is
populated post-hoc from receiving-facility feedback and not every chart
will have any of these elements at all. The chart-finalization gate
enforces NEMSIS Required/Conditional subsets via the registry-driven
validator, not in the ORM layer.

NEMSIS element bindings (handled by :mod:`projection_chart_outcome`):

    emergency_department_disposition_code             -> eOutcome.01
    hospital_disposition_code                         -> eOutcome.02
    emergency_department_diagnosis_codes_json         -> eOutcome.03 (1:M)
    hospital_admission_diagnosis_codes_json           -> eOutcome.04 (1:M)
    hospital_procedures_performed_codes_json          -> eOutcome.05 (1:M)
    trauma_registry_incident_id                       -> eOutcome.06
    hospital_outcome_at_discharge_code                -> eOutcome.07
    patient_disposition_from_emergency_department_at  -> eOutcome.08
    emergency_department_arrival_at                   -> eOutcome.09
    emergency_department_admit_at                     -> eOutcome.10
    emergency_department_discharge_at                 -> eOutcome.11
    hospital_admit_at                                 -> eOutcome.12
    hospital_discharge_at                             -> eOutcome.13
    icu_admit_at                                      -> eOutcome.14
    icu_discharge_at                                  -> eOutcome.15
    hospital_length_of_stay_days                      -> eOutcome.16
    icu_length_of_stay_days                           -> eOutcome.17
    final_patient_acuity_code                         -> eOutcome.18
    cause_of_death_codes_json                         -> eOutcome.19 (1:M)
    date_of_death                                     -> eOutcome.20
    medical_record_number                             -> eOutcome.21
    receiving_facility_record_number                  -> eOutcome.22
    referred_to_facility_code                         -> eOutcome.23
    referred_to_facility_name                         -> eOutcome.24

The four 1:M JSON list columns (diagnoses, procedures, causes of
death) are projected as repeating-group occurrences (one ledger row
per list entry) so the NEMSIS dataset XML builder can emit each
element occurrence separately.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)

from epcr_app.models import Base


class ChartOutcome(Base):
    """NEMSIS eOutcome 1:1 aggregate for a chart.

    All columns are nullable; outcome data is populated post-hoc from
    receiving-facility feedback. The chart-finalization gate enforces
    NEMSIS Required/Conditional subsets via the registry-driven
    validator.

    The four ``*_codes_json`` columns hold JSON arrays of NEMSIS-coded
    values (1:M repeating-group lists). The projection layer expands
    each list entry into one ledger row.
    """

    __tablename__ = "epcr_chart_outcome"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "chart_id",
            name="uq_epcr_chart_outcome_tenant_chart",
        ),
    )

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    chart_id = Column(
        String(36),
        ForeignKey("epcr_charts.id"),
        nullable=False,
        unique=True,
        index=True,
    )

    # eOutcome.01..24 in NEMSIS-canonical order
    emergency_department_disposition_code = Column(String(16), nullable=True)
    hospital_disposition_code = Column(String(16), nullable=True)
    emergency_department_diagnosis_codes_json = Column(JSON, nullable=True)
    hospital_admission_diagnosis_codes_json = Column(JSON, nullable=True)
    hospital_procedures_performed_codes_json = Column(JSON, nullable=True)
    trauma_registry_incident_id = Column(String(64), nullable=True)
    hospital_outcome_at_discharge_code = Column(String(16), nullable=True)
    patient_disposition_from_emergency_department_at = Column(String(255), nullable=True)
    emergency_department_arrival_at = Column(DateTime(timezone=True), nullable=True)
    emergency_department_admit_at = Column(DateTime(timezone=True), nullable=True)
    emergency_department_discharge_at = Column(DateTime(timezone=True), nullable=True)
    hospital_admit_at = Column(DateTime(timezone=True), nullable=True)
    hospital_discharge_at = Column(DateTime(timezone=True), nullable=True)
    icu_admit_at = Column(DateTime(timezone=True), nullable=True)
    icu_discharge_at = Column(DateTime(timezone=True), nullable=True)
    hospital_length_of_stay_days = Column(Integer, nullable=True)
    icu_length_of_stay_days = Column(Integer, nullable=True)
    final_patient_acuity_code = Column(String(16), nullable=True)
    cause_of_death_codes_json = Column(JSON, nullable=True)
    date_of_death = Column(DateTime(timezone=True), nullable=True)
    medical_record_number = Column(String(64), nullable=True)
    receiving_facility_record_number = Column(String(64), nullable=True)
    referred_to_facility_code = Column(String(64), nullable=True)
    referred_to_facility_name = Column(String(255), nullable=True)

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


__all__ = ["ChartOutcome"]
