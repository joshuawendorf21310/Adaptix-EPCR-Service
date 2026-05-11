"""NEMSIS eSituation (chart situation) ORM models.

Backs the ``epcr_chart_situation`` (1:1) and two child tables
``epcr_chart_situation_other_symptoms`` /
``epcr_chart_situation_secondary_impressions`` (1:M) created by
migration ``029``. Represents the NEMSIS v3.5.1 eSituation section as
a 1:1 child aggregate of :class:`Chart` plus two repeating groups
(Other Associated Symptoms and Provider's Secondary Impressions).

NEMSIS element bindings (handled by :mod:`projection_chart_situation`):

    symptom_onset_at                       -> eSituation.01 (Required)
    possible_injury_indicator_code         -> eSituation.02 (Required)
    complaint_type_code                    -> eSituation.03 (Required)
    complaint_text                         -> eSituation.04 (Required)
    complaint_duration_value               -> eSituation.05 (Required-if-known)
    complaint_duration_units_code          -> eSituation.06 (Required-if-.05)
    chief_complaint_anatomic_code          -> eSituation.07
    chief_complaint_organ_system_code      -> eSituation.08
    primary_symptom_code                   -> eSituation.09 (Required)
    other_symptoms[].symptom_code          -> eSituation.10 (Recommended, 1:M)
    provider_primary_impression_code       -> eSituation.11 (Required)
    secondary_impressions[].impression_code-> eSituation.12 (Recommended, 1:M)
    initial_patient_acuity_code            -> eSituation.13 (Required)
    work_related_indicator_code            -> eSituation.14 (Required)
    patient_industry_code                  -> eSituation.15
    patient_occupation_code                -> eSituation.16
    patient_activity_code                  -> eSituation.17
    last_known_well_at                     -> eSituation.18 (Required for stroke)
    transfer_justification_code            -> eSituation.19
    interfacility_transfer_reason_code     -> eSituation.20

All columns on the 1:1 row are nullable at the ORM layer; the chart-
finalization gate enforces the Required-at-National subset via the
registry-driven validator, not in the ORM layer.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)

from epcr_app.models import Base


class ChartSituation(Base):
    """NEMSIS eSituation 1:1 aggregate for a chart.

    Holds the 18 scalar eSituation columns (.01..09, .11, .13..20).
    The two repeating groups eSituation.10 (Other Associated Symptoms)
    and eSituation.12 (Provider's Secondary Impressions) live in their
    own child tables; see :class:`ChartSituationOtherSymptom` and
    :class:`ChartSituationSecondaryImpression`.
    """

    __tablename__ = "epcr_chart_situation"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "chart_id",
            name="uq_epcr_chart_situation_tenant_chart",
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

    # eSituation.01..20 scalar columns in NEMSIS-canonical order
    symptom_onset_at = Column(DateTime(timezone=True), nullable=True)
    possible_injury_indicator_code = Column(String(16), nullable=True)
    complaint_type_code = Column(String(16), nullable=True)
    complaint_text = Column(Text, nullable=True)
    complaint_duration_value = Column(Integer, nullable=True)
    complaint_duration_units_code = Column(String(16), nullable=True)
    chief_complaint_anatomic_code = Column(String(16), nullable=True)
    chief_complaint_organ_system_code = Column(String(16), nullable=True)
    primary_symptom_code = Column(String(32), nullable=True)
    provider_primary_impression_code = Column(String(32), nullable=True)
    initial_patient_acuity_code = Column(String(16), nullable=True)
    work_related_indicator_code = Column(String(16), nullable=True)
    patient_industry_code = Column(String(16), nullable=True)
    patient_occupation_code = Column(String(16), nullable=True)
    patient_activity_code = Column(String(16), nullable=True)
    last_known_well_at = Column(DateTime(timezone=True), nullable=True)
    transfer_justification_code = Column(String(16), nullable=True)
    interfacility_transfer_reason_code = Column(String(16), nullable=True)

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


class ChartSituationOtherSymptom(Base):
    """NEMSIS eSituation.10 1:M repeating group for a chart.

    Each row is one "Other Associated Symptom" code reported alongside
    the primary symptom (eSituation.09). The (tenant, chart, symptom)
    tuple is unique so the same code cannot be listed twice per chart.
    """

    __tablename__ = "epcr_chart_situation_other_symptoms"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "chart_id",
            "symptom_code",
            name="uq_epcr_chart_situation_other_symptoms_tenant_chart_code",
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

    symptom_code = Column(String(32), nullable=False)
    sequence_index = Column(Integer, nullable=False, default=0)

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


class ChartSituationSecondaryImpression(Base):
    """NEMSIS eSituation.12 1:M repeating group for a chart.

    Each row is one "Provider's Secondary Impression" code recorded in
    addition to the primary impression (eSituation.11). The (tenant,
    chart, impression) tuple is unique so the same code cannot be
    listed twice per chart.
    """

    __tablename__ = "epcr_chart_situation_secondary_impressions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "chart_id",
            "impression_code",
            name="uq_epcr_chart_situation_secondary_impressions_tenant_chart_code",
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

    impression_code = Column(String(32), nullable=False)
    sequence_index = Column(Integer, nullable=False, default=0)

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
    "ChartSituation",
    "ChartSituationOtherSymptom",
    "ChartSituationSecondaryImpression",
]
