"""NEMSIS eResponse (chart response metadata + delays) ORM models.

Backs the ``epcr_chart_response`` and ``epcr_chart_response_delays``
tables created by migration ``027``. Represents the NEMSIS v3.5.1
eResponse section as two child aggregates of :class:`Chart`:

* :class:`ChartResponse` — 1:1 response metadata (agency, unit, vehicle
  dispatch location, odometer readings, response-mode, additional
  response descriptors).
* :class:`ChartResponseDelay` — 1:M typed delays
  (dispatch/response/scene/transport/turn_around).

NEMSIS element bindings (handled by :mod:`projection_chart_response`):

    agency_number                         -> eResponse.01 (Mandatory)
    agency_name                           -> eResponse.02 (Required)
    type_of_service_requested_code        -> eResponse.05 (Mandatory)
    standby_purpose_code                  -> eResponse.06 (Optional)
    unit_transport_capability_code        -> eResponse.07 (Required)
    unit_vehicle_number                   -> eResponse.13 (Mandatory)
    unit_call_sign                        -> eResponse.14 (Required)
    vehicle_dispatch_address              -> eResponse.16
    vehicle_dispatch_lat/_long            -> eResponse.17 (lat+long bundle)
    vehicle_dispatch_usng                 -> eResponse.18
    beginning_odometer                    -> eResponse.19
    on_scene_odometer                     -> eResponse.20
    destination_odometer                  -> eResponse.21
    ending_odometer                       -> eResponse.22
    response_mode_to_scene_code           -> eResponse.23 (Mandatory)
    additional_response_descriptors_json  -> eResponse.24 (Optional, 1:M list)

    delay_kind="dispatch"     -> eResponse.08 Type of Dispatch Delay
    delay_kind="response"     -> eResponse.09 Type of Response Delay
    delay_kind="scene"        -> eResponse.10 Type of Scene Delay
    delay_kind="transport"    -> eResponse.11 Type of Transport Delay
    delay_kind="turn_around"  -> eResponse.12 Type of Turn-Around Delay
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


class ChartResponse(Base):
    """NEMSIS eResponse 1:1 metadata aggregate for a chart.

    Required-and-Mandatory columns are not enforced as NOT NULL at the
    ORM layer because the chart-finalization gate is the single
    authority on Required-at-National completeness. Coded fields are
    persisted as their raw NEMSIS code values; the projection layer
    surfaces them by element_number.
    """

    __tablename__ = "epcr_chart_response"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "chart_id",
            name="uq_epcr_chart_response_tenant_chart",
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

    # eResponse.01..02 — agency identity
    agency_number = Column(String(16), nullable=True)
    agency_name = Column(String(255), nullable=True)

    # eResponse.05..07 — service / unit capability
    type_of_service_requested_code = Column(String(16), nullable=True)
    standby_purpose_code = Column(String(16), nullable=True)
    unit_transport_capability_code = Column(String(16), nullable=True)

    # eResponse.13..14 — unit identity
    unit_vehicle_number = Column(String(32), nullable=True)
    unit_call_sign = Column(String(32), nullable=True)

    # eResponse.16..18 — vehicle dispatch location bundle
    vehicle_dispatch_address = Column(String(255), nullable=True)
    vehicle_dispatch_lat = Column(Float, nullable=True)
    vehicle_dispatch_long = Column(Float, nullable=True)
    vehicle_dispatch_usng = Column(String(64), nullable=True)

    # eResponse.19..22 — odometer readings
    beginning_odometer = Column(Float, nullable=True)
    on_scene_odometer = Column(Float, nullable=True)
    destination_odometer = Column(Float, nullable=True)
    ending_odometer = Column(Float, nullable=True)

    # eResponse.23 — response mode
    response_mode_to_scene_code = Column(String(16), nullable=True)

    # eResponse.24 — additional response descriptors (Optional, 1:M list)
    additional_response_descriptors_json = Column(JSON, nullable=True)

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


# Allowed values for ChartResponseDelay.delay_kind. Each kind maps 1:1
# to a NEMSIS eResponse element in the projection layer.
RESPONSE_DELAY_KINDS: tuple[str, ...] = (
    "dispatch",
    "response",
    "scene",
    "transport",
    "turn_around",
)


class ChartResponseDelay(Base):
    """NEMSIS eResponse 1:M typed-delay aggregate for a chart.

    Each row is one (kind, code) pair. ``delay_kind`` partitions the
    rows into the five NEMSIS delay element groups
    (eResponse.08/09/10/11/12); ``delay_code`` is the NEMSIS coded
    value. The (tenant, chart, kind, code) tuple is unique so the same
    delay code cannot be listed twice within a single delay kind on the
    same chart.
    """

    __tablename__ = "epcr_chart_response_delays"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "chart_id",
            "delay_kind",
            "delay_code",
            name="uq_chart_response_delays_kind_code",
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

    delay_kind = Column(String(16), nullable=False)
    delay_code = Column(String(32), nullable=False)
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


__all__ = ["ChartResponse", "ChartResponseDelay", "RESPONSE_DELAY_KINDS"]
