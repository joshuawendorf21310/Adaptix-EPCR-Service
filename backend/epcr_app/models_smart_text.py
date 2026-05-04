"""Smart Text Box System — structured-aware clinical composition surface.

The smart text box is NOT a free-text field. It is a structured-aware
clinical composition surface that:
- Expands shorthand into structured clinical entities
- Recognizes symptoms, interventions, medications, impressions, facilities
- Detects contradictions in real-time
- Proposes structured extraction for review
- Preserves raw entry
- Never silently mutates authoritative chart data

Every proposal must include:
- Raw source text
- Parsed entity
- Target chart object
- Confidence
- Suggested binding
- Reviewer action
- Acceptance state
- Audit record
"""
from __future__ import annotations

from datetime import datetime, UTC
from enum import Enum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import relationship

from epcr_app.models import Base


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class SmartTextEntityType(str, Enum):
    SYMPTOM = "symptom"
    INTERVENTION = "intervention"
    MEDICATION = "medication"
    IMPRESSION = "impression"
    FACILITY = "facility"
    ADDRESS = "address"
    TIMESTAMP = "timestamp"
    PROCEDURE = "procedure"
    VITAL = "vital"
    FINDING = "finding"
    CONTRADICTION = "contradiction"


class SmartTextProposalState(str, Enum):
    PENDING_REVIEW = "pending_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EDITED_AND_ACCEPTED = "edited_and_accepted"
    IGNORED = "ignored"


# ---------------------------------------------------------------------------
# Smart Text Session
# ---------------------------------------------------------------------------

class SmartTextSession(Base):
    """A smart text composition session for a chart.

    Tracks the raw text input, extracted entities, and proposal state.
    Raw entry is always preserved — never overwritten.
    """
    __tablename__ = "epcr_smart_text_sessions"

    id = Column(String(36), primary_key=True, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    # Raw text — always preserved
    raw_text = Column(Text, nullable=False)
    text_source = Column(String(64), nullable=False)  # manual, voice_cleanup, dictation

    # Session context
    context_section = Column(String(64), nullable=True)  # chief_complaint, narrative, assessment, etc.
    provider_id = Column(String(255), nullable=False)

    # Processing state
    processing_status = Column(String(32), nullable=False, default="pending")
    processed_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    proposals = relationship("SmartTextProposal", back_populates="session", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# Smart Text Proposal
# ---------------------------------------------------------------------------

class SmartTextProposal(Base):
    """A structured extraction proposal from smart text analysis.

    Smart text may propose structure. It must NOT silently mutate
    authoritative chart data. Every proposal requires explicit acceptance.
    """
    __tablename__ = "epcr_smart_text_proposals"

    id = Column(String(36), primary_key=True, index=True)
    session_id = Column(String(36), ForeignKey("epcr_smart_text_sessions.id"), nullable=False, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    # Source
    raw_source_text = Column(Text, nullable=False)  # exact text span that generated this proposal
    span_start = Column(Integer, nullable=True)  # character offset in raw_text
    span_end = Column(Integer, nullable=True)

    # Parsed entity
    entity_type = Column(String(64), nullable=False)  # SmartTextEntityType
    entity_label = Column(String(255), nullable=False)
    entity_payload_json = Column(Text, nullable=False)  # structured entity data

    # Target chart object
    target_chart_field = Column(String(128), nullable=True)  # e.g., "chief_complaint", "medications"
    target_chart_section = Column(String(64), nullable=True)

    # Confidence and binding
    confidence = Column(Float, nullable=False)
    suggested_binding_json = Column(Text, nullable=True)  # terminology binding suggestion

    # Review state — NEVER auto-accepted
    proposal_state = Column(String(64), nullable=False, default="pending_review")
    reviewer_id = Column(String(255), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    reviewer_notes = Column(Text, nullable=True)
    edited_entity_json = Column(Text, nullable=True)  # if edited before acceptance

    # Accepted chart record (set after acceptance)
    accepted_chart_record_id = Column(String(36), nullable=True)
    accepted_chart_record_type = Column(String(64), nullable=True)

    # Contradiction detection
    is_contradiction = Column(Boolean, nullable=False, default=False)
    contradiction_detail = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))

    session = relationship("SmartTextSession", back_populates="proposals")


# ---------------------------------------------------------------------------
# Smart Text Audit Record
# ---------------------------------------------------------------------------

class SmartTextAuditRecord(Base):
    """Immutable audit record for smart text proposal actions."""

    __tablename__ = "epcr_smart_text_audit"

    id = Column(String(36), primary_key=True, index=True)
    proposal_id = Column(String(36), ForeignKey("epcr_smart_text_proposals.id"), nullable=False, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    action = Column(String(64), nullable=False)  # accept, reject, edit_and_accept, ignore
    actor_id = Column(String(255), nullable=False)
    before_state = Column(String(64), nullable=True)
    after_state = Column(String(64), nullable=False)
    notes = Column(Text, nullable=True)

    performed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


# ---------------------------------------------------------------------------
# Finding Methods (epcr_finding_methods — required by spec)
# ---------------------------------------------------------------------------

class FindingMethod(Base):
    """Reference table for finding detection methods.

    Defines the canonical set of methods by which physical findings
    can be detected: direct observation, palpation, auscultation,
    device reading, Vision proposal, voice proposal, smart text proposal.
    """
    __tablename__ = "epcr_finding_methods"

    id = Column(String(36), primary_key=True, index=True)
    method_code = Column(String(64), unique=True, nullable=False, index=True)
    display_name = Column(String(128), nullable=False)
    requires_review = Column(Boolean, nullable=False, default=False)  # Vision/SmartText require review
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)
