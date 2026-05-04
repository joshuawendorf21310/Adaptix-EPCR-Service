"""VAS — Visual Assessment System models.

VAS provides realistic, clinically meaningful, dynamically changing human
assessment visuals. VAS is NOT decorative. Every visual overlay is:
- Bound to a structured CPAE physical finding
- Linked to a CareGraph node
- Versioned for reassessment comparison
- Auditable
- Review-gated for Vision projections

Visual state without CPAE linkage is FORBIDDEN.
Free-floating annotations are FORBIDDEN.
Vision projections bypass review is FORBIDDEN.
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

class PatientModelType(str, Enum):
    ADULT = "adult"
    PEDIATRIC = "pediatric"
    NEONATAL = "neonatal"


class AnatomicalView(str, Enum):
    FRONT = "front"
    POSTERIOR = "posterior"
    LEFT_LATERAL = "left_lateral"
    RIGHT_LATERAL = "right_lateral"
    REGIONAL_ZOOM = "regional_zoom"


class OverlayType(str, Enum):
    BRUISING = "bruising"
    SWELLING = "swelling"
    DEFORMITY = "deformity"
    BURN = "burn"
    BLEEDING = "bleeding"
    CYANOSIS = "cyanosis"
    PALLOR = "pallor"
    MOTTLING = "mottling"
    RESPIRATORY_EFFORT = "respiratory_effort"
    FACIAL_DROOP = "facial_droop"
    PUPILLARY_FINDING = "pupillary_finding"
    PAIN_MAP = "pain_map"
    DEVICE_PLACEMENT = "device_placement"
    SPLINTING = "splinting"
    INTERVENTION_RESPONSE = "intervention_response"


class VASReviewState(str, Enum):
    DIRECT_CONFIRMED = "direct_confirmed"
    VISION_PROPOSED = "vision_proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EDITED_AND_ACCEPTED = "edited_and_accepted"


# ---------------------------------------------------------------------------
# Visual Model Reference
# ---------------------------------------------------------------------------

class VisualModel(Base):
    """Reference definition for a patient visual model variant.

    Defines the canonical patient model (adult/pediatric/neonatal) with
    available views and overlay capabilities.
    """
    __tablename__ = "epcr_visual_models"

    id = Column(String(36), primary_key=True, index=True)
    model_type = Column(String(32), unique=True, nullable=False, index=True)
    display_name = Column(String(128), nullable=False)
    available_views_json = Column(Text, nullable=False)  # JSON list of AnatomicalView values
    supported_overlays_json = Column(Text, nullable=False)  # JSON list of OverlayType values
    is_active = Column(Boolean, nullable=False, default=True)


# ---------------------------------------------------------------------------
# Visual Region Reference
# ---------------------------------------------------------------------------

class VisualRegion(Base):
    """Reference definition for a visual region within a patient model view.

    Maps visual regions to anatomical regions for CPAE linkage.
    """
    __tablename__ = "epcr_visual_regions"

    id = Column(String(36), primary_key=True, index=True)
    model_type = Column(String(32), nullable=False, index=True)
    anatomical_view = Column(String(32), nullable=False, index=True)
    region_code = Column(String(64), nullable=False, index=True)
    display_name = Column(String(128), nullable=False)
    cpae_anatomy_code = Column(String(64), nullable=True)  # maps to CPAE AnatomicalRegion
    default_geometry_json = Column(Text, nullable=True)  # default bounding geometry
    is_active = Column(Boolean, nullable=False, default=True)


# ---------------------------------------------------------------------------
# Visual Overlay — core VAS entity
# ---------------------------------------------------------------------------

class VASOverlay(Base):
    """Clinical visual overlay bound to a structured CPAE finding.

    Every overlay MUST be linked to a PhysicalFinding. Overlays without
    CPAE linkage are rejected by the validation layer.

    Geometry is stored as structured JSON (not free-form SVG paths).
    """
    __tablename__ = "epcr_visual_overlays_v2"

    id = Column(String(36), primary_key=True, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    physical_finding_id = Column(String(36), nullable=False, index=True)  # FK to epcr_physical_findings
    caregraph_node_id = Column(String(36), nullable=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    # Visual model context
    patient_model = Column(String(32), nullable=False)  # PatientModelType
    anatomical_view = Column(String(32), nullable=False)  # AnatomicalView
    overlay_type = Column(String(64), nullable=False)  # OverlayType
    anchor_region = Column(String(64), nullable=False)  # visual region code

    # Geometry (structured JSON: {type, coordinates, width, height, severity_gradient})
    geometry_json = Column(Text, nullable=False)

    # Clinical state
    severity = Column(String(32), nullable=False)
    evolution = Column(String(32), nullable=False, default="new")  # FindingEvolution

    # Review state
    review_state = Column(String(64), nullable=False, default="direct_confirmed")

    # Attribution
    provider_id = Column(String(255), nullable=False)
    evidence_artifact_ids_json = Column(Text, nullable=True)

    # Timestamps
    rendered_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    overlay_versions = relationship("VASOverlayVersion", back_populates="overlay", cascade="all, delete-orphan")
    reassessment_snapshots = relationship("VASReassessmentSnapshot", back_populates="overlay", cascade="all, delete-orphan")
    intervention_response_links = relationship("VASInterventionResponseLink", back_populates="overlay", cascade="all, delete-orphan")
    audit_events = relationship("VASAuditEvent", back_populates="overlay", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# VAS Overlay Version
# ---------------------------------------------------------------------------

class VASOverlayVersion(Base):
    """Versioned snapshot of a VAS overlay for timeline scrubbing.

    Enables before/after comparison and reassessment timeline replay.
    """
    __tablename__ = "epcr_visual_overlay_versions"

    id = Column(String(36), primary_key=True, index=True)
    overlay_id = Column(String(36), ForeignKey("epcr_visual_overlays_v2.id"), nullable=False, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    version_number = Column(Integer, nullable=False)
    geometry_json = Column(Text, nullable=False)
    severity = Column(String(32), nullable=False)
    evolution = Column(String(32), nullable=False)
    snapshot_reason = Column(String(64), nullable=False)  # initial, reassessment, intervention_response
    provider_id = Column(String(255), nullable=False)
    captured_at = Column(DateTime(timezone=True), nullable=False)

    overlay = relationship("VASOverlay", back_populates="overlay_versions")


# ---------------------------------------------------------------------------
# VAS Finding Link (explicit link table)
# ---------------------------------------------------------------------------

class VASFindingLink(Base):
    """Explicit link between a VAS overlay and a CPAE physical finding."""

    __tablename__ = "epcr_visual_finding_links"

    id = Column(String(36), primary_key=True, index=True)
    overlay_id = Column(String(36), nullable=False, index=True)
    finding_id = Column(String(36), nullable=False, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    link_type = Column(String(64), nullable=False, default="primary")  # primary, supporting
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


# ---------------------------------------------------------------------------
# VAS Reassessment Snapshot
# ---------------------------------------------------------------------------

class VASReassessmentSnapshot(Base):
    """Full visual state snapshot at a reassessment point.

    Enables side-by-side comparison of visual state before and after
    interventions or over time.
    """
    __tablename__ = "epcr_visual_reassessment_snapshots"

    id = Column(String(36), primary_key=True, index=True)
    overlay_id = Column(String(36), ForeignKey("epcr_visual_overlays_v2.id"), nullable=False, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    snapshot_type = Column(String(64), nullable=False)  # initial, post_intervention, reassessment, final
    full_state_json = Column(Text, nullable=False)  # complete overlay state at this point
    delta_from_prior_json = Column(Text, nullable=True)  # structured delta from previous snapshot

    provider_id = Column(String(255), nullable=False)
    captured_at = Column(DateTime(timezone=True), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))

    overlay = relationship("VASOverlay", back_populates="reassessment_snapshots")


# ---------------------------------------------------------------------------
# VAS Intervention Response Link
# ---------------------------------------------------------------------------

class VASInterventionResponseLink(Base):
    """Links a VAS overlay change to an intervention response."""

    __tablename__ = "epcr_visual_intervention_response_links"

    id = Column(String(36), primary_key=True, index=True)
    overlay_id = Column(String(36), ForeignKey("epcr_visual_overlays_v2.id"), nullable=False, index=True)
    intervention_id = Column(String(36), nullable=False, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    response_description = Column(Text, nullable=False)
    visual_change_json = Column(Text, nullable=True)  # structured description of visual change
    provider_id = Column(String(255), nullable=False)
    linked_at = Column(DateTime(timezone=True), nullable=False)

    overlay = relationship("VASOverlay", back_populates="intervention_response_links")


# ---------------------------------------------------------------------------
# VAS Projection Review (Vision proposals)
# ---------------------------------------------------------------------------

class VASProjectionReview(Base):
    """Review record for a Vision-proposed VAS overlay projection.

    Vision may propose body-map projections from injury photos or scene photos.
    These proposals MUST be reviewed before becoming accepted VAS overlays.
    """
    __tablename__ = "epcr_visual_projection_reviews"

    id = Column(String(36), primary_key=True, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    vision_artifact_id = Column(String(36), nullable=False, index=True)
    proposed_overlay_json = Column(Text, nullable=False)  # proposed overlay state
    confidence = Column(Float, nullable=False)
    model_version = Column(String(64), nullable=True)

    review_state = Column(String(64), nullable=False, default="pending")  # pending, accepted, rejected, edited_accepted
    reviewer_id = Column(String(255), nullable=True)
    reviewer_notes = Column(Text, nullable=True)
    accepted_overlay_id = Column(String(36), nullable=True)  # FK to VASOverlay if accepted

    proposed_at = Column(DateTime(timezone=True), nullable=False)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    version = Column(Integer, nullable=False, server_default=text("1"))


# ---------------------------------------------------------------------------
# VAS Audit Event
# ---------------------------------------------------------------------------

class VASAuditEvent(Base):
    """Immutable audit event for VAS overlay mutations."""

    __tablename__ = "epcr_visual_audit_events"

    id = Column(String(36), primary_key=True, index=True)
    overlay_id = Column(String(36), ForeignKey("epcr_visual_overlays_v2.id"), nullable=False, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    action = Column(String(64), nullable=False)
    actor_id = Column(String(255), nullable=False)
    before_state_json = Column(Text, nullable=True)
    after_state_json = Column(Text, nullable=True)
    performed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)

    overlay = relationship("VASOverlay", back_populates="audit_events")
