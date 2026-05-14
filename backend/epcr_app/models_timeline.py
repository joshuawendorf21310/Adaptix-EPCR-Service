"""Patient state timeline persistence models.

Immutable append-only state progression tracking for patient care
workflows. Every significant state change is recorded for audit,
compliance, and temporal analysis.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import declarative_base

# Create a separate Base for these models to avoid circular imports
Base = declarative_base()


def utcnow() -> datetime:
    return datetime.now(UTC)


class PatientStateTimeline(Base):
    """Immutable patient state progression record.

    Append-only timeline of all state transitions for a patient within
    an incident. Used for audit trails, compliance verification, and
    temporal analysis of care progression.

    No updates or deletes allowed - this is an immutable log.
    """

    __tablename__ = "patient_state_timeline"

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), nullable=False, index=True)
    incident_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    patient_id = Column(String(36), nullable=True, index=True)

    # State transition
    state_name = Column(String(128), nullable=False, index=True)
    prior_state = Column(String(128), nullable=True)

    # Actor and metadata
    changed_by = Column(String(255), nullable=True)
    metadata_json = Column(Text, nullable=True)

    # Entity context
    entity_type = Column(String(64), nullable=True)
    entity_id = Column(String(36), nullable=True)

    # Timestamps
    changed_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    # No version or deleted_at - immutable records
    # If a record needs to be "corrected", append a correction state instead
