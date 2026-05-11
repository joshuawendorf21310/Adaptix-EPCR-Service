"""NEMSIS eCrew (chart crew members) ORM model.

Backs the ``epcr_chart_crew_members`` table created by migration ``026``.
Represents the NEMSIS v3.5.1 eCrew section as a 1:M child aggregate
of :class:`Chart`: each crew member assigned to the chart is one row.

NEMSIS element bindings (handled by :mod:`projection_chart_crew`):

    crew_member_id                  -> eCrew.01 (Mandatory)
    crew_member_level_code          -> eCrew.02 (Mandatory)
    crew_member_response_role_code  -> eCrew.03 (Required)

Each crew row projects as one repeating-group occurrence with three
ledger entries sharing the row's UUID as ``occurrence_id`` so the
NEMSIS dataset XML builder can reassemble the crew member element.
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

from epcr_app.models import Base


class ChartCrewMember(Base):
    """NEMSIS eCrew 1:M aggregate for a chart.

    A chart has zero or more crew member rows. The (tenant, chart,
    crew_member_id) tuple is unique so the same person cannot be listed
    twice on the same chart. The chart-finalization gate enforces the
    Mandatory subset (eCrew.01/02) and Required subset (eCrew.03) via
    the registry-driven validator, not in the ORM layer.
    """

    __tablename__ = "epcr_chart_crew_members"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "chart_id",
            "crew_member_id",
            name="uq_epcr_chart_crew_members_tenant_chart_member",
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

    # eCrew.01..03 in NEMSIS-canonical order
    crew_member_id = Column(String(64), nullable=False)
    crew_member_level_code = Column(String(16), nullable=False)
    crew_member_response_role_code = Column(String(16), nullable=False)
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


__all__ = ["ChartCrewMember"]
