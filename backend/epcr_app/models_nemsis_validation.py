"""NEMSIS validation persistence models.

Stores validation results, errors, warnings, and export job state
for NEMSIS 3.5.1 compliance validation and export blocking logic.
"""
from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import declarative_base, relationship

# Create a separate Base for these models to avoid circular imports
Base = declarative_base()


def utcnow() -> datetime:
    return datetime.now(UTC)


class ValidationStatus(str, Enum):
    """Validation result status enumeration."""

    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"


class ValidationSeverity(str, Enum):
    """Severity of validation finding."""

    ERROR = "error"
    WARNING = "warning"


class ExportJobStatus(str, Enum):
    """NEMSIS export job status enumeration."""

    PENDING = "pending"
    VALIDATING = "validating"
    VALIDATION_FAILED = "validation_failed"
    EXPORTING = "exporting"
    EXPORTED = "exported"
    FAILED = "failed"


class NEMSISValidationResult(Base):
    """Stores NEMSIS validation output for an incident/chart.

    Each validation run creates a new record. Supports validation
    history tracking and export blocking logic.
    """

    __tablename__ = "nemsis_validation_results"

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), nullable=False, index=True)
    incident_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)

    validation_status = Column(String(32), nullable=False, default="pending")
    errors_json = Column(Text, nullable=True)
    warnings_json = Column(Text, nullable=True)
    validation_summary_json = Column(Text, nullable=True)

    # Cached counts for quick filtering
    error_count = Column(Integer, nullable=False, default=0)
    warning_count = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    created_by_user_id = Column(String(255), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)

    errors = relationship(
        "NEMSISValidationError",
        backref="validation_result",
        cascade="all, delete-orphan",
        order_by="NEMSISValidationError.created_at",
    )


class NEMSISValidationError(Base):
    """Detailed NEMSIS validation error or warning.

    Each validation finding is stored as a separate row for
    granular query and filtering.
    """

    __tablename__ = "nemsis_validation_errors"

    id = Column(String(36), primary_key=True)
    result_id = Column(
        String(36),
        ForeignKey("nemsis_validation_results.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(String(36), nullable=False, index=True)

    element_id = Column(String(128), nullable=True, index=True)
    error_code = Column(String(64), nullable=True, index=True)
    error_message = Column(Text, nullable=False)
    severity = Column(String(32), nullable=False)

    field_path = Column(String(512), nullable=True)
    current_value = Column(Text, nullable=True)
    expected_value = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)


class NEMSISExportJob(Base):
    """NEMSIS export job tracking.

    Tracks export lifecycle from validation through XML generation
    and S3 storage. Blocks exports if validation fails.
    """

    __tablename__ = "nemsis_export_jobs"

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), nullable=False, index=True)
    incident_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)

    # Link to latest validation result
    validation_result_id = Column(
        String(36),
        ForeignKey("nemsis_validation_results.id"),
        nullable=True,
        index=True,
    )

    status = Column(String(32), nullable=False, default="pending", index=True)

    s3_bucket = Column(String(255), nullable=True)
    s3_key = Column(String(1024), nullable=True)
    file_size_bytes = Column(BigInteger, nullable=True)
    sha256 = Column(String(64), nullable=True)

    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)

    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    failed_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    created_by_user_id = Column(String(255), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)

    validation_result = relationship(
        "NEMSISValidationResult",
        foreign_keys=[validation_result_id],
        uselist=False,
    )
