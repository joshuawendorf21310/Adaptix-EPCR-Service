"""NEMSIS submission pipeline ORM models for the epcr domain.

Defines tables for resource packs, state submission lifecycle,
submission status history, and compliance studio scenario management.
All models align to the PostgreSQL schema in migration 004_add_nemsis_submission_pipeline.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import relationship

from epcr_app.models import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class NemsisPack(Base):
    """NEMSIS resource pack: a versioned collection of validation assets."""

    __tablename__ = "nemsis_resource_packs"

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    pack_type = Column(String(64), nullable=False)
    nemsis_version = Column(String(32), nullable=False, default="3.5.1")
    status = Column(String(32), nullable=False, default="pending")
    s3_bucket = Column(String(255), nullable=True)
    s3_prefix = Column(String(1024), nullable=True)
    file_count = Column(Integer, nullable=False, default=0)
    size_bytes = Column(BigInteger, nullable=False, default=0)
    activated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    created_by_user_id = Column(String(255), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)

    files = relationship(
        "NemsisPackFile",
        backref="pack",
        cascade="all, delete-orphan",
        order_by="NemsisPackFile.uploaded_at",
    )


class NemsisPackFile(Base):
    """A single file within a NEMSIS resource pack."""

    __tablename__ = "nemsis_pack_files"

    id = Column(String(36), primary_key=True)
    pack_id = Column(
        String(36),
        ForeignKey("nemsis_resource_packs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_name = Column(String(512), nullable=False)
    file_role = Column(String(64), nullable=True)
    s3_key = Column(String(1024), nullable=True)
    size_bytes = Column(BigInteger, nullable=False, default=0)
    sha256 = Column(String(64), nullable=True)
    uploaded_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)


class NemsisSubmissionResult(Base):
    """State submission lifecycle record for a single NEMSIS 3.5.1 export."""

    __tablename__ = "nemsis_submission_results"

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), nullable=False, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)

    # Keep as string only if there is no canonical export table yet.
    # If a real export table exists, convert this to a ForeignKey.
    export_id = Column(String(36), nullable=True, index=True)

    submission_number = Column(String(64), nullable=False, index=True)
    state_endpoint_url = Column(String(2048), nullable=True)
    submission_status = Column(String(32), nullable=False, default="pending")

    xml_s3_bucket = Column(String(255), nullable=True)
    xml_s3_key = Column(String(1024), nullable=True)
    ack_s3_bucket = Column(String(255), nullable=True)
    ack_s3_key = Column(String(1024), nullable=True)
    response_s3_bucket = Column(String(255), nullable=True)
    response_s3_key = Column(String(1024), nullable=True)

    payload_sha256 = Column(String(64), nullable=True)
    soap_message_id = Column(String(255), nullable=True)
    soap_response_code = Column(String(32), nullable=True)
    rejection_reason = Column(Text, nullable=True)
    comparison_report_ref = Column(String(1024), nullable=True)

    submitted_at = Column(DateTime(timezone=True), nullable=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    created_by_user_id = Column(String(255), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)

    history = relationship(
        "NemsisSubmissionStatusHistory",
        backref="submission",
        cascade="all, delete-orphan",
        order_by="NemsisSubmissionStatusHistory.transitioned_at",
    )


class NemsisSubmissionStatusHistory(Base):
    """Immutable status transition log for a NEMSIS state submission."""

    __tablename__ = "nemsis_submission_status_history"

    id = Column(String(36), primary_key=True)
    submission_id = Column(
        String(36),
        ForeignKey("nemsis_submission_results.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(String(36), nullable=False, index=True)
    from_status = Column(String(32), nullable=True)
    to_status = Column(String(32), nullable=False)
    actor_user_id = Column(String(255), nullable=True)
    note = Column(Text, nullable=True)
    payload_snapshot_json = Column(Text, nullable=True)
    transitioned_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)


class NemsisScenario(Base):
    """NEMSIS 2026 TAC Compliance Studio scenario definition and run state."""

    __tablename__ = "nemsis_cs_scenarios"

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), nullable=True, index=True)
    scenario_code = Column(String(64), nullable=False, unique=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    year = Column(Integer, nullable=False)
    category = Column(String(32), nullable=False)
    asset_s3_bucket = Column(String(255), nullable=True)
    asset_s3_key = Column(String(1024), nullable=True)
    asset_json = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="available")
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    last_submission_id = Column(
        String(36),
        ForeignKey("nemsis_submission_results.id"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)

    last_submission = relationship(
        "NemsisSubmissionResult",
        foreign_keys=[last_submission_id],
        uselist=False,
    )