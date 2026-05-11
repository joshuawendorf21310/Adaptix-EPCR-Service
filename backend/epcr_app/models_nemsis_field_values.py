"""Row-per-occurrence NEMSIS field-value ORM model.

Backs the ``epcr_nemsis_field_values`` table created by migration 021.
Preserves NEMSIS repeating-group truth: the unique key is
(tenant_id, chart_id, element_number, group_path, occurrence_id) so the
same element_number may be saved many times within one chart, one row
per occurrence. NV/PN/xsi:nil and validation issues live alongside the
value as JSON sidecars on the same row.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
    text,
)

from epcr_app.models import Base


class NemsisFieldValue(Base):
    """One row = one NEMSIS element occurrence on a chart."""

    __tablename__ = "epcr_nemsis_field_values"

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    chart_id = Column(String(64), nullable=False, index=True)
    section = Column(String(32), nullable=False)
    element_number = Column(String(32), nullable=False)
    element_name = Column(String(255), nullable=False)
    group_path = Column(String(255), nullable=False, server_default="")
    occurrence_id = Column(String(64), nullable=False, server_default="")
    sequence_index = Column(Integer, nullable=False, server_default=text("0"))
    value_json = Column(JSON, nullable=True)
    attributes_json = Column(JSON, nullable=False, server_default="{}")
    source = Column(String(32), nullable=False, server_default="manual")
    validation_status = Column(
        String(32), nullable=False, server_default="unvalidated"
    )
    validation_issues_json = Column(JSON, nullable=False, server_default="[]")
    created_by_user_id = Column(String(64), nullable=True)
    updated_by_user_id = Column(String(64), nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "chart_id",
            "element_number",
            "group_path",
            "occurrence_id",
            name="uq_epcr_nemsis_field_values_occurrence",
        ),
    )
