"""NEMSIS eInjury (chart injury + ACN telematics) ORM models.

Backs the ``epcr_chart_injury`` and ``epcr_chart_injury_acn`` tables
created by migration ``031``. Represents the NEMSIS v3.5.1 eInjury
section as a 1:1 child aggregate of :class:`Chart` (populated when the
incident type implies trauma) plus an optional 1:1 ACN telematics
sub-aggregate covering the eInjury.11..29 Automated Crash Notification
Group.

NEMSIS element bindings (handled by :mod:`projection_chart_injury`):

    ChartInjury (eInjury.01..10):
        cause_of_injury_codes_json          -> eInjury.01 (1:M list)
        mechanism_of_injury_code            -> eInjury.02
        trauma_triage_high_codes_json       -> eInjury.03 (1:M list)
        trauma_triage_moderate_codes_json   -> eInjury.04 (1:M list)
        vehicle_impact_area_code            -> eInjury.05
        patient_location_in_vehicle_code    -> eInjury.06
        occupant_safety_equipment_codes_json -> eInjury.07 (1:M list)
        airbag_deployment_code              -> eInjury.08
        height_of_fall_feet                 -> eInjury.09
        osha_ppe_used_codes_json            -> eInjury.10 (1:M list)

    ChartInjuryAcn (eInjury.11..29, Automated Crash Notification Group):
        acn_system_company                  -> eInjury.11
        acn_incident_id                     -> eInjury.12
        acn_callback_phone                  -> eInjury.13
        acn_incident_at                     -> eInjury.14
        acn_incident_location               -> eInjury.15
        acn_vehicle_body_type_code          -> eInjury.16
        acn_vehicle_manufacturer            -> eInjury.17
        acn_vehicle_make                    -> eInjury.18
        acn_vehicle_model                   -> eInjury.19
        acn_vehicle_model_year              -> eInjury.20
        acn_multiple_impacts_code           -> eInjury.21
        acn_delta_velocity                  -> eInjury.22
        acn_high_probability_code           -> eInjury.23
        acn_pdof                            -> eInjury.24
        acn_rollover_code                   -> eInjury.25
        acn_seat_location_code              -> eInjury.26
        seat_occupied_code                  -> eInjury.27
        acn_seatbelt_use_code               -> eInjury.28
        acn_airbag_deployed_code            -> eInjury.29

The four ``*_codes_json`` columns on ChartInjury hold JSON arrays of
NEMSIS code values (1:M repeating-group lists). The projection layer
expands each list entry into one ledger row per entry.
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

from epcr_app.models import Base


class ChartInjury(Base):
    """NEMSIS eInjury 1:1 aggregate for a chart.

    All columns are nullable; the chart-finalization gate enforces any
    Mandatory/Required-at-National subsets via the registry-driven
    validator, not in the ORM layer.

    The four ``*_codes_json`` columns hold JSON arrays of NEMSIS code
    values (1:M repeating-group lists). The projection layer expands
    each list entry into one ledger row.
    """

    __tablename__ = "epcr_chart_injury"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "chart_id",
            name="uq_epcr_chart_injury_tenant_chart",
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

    # eInjury.01..10 in NEMSIS-canonical order
    cause_of_injury_codes_json = Column(JSON, nullable=True)
    mechanism_of_injury_code = Column(String(16), nullable=True)
    trauma_triage_high_codes_json = Column(JSON, nullable=True)
    trauma_triage_moderate_codes_json = Column(JSON, nullable=True)
    vehicle_impact_area_code = Column(String(16), nullable=True)
    patient_location_in_vehicle_code = Column(String(16), nullable=True)
    occupant_safety_equipment_codes_json = Column(JSON, nullable=True)
    airbag_deployment_code = Column(String(16), nullable=True)
    height_of_fall_feet = Column(Float, nullable=True)
    osha_ppe_used_codes_json = Column(JSON, nullable=True)

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


class ChartInjuryAcn(Base):
    """NEMSIS eInjury.11..29 Automated Crash Notification Group 1:1 block.

    Sub-aggregate of :class:`ChartInjury`; one row per ChartInjury when
    ACN telematics are reported. All columns are nullable.
    """

    __tablename__ = "epcr_chart_injury_acn"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "chart_id",
            name="uq_epcr_chart_injury_acn_tenant_chart",
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
    injury_id = Column(
        String(36),
        ForeignKey("epcr_chart_injury.id"),
        nullable=False,
        unique=True,
        index=True,
    )

    # eInjury.11..29 in NEMSIS-canonical order
    acn_system_company = Column(String(255), nullable=True)
    acn_incident_id = Column(String(64), nullable=True)
    acn_callback_phone = Column(String(32), nullable=True)
    acn_incident_at = Column(DateTime(timezone=True), nullable=True)
    acn_incident_location = Column(String(255), nullable=True)
    acn_vehicle_body_type_code = Column(String(16), nullable=True)
    acn_vehicle_manufacturer = Column(String(120), nullable=True)
    acn_vehicle_make = Column(String(120), nullable=True)
    acn_vehicle_model = Column(String(120), nullable=True)
    acn_vehicle_model_year = Column(Integer, nullable=True)
    acn_multiple_impacts_code = Column(String(16), nullable=True)
    acn_delta_velocity = Column(Float, nullable=True)
    acn_high_probability_code = Column(String(16), nullable=True)
    acn_pdof = Column(Integer, nullable=True)
    acn_rollover_code = Column(String(16), nullable=True)
    acn_seat_location_code = Column(String(16), nullable=True)
    seat_occupied_code = Column(String(16), nullable=True)
    acn_seatbelt_use_code = Column(String(16), nullable=True)
    acn_airbag_deployed_code = Column(String(16), nullable=True)

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


__all__ = ["ChartInjury", "ChartInjuryAcn"]
