"""NEMSIS v3.5.1 eVitals extension ORM models.

The existing :class:`Vitals` table holds the 7 legacy vital-sign
measurements (BP, HR, RR, temp, SpO2, glucose). NEMSIS v3.5.1 eVitals
defines 27 additional elements (GCS components, AVPU, stroke scale,
ECG rhythm/interpretation, ETCO2, pain score, reperfusion checklist,
APGAR, RTS, ...). This module models those additional elements as a
per-vitals-row extension table (1:1 with each Vitals row), plus two
sibling child tables for the 1:M repeating groups:

    eVitals.22  GCS Qualifier                -> epcr_vitals_gcs_qualifiers
    eVitals.31  Reperfusion Checklist        -> epcr_vitals_reperfusion_checklist

The existing :class:`Vitals` table is OFF-LIMITS and is not modified.
Every column in :class:`VitalsNemsisExt` is nullable; the chart
finalization gate enforces the Required-at-National subset via the
registry-driven validator, not in the ORM layer.

Tenant isolation is enforced at every read/write by the service layer
filtering on ``tenant_id``. The unique constraint on
``(tenant_id, vitals_id)`` makes the 1:1 invariant a hard schema
guarantee.

NEMSIS element bindings (handled by :mod:`projection_vitals_ext`):

    obtained_prior_to_ems_code               -> eVitals.02  (Required)
    cardiac_rhythm_codes_json                -> eVitals.03  (1:M)
    ecg_type_code                            -> eVitals.04
    ecg_interpretation_method_codes_json     -> eVitals.05  (1:M)
    blood_pressure_method_code               -> eVitals.08
    mean_arterial_pressure                   -> eVitals.09
    heart_rate_method_code                   -> eVitals.11
    pulse_rhythm_code                        -> eVitals.13
    respiratory_effort_code                  -> eVitals.15  (Required)
    etco2                                    -> eVitals.16  (Required)
    carbon_monoxide_ppm                      -> eVitals.17
    gcs_eye_code                             -> eVitals.19  (Required)
    gcs_verbal_code                          -> eVitals.20  (Required)
    gcs_motor_code                           -> eVitals.21  (Required)
    gcs_qualifiers (child rows)              -> eVitals.22  (Required, 1:M)
    gcs_total                                -> eVitals.23
    temperature_method_code                  -> eVitals.25
    avpu_code                                -> eVitals.26  (Required)
    pain_score                               -> eVitals.27
    pain_scale_type_code                     -> eVitals.28
    stroke_scale_result_code                 -> eVitals.29  (Required)
    stroke_scale_type_code                   -> eVitals.30  (Required)
    reperfusion_checklist (child rows)       -> eVitals.31  (1:M)
    apgar_score                              -> eVitals.32
    revised_trauma_score                     -> eVitals.33
    stroke_scale_score                       -> eVitals.34
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship

from epcr_app.models import Base


class VitalsNemsisExt(Base):
    """NEMSIS eVitals 1:1 extension aggregate for a Vitals row.

    Keyed on ``vitals_id`` (unique). Carries every NEMSIS v3.5.1
    eVitals element that the legacy :class:`Vitals` table does NOT
    already model. All clinical columns are nullable; the chart
    finalization gate (registry-driven) enforces the Required-at-National
    subset, not the schema.
    """

    __tablename__ = "epcr_vitals_nemsis_ext"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "vitals_id",
            name="uq_epcr_vitals_nemsis_ext_tenant_vitals",
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
    vitals_id = Column(
        String(36),
        ForeignKey("epcr_vitals.id"),
        nullable=False,
        unique=True,
        index=True,
    )

    # eVitals.02 — Obtained Prior to EMS Care (Required)
    obtained_prior_to_ems_code = Column(String(16), nullable=True)
    # eVitals.03 — Cardiac Rhythm/Electrocardiogram (1:M, list of codes)
    cardiac_rhythm_codes_json = Column(JSON, nullable=True)
    # eVitals.04 — Type of Electrocardiogram
    ecg_type_code = Column(String(16), nullable=True)
    # eVitals.05 — Method of ECG Interpretation (1:M)
    ecg_interpretation_method_codes_json = Column(JSON, nullable=True)
    # eVitals.08 — Blood Pressure Method
    blood_pressure_method_code = Column(String(16), nullable=True)
    # eVitals.09 — Mean Arterial Pressure
    mean_arterial_pressure = Column(Integer, nullable=True)
    # eVitals.11 — Method of Heart Rate Measurement
    heart_rate_method_code = Column(String(16), nullable=True)
    # eVitals.13 — Pulse Rhythm
    pulse_rhythm_code = Column(String(16), nullable=True)
    # eVitals.15 — Respiratory Effort (Required)
    respiratory_effort_code = Column(String(16), nullable=True)
    # eVitals.16 — End-Tidal Carbon Dioxide (ETCO2) (Required)
    etco2 = Column(Integer, nullable=True)
    # eVitals.17 — Carbon Monoxide (CO)
    carbon_monoxide_ppm = Column(Float, nullable=True)
    # eVitals.19 — Glasgow Coma Score — Eye (Required)
    gcs_eye_code = Column(String(16), nullable=True)
    # eVitals.20 — Glasgow Coma Score — Verbal (Required)
    gcs_verbal_code = Column(String(16), nullable=True)
    # eVitals.21 — Glasgow Coma Score — Motor (Required)
    gcs_motor_code = Column(String(16), nullable=True)
    # eVitals.23 — Total Glasgow Coma Score
    gcs_total = Column(Integer, nullable=True)
    # eVitals.25 — Temperature Method
    temperature_method_code = Column(String(16), nullable=True)
    # eVitals.26 — Level of Responsiveness (AVPU) (Required)
    avpu_code = Column(String(16), nullable=True)
    # eVitals.27 — Pain Scale Score
    pain_score = Column(Integer, nullable=True)
    # eVitals.28 — Pain Scale Type
    pain_scale_type_code = Column(String(16), nullable=True)
    # eVitals.29 — Stroke Scale Result (Required)
    stroke_scale_result_code = Column(String(16), nullable=True)
    # eVitals.30 — Stroke Scale Type (Required)
    stroke_scale_type_code = Column(String(16), nullable=True)
    # eVitals.34 — Stroke Scale Score
    stroke_scale_score = Column(Integer, nullable=True)
    # eVitals.32 — APGAR
    apgar_score = Column(Integer, nullable=True)
    # eVitals.33 — Revised Trauma Score
    revised_trauma_score = Column(Integer, nullable=True)

    # standard envelope
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
    vitals = relationship("Vitals", foreign_keys=[vitals_id])


class VitalsGcsQualifier(Base):
    """eVitals.22 — Glasgow Coma Score Qualifier (Required, 1:M).

    Repeating-group child for the GCS qualifier code list (e.g.
    intubated, eyes-closed-due-to-swelling, medication effect). One row
    per applicable qualifier per parent Vitals row.
    """

    __tablename__ = "epcr_vitals_gcs_qualifiers"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "vitals_id",
            "qualifier_code",
            name="uq_epcr_vitals_gcs_qualifiers_tenant_vitals_code",
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
    vitals_id = Column(
        String(36),
        ForeignKey("epcr_vitals.id"),
        nullable=False,
        index=True,
    )
    qualifier_code = Column(String(16), nullable=False)
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


class VitalsReperfusionChecklist(Base):
    """eVitals.31 — Reperfusion Checklist (1:M).

    Repeating-group child for the reperfusion (STEMI/stroke) checklist
    code list. One row per applicable checklist item per parent Vitals
    row.
    """

    __tablename__ = "epcr_vitals_reperfusion_checklist"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "vitals_id",
            "item_code",
            name="uq_epcr_vitals_reperfusion_checklist_tenant_vitals_code",
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
    vitals_id = Column(
        String(36),
        ForeignKey("epcr_vitals.id"),
        nullable=False,
        index=True,
    )
    item_code = Column(String(16), nullable=False)
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


__all__ = [
    "VitalsNemsisExt",
    "VitalsGcsQualifier",
    "VitalsReperfusionChecklist",
]
