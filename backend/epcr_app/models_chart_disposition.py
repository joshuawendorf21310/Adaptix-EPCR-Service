"""NEMSIS eDisposition (chart disposition) ORM model.

Backs the ``epcr_chart_disposition`` table created by migration ``033``.
Represents the NEMSIS v3.5.1 eDisposition section as a 1:1 child
aggregate of :class:`Chart`. The chart-finalization gate enforces the
Mandatory / Required-at-National subsets
(eDisposition.12 Mandatory; eDisposition.16/.18 Required-at-National)
via the registry-driven validator, not in the ORM layer.

NEMSIS element bindings (handled by :mod:`projection_chart_disposition`):

    destination_name                                  -> eDisposition.01
    destination_code                                  -> eDisposition.02
    destination_address                               -> eDisposition.03
    destination_city                                  -> eDisposition.04
    destination_county                                -> eDisposition.05
    destination_state                                 -> eDisposition.06
    destination_zip                                   -> eDisposition.07
    destination_country                               -> eDisposition.08
    hospital_capability_codes_json                    -> eDisposition.09 (1:M list)
    reason_for_choosing_destination_codes_json        -> eDisposition.10 (1:M list)
    type_of_destination_code                          -> eDisposition.11
    incident_patient_disposition_code                 -> eDisposition.12 (Mandatory)
    transport_mode_from_scene_code                    -> eDisposition.13
    additional_transport_descriptors_codes_json       -> eDisposition.14 (1:M list)
    hospital_incapability_codes_json                  -> eDisposition.15 (1:M list)
    transport_disposition_code                        -> eDisposition.16 (Required)
    reason_not_transported_code                       -> eDisposition.17
    level_of_care_provided_code                       -> eDisposition.18 (Required)
    position_during_transport_code                    -> eDisposition.19
    condition_at_destination_code                     -> eDisposition.20
    transferred_care_to_code                          -> eDisposition.21
    prearrival_activation_codes_json                  -> eDisposition.22 (1:M list)
    type_of_destination_reason_codes_json             -> eDisposition.23 (1:M list)
    destination_team_activations_codes_json           -> eDisposition.24 (1:M list)
    destination_type_when_reason_code                 -> eDisposition.25
    crew_disposition_codes_json                       -> eDisposition.27 (1:M list)
    unit_disposition_code                             -> eDisposition.28
    transport_method_code                             -> eDisposition.29
    transport_method_additional_codes_json            -> eDisposition.30 (1:M list)

(eDisposition.26 is not defined in NEMSIS v3.5.1; intentionally skipped.)

The ``*_codes_json`` columns hold JSON arrays of NEMSIS code values
(1:M repeating-group lists). The projection layer expands each list
entry into one ledger row.
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


class ChartDisposition(Base):
    """NEMSIS eDisposition 1:1 aggregate for a chart.

    All columns are nullable in the ORM. The chart-finalization gate
    enforces NEMSIS Mandatory/Required-at-National subsets via the
    registry-driven validator. The ``*_codes_json`` columns hold JSON
    arrays of NEMSIS code values that the projection layer expands
    into separate repeating-group ledger rows.
    """

    __tablename__ = "epcr_chart_disposition"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "chart_id",
            name="uq_epcr_chart_disposition_tenant_chart",
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

    # eDisposition.01..08 — destination identification + address
    destination_name = Column(String(255), nullable=True)
    destination_code = Column(String(64), nullable=True)
    destination_address = Column(String(255), nullable=True)
    destination_city = Column(String(120), nullable=True)
    destination_county = Column(String(120), nullable=True)
    destination_state = Column(String(8), nullable=True)
    destination_zip = Column(String(16), nullable=True)
    destination_country = Column(String(8), nullable=True)

    # eDisposition.09..10 — hospital capabilities / reason for choosing (1:M)
    hospital_capability_codes_json = Column(JSON, nullable=True)
    reason_for_choosing_destination_codes_json = Column(JSON, nullable=True)

    # eDisposition.11..12 — type of destination + incident/patient disposition
    type_of_destination_code = Column(String(16), nullable=True)
    incident_patient_disposition_code = Column(String(16), nullable=True)

    # eDisposition.13..14 — transport mode + additional descriptors (1:M)
    transport_mode_from_scene_code = Column(String(16), nullable=True)
    additional_transport_descriptors_codes_json = Column(JSON, nullable=True)

    # eDisposition.15 — hospital incapability (1:M)
    hospital_incapability_codes_json = Column(JSON, nullable=True)

    # eDisposition.16..18 — transport disposition + reason + level of care
    transport_disposition_code = Column(String(16), nullable=True)
    reason_not_transported_code = Column(String(16), nullable=True)
    level_of_care_provided_code = Column(String(16), nullable=True)

    # eDisposition.19..21 — position / condition / care-to
    position_during_transport_code = Column(String(16), nullable=True)
    condition_at_destination_code = Column(String(16), nullable=True)
    transferred_care_to_code = Column(String(16), nullable=True)

    # eDisposition.22..24 — prearrival / type-reason / team activations (1:M)
    prearrival_activation_codes_json = Column(JSON, nullable=True)
    type_of_destination_reason_codes_json = Column(JSON, nullable=True)
    destination_team_activations_codes_json = Column(JSON, nullable=True)

    # eDisposition.25 — destination type when reason code used
    destination_type_when_reason_code = Column(String(16), nullable=True)

    # eDisposition.27..30 — crew/unit disposition + EMS transport method
    # (eDisposition.26 is not defined in NEMSIS v3.5.1)
    crew_disposition_codes_json = Column(JSON, nullable=True)
    unit_disposition_code = Column(String(16), nullable=True)
    transport_method_code = Column(String(16), nullable=True)
    transport_method_additional_codes_json = Column(JSON, nullable=True)

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


__all__ = ["ChartDisposition"]
