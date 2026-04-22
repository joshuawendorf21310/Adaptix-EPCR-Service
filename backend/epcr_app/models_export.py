"""NEMSIS export attempt and event ORM models.

Core persistence layer for export lifecycle with complete audit trail.
Uses database-agnostic JSON type so the schema can be created on both
SQLite (local development) and PostgreSQL (production). On PostgreSQL,
JSONB behaviour is preserved at the driver level via asyncpg.
"""
from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, JSON, Numeric, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from epcr_app.models import Base


_BIGINT_IDENTITY = BigInteger().with_variant(Integer, "sqlite")


class NemsisExportAttempt(Base):
    """Export attempt lifecycle tracking."""
    __tablename__ = "epcr_nemsis_export_attempts"

    id: Mapped[int] = mapped_column(_BIGINT_IDENTITY, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    chart_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)

    status: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    failure_type: Mapped[str] = mapped_column(Text, nullable=False, default="none")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    trigger_source: Mapped[str] = mapped_column(Text, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    supersedes_export_id: Mapped[int | None] = mapped_column(
        _BIGINT_IDENTITY,
        ForeignKey("epcr_nemsis_export_attempts.id", ondelete="SET NULL"),
        nullable=True,
    )
    superseded_by_export_id: Mapped[int | None] = mapped_column(
        _BIGINT_IDENTITY,
        ForeignKey("epcr_nemsis_export_attempts.id", ondelete="SET NULL"),
        nullable=True,
    )

    ready_for_export: Mapped[bool] = mapped_column(Boolean, nullable=False)
    blocker_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    compliance_percentage: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    missing_mandatory_fields: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    artifact_file_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifact_mime_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifact_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    artifact_storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifact_checksum_sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    xsd_valid: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    schematron_valid: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    validator_errors: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    validator_warnings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    validator_asset_version: Mapped[str | None] = mapped_column(Text, nullable=True)

    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by_user_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    events: Mapped[list["NemsisExportEvent"]] = relationship(
        "NemsisExportEvent",
        back_populates="attempt",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_nemsis_export_attempts_chart_id", "chart_id"),
        Index("idx_nemsis_export_attempts_tenant_chart", "tenant_id", "chart_id"),
        Index("idx_nemsis_export_attempts_status", "status"),
        Index("idx_nemsis_export_attempts_created_at", "created_at"),
        Index("idx_nemsis_export_attempts_chart_created_desc", "chart_id", "created_at"),
    )


class NemsisExportEvent(Base):
    """Audit-grade event log for export lifecycle transitions."""
    __tablename__ = "epcr_nemsis_export_events"

    id: Mapped[int] = mapped_column(_BIGINT_IDENTITY, primary_key=True, autoincrement=True)
    export_attempt_id: Mapped[int] = mapped_column(
        _BIGINT_IDENTITY,
        ForeignKey("epcr_nemsis_export_attempts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    chart_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)

    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    from_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    to_status: Mapped[str | None] = mapped_column(Text, nullable=True)

    message: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_by_user_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    attempt: Mapped["NemsisExportAttempt"] = relationship(
        "NemsisExportAttempt",
        back_populates="events",
    )

    __table_args__ = (
        Index("idx_nemsis_export_events_attempt_id", "export_attempt_id"),
        Index("idx_nemsis_export_events_chart_id", "chart_id"),
    )
