"""CPAE — CareGraph Physical Assessment Engine models.

CPAE replaces static head-to-toe forms with structured, physiology-aware,
anatomically mapped assessment evidence. Every finding is linked to:
- An anatomical region
- A physiological system
- A detection method
- A CareGraph node
- NEMSIS export mapping
- Reassessment delta tracking

CPAE is NOT a generic form. It is NOT checkbox-only.
Findings without anatomy and physiology are FORBIDDEN.
Visual marks without structured findings are FORBIDDEN.
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
    Enum as SQLEnum,
    text,
)
from sqlalchemy.orm import relationship

from epcr_app.models import Base


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class AnatomicalRegion(str, Enum):
    HEAD = "head"
    FACE = "face"
    NECK = "neck"
    ANTERIOR_CHEST = "anterior_chest"
    POSTERIOR_CHEST = "posterior_chest"
    ABDOMEN_RUQ = "abdomen_ruq"
    ABDOMEN_LUQ = "abdomen_luq"
    ABDOMEN_RLQ = "abdomen_rlq"
    ABDOMEN_LLQ = "abdomen_llq"
    ABDOMEN_PERIUMBILICAL = "abdomen_periumbilical"
    PELVIS = "pelvis"
    SPINE_CERVICAL = "spine_cervical"
    SPINE_THORACIC = "spine_thoracic"
    SPINE_LUMBAR = "spine_lumbar"
    SPINE_SACRAL = "spine_sacral"
    BACK = "back"
    LEFT_UPPER_EXTREMITY = "left_upper_extremity"
    RIGHT_UPPER_EXTREMITY = "right_upper_extremity"
    LEFT_LOWER_EXTREMITY = "left_lower_extremity"
    RIGHT_LOWER_EXTREMITY = "right_lower_extremity"
    GENERALIZED_SKIN = "generalized_skin"
    REGIONAL_ZOOM = "regional_zoom"


class PhysiologicSystem(str, Enum):
    NEUROLOGICAL = "neurological"
    RESPIRATORY = "respiratory"
    CARDIOVASCULAR = "cardiovascular"
    MUSCULOSKELETAL = "musculoskeletal"
    INTEGUMENTARY = "integumentary"
    GASTROINTESTINAL = "gastrointestinal"
    GENITOURINARY = "genitourinary"
    ENDOCRINE = "endocrine"
    TRAUMA = "trauma"


class FindingClass(str, Enum):
    INSPECTION = "inspection"
    PALPATION = "palpation"
    AUSCULTATION = "auscultation"
    NEUROLOGICAL_EXAM = "neurological_exam"
    PAIN_FINDING = "pain_finding"
    INJURY_FINDING = "injury_finding"
    DEFORMITY = "deformity"
    SWELLING = "swelling"
    BLEEDING = "bleeding"
    BURN = "burn"
    PULSE = "pulse"
    CAPILLARY_REFILL = "capillary_refill"
    TENDERNESS = "tenderness"
    RIGIDITY = "rigidity"
    CREPITUS = "crepitus"
    DEVICE_ASSOCIATED = "device_associated"


class Laterality(str, Enum):
    LEFT = "left"
    RIGHT = "right"
    BILATERAL = "bilateral"
    MIDLINE = "midline"
    NOT_APPLICABLE = "not_applicable"


class FindingSeverity(str, Enum):
    ABSENT = "absent"
    MILD = "mild"
    MODERATE = "moderate"
    SEVERE = "severe"
    CRITICAL = "critical"


class CPAEReviewState(str, Enum):
    DIRECT_CONFIRMED = "direct_confirmed"
    VISION_PROPOSED = "vision_proposed"
    SMART_TEXT_PROPOSED = "smart_text_proposed"
    VOICE_PROPOSED = "voice_proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EDITED_AND_ACCEPTED = "edited_and_accepted"


# ---------------------------------------------------------------------------
# Assessment Region Reference
# ---------------------------------------------------------------------------

class AssessmentRegion(Base):
    """Reference table for anatomical assessment regions.

    Defines the canonical set of anatomical regions supported by CPAE,
    including display metadata and NEMSIS mapping context.
    """
    __tablename__ = "epcr_assessment_regions"

    id = Column(String(36), primary_key=True, index=True)
    region_code = Column(String(64), unique=True, nullable=False, index=True)
    display_name = Column(String(128), nullable=False)
    parent_region_code = Column(String(64), nullable=True)
    supports_laterality = Column(Boolean, nullable=False, default=False)
    nemsis_body_site_code = Column(String(32), nullable=True)
    snomed_code = Column(String(32), nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)


class PhysiologicSystemRef(Base):
    """Reference table for physiological systems supported by CPAE."""

    __tablename__ = "epcr_physiologic_systems"

    id = Column(String(36), primary_key=True, index=True)
    system_code = Column(String(64), unique=True, nullable=False, index=True)
    display_name = Column(String(128), nullable=False)
    nemsis_section_hint = Column(String(64), nullable=True)
    snomed_code = Column(String(32), nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)


# ---------------------------------------------------------------------------
# Physical Finding — core CPAE entity
# ---------------------------------------------------------------------------

class PhysicalFinding(Base):
    """Structured physical finding linked to anatomy, physiology, and CareGraph.

    This is the core CPAE entity. Every finding must have:
    - Anatomical region
    - Physiological system
    - Finding class (inspection, palpation, auscultation, etc.)
    - Severity
    - Detection method
    - Provider attribution
    - Timestamp
    - CareGraph node linkage

    Findings without anatomy and physiology are REJECTED by the validation layer.
    """
    __tablename__ = "epcr_physical_findings"

    id = Column(String(36), primary_key=True, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    caregraph_node_id = Column(String(36), nullable=True, index=True)  # FK to CareGraph node

    # Anatomical and physiological context
    anatomy = Column(String(64), nullable=False, index=True)  # AnatomicalRegion value
    physiologic_system = Column(String(64), nullable=False, index=True)  # PhysiologicSystem value
    finding_class = Column(String(64), nullable=False)  # FindingClass value
    laterality = Column(String(32), nullable=True)  # Laterality value
    severity = Column(String(32), nullable=False)  # FindingSeverity value

    # Finding content
    finding_label = Column(String(255), nullable=False)
    finding_description = Column(Text, nullable=True)
    characteristics_json = Column(Text, nullable=True)  # structured finding characteristics

    # Detection method
    detection_method = Column(String(64), nullable=False)  # direct, palpation, auscultation, device, vision, voice

    # Review state (Vision/SmartText proposals require review before acceptance)
    review_state = Column(String(64), nullable=False, default="direct_confirmed")

    # Terminology bindings
    snomed_code = Column(String(32), nullable=True)
    snomed_display = Column(String(255), nullable=True)
    nemsis_exam_element = Column(String(64), nullable=True)
    nemsis_exam_value = Column(String(255), nullable=True)

    # Contradiction detection
    has_contradiction = Column(Boolean, nullable=False, default=False)
    contradiction_detail = Column(Text, nullable=True)

    # Attribution
    provider_id = Column(String(255), nullable=False)
    source_artifact_ids_json = Column(Text, nullable=True)  # Vision/SmartText source artifacts

    # Timestamps
    observed_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    characteristics = relationship("FindingCharacteristic", back_populates="finding", cascade="all, delete-orphan")
    reassessments = relationship("FindingReassessment", back_populates="finding", cascade="all, delete-orphan")
    evidence_links = relationship("FindingEvidenceLink", back_populates="finding", cascade="all, delete-orphan")
    intervention_links = relationship("FindingInterventionLink", back_populates="finding", cascade="all, delete-orphan")
    response_links = relationship("FindingResponseLink", back_populates="finding", cascade="all, delete-orphan")
    nemsis_links = relationship("FindingNemsisLink", back_populates="finding", cascade="all, delete-orphan")
    audit_events = relationship("FindingAuditEvent", back_populates="finding", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# Finding Characteristics
# ---------------------------------------------------------------------------

class FindingCharacteristic(Base):
    """Structured characteristic of a physical finding.

    Examples: burn degree, wound depth, deformity type, pulse quality,
    capillary refill time, neurological deficit type, etc.
    """
    __tablename__ = "epcr_finding_characteristics"

    id = Column(String(36), primary_key=True, index=True)
    finding_id = Column(String(36), ForeignKey("epcr_physical_findings.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    characteristic_key = Column(String(64), nullable=False)
    characteristic_value = Column(String(255), nullable=False)
    characteristic_unit = Column(String(32), nullable=True)
    snomed_code = Column(String(32), nullable=True)

    finding = relationship("PhysicalFinding", back_populates="characteristics")


# ---------------------------------------------------------------------------
# Finding Reassessment
# ---------------------------------------------------------------------------

class FindingReassessment(Base):
    """Reassessment record for a physical finding.

    Captures the evolution of a finding over time: improved, worsened,
    unchanged, resolved. Links to the reassessment CareGraph node.
    """
    __tablename__ = "epcr_finding_reassessments"

    id = Column(String(36), primary_key=True, index=True)
    finding_id = Column(String(36), ForeignKey("epcr_physical_findings.id"), nullable=False, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    caregraph_reassessment_node_id = Column(String(36), nullable=True, index=True)

    evolution = Column(String(32), nullable=False)  # improving, worsening, unchanged, resolved
    severity_at_reassessment = Column(String(32), nullable=True)
    description = Column(Text, nullable=True)
    characteristics_json = Column(Text, nullable=True)

    intervention_trigger_id = Column(String(36), nullable=True)
    provider_id = Column(String(255), nullable=False)
    reassessed_at = Column(DateTime(timezone=True), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    finding = relationship("PhysicalFinding", back_populates="reassessments")


# ---------------------------------------------------------------------------
# Finding Evidence Link
# ---------------------------------------------------------------------------

class FindingEvidenceLink(Base):
    """Link between a physical finding and its supporting evidence."""

    __tablename__ = "epcr_finding_evidence_links"

    id = Column(String(36), primary_key=True, index=True)
    finding_id = Column(String(36), ForeignKey("epcr_physical_findings.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    evidence_type = Column(String(64), nullable=False)  # vision_artifact, vital, opqrst, device_reading
    evidence_id = Column(String(36), nullable=False, index=True)
    evidence_description = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)

    finding = relationship("PhysicalFinding", back_populates="evidence_links")


# ---------------------------------------------------------------------------
# Finding Intervention Link
# ---------------------------------------------------------------------------

class FindingInterventionLink(Base):
    """Link between a physical finding and an intervention it prompted."""

    __tablename__ = "epcr_finding_intervention_links"

    id = Column(String(36), primary_key=True, index=True)
    finding_id = Column(String(36), ForeignKey("epcr_physical_findings.id"), nullable=False, index=True)
    intervention_id = Column(String(36), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    link_rationale = Column(Text, nullable=True)

    finding = relationship("PhysicalFinding", back_populates="intervention_links")


# ---------------------------------------------------------------------------
# Finding Response Link
# ---------------------------------------------------------------------------

class FindingResponseLink(Base):
    """Link between a physical finding and the clinical response observed."""

    __tablename__ = "epcr_finding_response_links"

    id = Column(String(36), primary_key=True, index=True)
    finding_id = Column(String(36), ForeignKey("epcr_physical_findings.id"), nullable=False, index=True)
    response_node_id = Column(String(36), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    response_description = Column(Text, nullable=True)

    finding = relationship("PhysicalFinding", back_populates="response_links")


# ---------------------------------------------------------------------------
# Finding NEMSIS Link
# ---------------------------------------------------------------------------

class FindingNemsisLink(Base):
    """NEMSIS export mapping for a physical finding.

    Maps a structured physical finding to the correct NEMSIS eExam element,
    value, and XML path for export inclusion.
    """
    __tablename__ = "epcr_finding_nemsis_links"

    id = Column(String(36), primary_key=True, index=True)
    finding_id = Column(String(36), ForeignKey("epcr_physical_findings.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    nemsis_section = Column(String(32), nullable=False)  # eExam
    nemsis_element = Column(String(64), nullable=False)  # e.g., eExam.01
    nemsis_value = Column(String(255), nullable=False)
    xml_path = Column(String(255), nullable=True)
    export_ready = Column(Boolean, nullable=False, default=False)
    export_blocker_reason = Column(Text, nullable=True)

    finding = relationship("PhysicalFinding", back_populates="nemsis_links")


# ---------------------------------------------------------------------------
# Finding Audit Event
# ---------------------------------------------------------------------------

class FindingAuditEvent(Base):
    """Immutable audit event for physical finding mutations."""

    __tablename__ = "epcr_finding_audit_events"

    id = Column(String(36), primary_key=True, index=True)
    finding_id = Column(String(36), ForeignKey("epcr_physical_findings.id"), nullable=False, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    action = Column(String(64), nullable=False)
    actor_id = Column(String(255), nullable=False)
    before_state_json = Column(Text, nullable=True)
    after_state_json = Column(Text, nullable=True)
    performed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)

    finding = relationship("PhysicalFinding", back_populates="audit_events")
