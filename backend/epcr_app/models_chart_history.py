"""NEMSIS eHistory (chart medical history) ORM models.

Back the five ``epcr_chart_history_*`` tables created by migration
``030``. Represents the NEMSIS v3.5.1 eHistory section as a small star
of child aggregates around :class:`Chart`:

    * :class:`ChartHistoryMeta`              -- 1:1 single-row meta
    * :class:`ChartHistoryAllergy`           -- 1:M medication + env/food allergies
    * :class:`ChartHistorySurgical`          -- 1:M medical/surgical history
    * :class:`ChartHistoryCurrentMedication` -- 1:M current medications + dose info
    * :class:`ChartHistoryImmunization`      -- 1:M immunizations

NEMSIS element bindings (handled by :mod:`projection_chart_history`):

    barriers_to_care_codes_json                -> eHistory.01 (1:M)
    practitioner_last_name                     -> eHistory.02
    practitioner_first_name                    -> eHistory.03
    practitioner_middle_name                   -> eHistory.04
    advance_directives_codes_json              -> eHistory.05 (1:M)
    allergies (medication)                     -> eHistory.06 (1:M)
    allergies (environmental_food)             -> eHistory.07 (1:M)
    surgical condition_code                    -> eHistory.08 (1:M)
    medical_history_obtained_from_codes_json   -> eHistory.09 (1:M)
    immunizations immunization_type_code       -> eHistory.10 (1:M)
    immunizations immunization_year            -> eHistory.11 (1:M)
    current_medications drug_code              -> eHistory.12 (1:M)
    current_medications dose_value             -> eHistory.13
    current_medications dose_unit_code         -> eHistory.14
    current_medications route_code             -> eHistory.15
    emergency_information_form_code            -> eHistory.16
    alcohol_drug_use_codes_json                -> eHistory.17 (1:M)
    pregnancy_code                             -> eHistory.18
    last_oral_intake_at                        -> eHistory.19
    current_medications frequency_code         -> eHistory.20
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
from sqlalchemy.orm import relationship

from epcr_app.models import Base


class ChartHistoryMeta(Base):
    """NEMSIS eHistory 1:1 meta aggregate for a chart.

    Holds the single-valued eHistory elements (practitioner name,
    pregnancy code, last oral intake, emergency information form) and
    the four 1:M code-list columns that are stored inline as JSON
    arrays (barriers to care, advance directives, history-obtained-from,
    alcohol/drug use). The chart-finalization gate enforces the Required
    subset via the registry-driven validator, not in the ORM layer.
    """

    __tablename__ = "epcr_chart_history_meta"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "chart_id",
            name="uq_epcr_chart_history_meta_tenant_chart",
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

    # 1:M code-list columns (stored inline as JSON arrays)
    barriers_to_care_codes_json = Column(JSON, nullable=True)
    advance_directives_codes_json = Column(JSON, nullable=True)
    medical_history_obtained_from_codes_json = Column(JSON, nullable=True)
    alcohol_drug_use_codes_json = Column(JSON, nullable=True)

    # Single-valued columns
    practitioner_last_name = Column(String(120), nullable=True)
    practitioner_first_name = Column(String(120), nullable=True)
    practitioner_middle_name = Column(String(120), nullable=True)
    pregnancy_code = Column(String(16), nullable=True)
    last_oral_intake_at = Column(DateTime(timezone=True), nullable=True)
    emergency_information_form_code = Column(String(16), nullable=True)

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


class ChartHistoryAllergy(Base):
    """NEMSIS eHistory.06 / eHistory.07 1:M allergy aggregate.

    ``allergy_kind`` discriminates which NEMSIS element this row maps
    to: ``"medication"`` => eHistory.06 Medication Allergies (Required,
    1:M); ``"environmental_food"`` => eHistory.07 Environmental/Food
    Allergies (Required, 1:M). Each row is one allergy occurrence.
    """

    __tablename__ = "epcr_chart_history_allergies"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "chart_id",
            "allergy_kind",
            "allergy_code",
            name="uq_epcr_chart_history_allergies_tenant_chart_kind_code",
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

    allergy_kind = Column(String(16), nullable=False)
    allergy_code = Column(String(64), nullable=False)
    allergy_text = Column(String(255), nullable=True)
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


class ChartHistorySurgical(Base):
    """NEMSIS eHistory.08 Medical/Surgical History (Required, 1:M).

    Each row is one ICD-10 condition the patient has in their medical
    or surgical history. ``condition_text`` is an optional free-text
    label captured for display/UX; the export emits ``condition_code``.
    """

    __tablename__ = "epcr_chart_history_surgical"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "chart_id",
            "condition_code",
            name="uq_epcr_chart_history_surgical_tenant_chart_code",
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

    condition_code = Column(String(64), nullable=False)
    condition_text = Column(String(255), nullable=True)
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


class ChartHistoryCurrentMedication(Base):
    """NEMSIS eHistory.12/13/14/15/20 Current Medications (1:M).

    One row per current medication. ``drug_code`` is RxNorm
    (eHistory.12 Required). Dose value/unit (eHistory.13/14), route
    (eHistory.15), and frequency (eHistory.20) are sibling fields that
    travel with the same NEMSIS group occurrence.
    """

    __tablename__ = "epcr_chart_history_current_medications"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "chart_id",
            "drug_code",
            name="uq_epcr_chart_history_current_medications_tenant_chart_drug",
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

    drug_code = Column(String(64), nullable=False)
    dose_value = Column(String(32), nullable=True)
    dose_unit_code = Column(String(16), nullable=True)
    route_code = Column(String(16), nullable=True)
    frequency_code = Column(String(32), nullable=True)
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


class ChartHistoryImmunization(Base):
    """NEMSIS eHistory.10/11 Immunizations (Optional, 1:M).

    One row per immunization. ``immunization_type_code`` maps to
    eHistory.10; ``immunization_year`` maps to eHistory.11. Year may be
    null when the patient/caregiver cannot recall the date.
    """

    __tablename__ = "epcr_chart_history_immunizations"

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    chart_id = Column(
        String(36),
        ForeignKey("epcr_charts.id"),
        nullable=False,
        index=True,
    )

    immunization_type_code = Column(String(16), nullable=False)
    immunization_year = Column(Integer, nullable=True)
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
    "ChartHistoryMeta",
    "ChartHistoryAllergy",
    "ChartHistorySurgical",
    "ChartHistoryCurrentMedication",
    "ChartHistoryImmunization",
]
