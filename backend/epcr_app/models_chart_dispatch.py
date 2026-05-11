"""NEMSIS eDispatch (chart dispatch) ORM model.

Backs the ``epcr_chart_dispatch`` table created by migration ``025``.
Represents the 6 NEMSIS v3.5.1 eDispatch elements as a 1:1 child
aggregate of :class:`Chart`. Every column is nullable because not every
call captures every element; the chart-finalization gate enforces the
Mandatory/Required-at-National subset.

NEMSIS element bindings (handled by :mod:`projection_chart_dispatch`):

    dispatch_reason_code      -> eDispatch.01  (Dispatch Reason)
    emd_performed_code        -> eDispatch.02  (EMD Performed)
    emd_determinant_code      -> eDispatch.03  (EMD Determinant Code)
    dispatch_center_id        -> eDispatch.04  (Dispatch Center Name or ID)
    dispatch_priority_code    -> eDispatch.05  (Dispatch Priority - Patient Acuity)
    cad_record_id             -> eDispatch.06  (Unit Dispatched CAD Record ID)
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


class ChartDispatch(Base):
    """NEMSIS eDispatch 1:1 aggregate for a chart.

    All 6 columns are nullable. The chart finalization gate enforces
    the Mandatory (eDispatch.01) and Required-at-National
    (eDispatch.02/03/04/05) subset via the registry-driven validator,
    not in the ORM layer.
    """

    __tablename__ = "epcr_chart_dispatch"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "chart_id",
            name="uq_epcr_chart_dispatch_tenant_chart",
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

    # eDispatch.01..06 in NEMSIS-canonical order
    dispatch_reason_code = Column(String(16), nullable=True)
    emd_performed_code = Column(String(16), nullable=True)
    emd_determinant_code = Column(String(64), nullable=True)
    dispatch_center_id = Column(String(128), nullable=True)
    dispatch_priority_code = Column(String(16), nullable=True)
    cad_record_id = Column(String(64), nullable=True)

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


__all__ = ["ChartDispatch"]
