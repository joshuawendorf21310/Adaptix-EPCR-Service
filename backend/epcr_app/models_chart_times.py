"""NEMSIS eTimes (chart event timeline) ORM model.

Backs the ``epcr_chart_times`` table created by migration ``024``.
Represents the 17 NEMSIS v3.5.1 eTimes elements as a 1:1 child aggregate
of :class:`Chart`. Every column is nullable because not every call
captures every time; the chart-finalization gate enforces the
Required-at-National subset.

NEMSIS element bindings (handled by :mod:`projection_chart_times`):

    psap_call_at                       -> eTimes.01
    dispatch_notified_at               -> eTimes.02
    unit_notified_by_dispatch_at       -> eTimes.03
    dispatch_acknowledged_at           -> eTimes.04
    unit_en_route_at                   -> eTimes.05
    unit_on_scene_at                   -> eTimes.06
    arrived_at_patient_at              -> eTimes.07
    transfer_of_ems_care_at            -> eTimes.08
    unit_left_scene_at                 -> eTimes.09
    arrival_landing_area_at            -> eTimes.10
    patient_arrived_at_destination_at  -> eTimes.11
    destination_transfer_of_care_at    -> eTimes.12
    unit_back_in_service_at            -> eTimes.13
    unit_canceled_at                   -> eTimes.14
    unit_back_home_location_at         -> eTimes.15
    ems_call_completed_at              -> eTimes.16
    unit_arrived_staging_at            -> eTimes.17
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


class ChartTimes(Base):
    """NEMSIS eTimes 1:1 aggregate for a chart.

    All 17 timestamp columns are nullable. The chart finalization gate
    enforces the Required-at-National subset
    (eTimes.03/05/06/07/09/11/12 at minimum) via the registry-driven
    validator, not in the ORM layer.
    """

    __tablename__ = "epcr_chart_times"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "chart_id",
            name="uq_epcr_chart_times_tenant_chart",
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

    # eTimes.01..17 in NEMSIS-canonical order
    psap_call_at = Column(DateTime(timezone=True), nullable=True)
    dispatch_notified_at = Column(DateTime(timezone=True), nullable=True)
    unit_notified_by_dispatch_at = Column(DateTime(timezone=True), nullable=True)
    dispatch_acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    unit_en_route_at = Column(DateTime(timezone=True), nullable=True)
    unit_on_scene_at = Column(DateTime(timezone=True), nullable=True)
    arrived_at_patient_at = Column(DateTime(timezone=True), nullable=True)
    transfer_of_ems_care_at = Column(DateTime(timezone=True), nullable=True)
    unit_left_scene_at = Column(DateTime(timezone=True), nullable=True)
    arrival_landing_area_at = Column(DateTime(timezone=True), nullable=True)
    patient_arrived_at_destination_at = Column(DateTime(timezone=True), nullable=True)
    destination_transfer_of_care_at = Column(DateTime(timezone=True), nullable=True)
    unit_back_in_service_at = Column(DateTime(timezone=True), nullable=True)
    unit_canceled_at = Column(DateTime(timezone=True), nullable=True)
    unit_back_home_location_at = Column(DateTime(timezone=True), nullable=True)
    ems_call_completed_at = Column(DateTime(timezone=True), nullable=True)
    unit_arrived_staging_at = Column(DateTime(timezone=True), nullable=True)

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


__all__ = ["ChartTimes"]
