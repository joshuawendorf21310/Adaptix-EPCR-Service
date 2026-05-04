"""CareGraph — authoritative clinical truth graph model.

CareGraph is the sole source of clinical truth for the EPCR domain.
Every clinical statement is evidence-backed, timestamped, provider-attributed,
tenant-scoped, auditable, replayable, sync-safe, and linked to source data.

Narrative is NEVER stored here as truth. Narrative is derived output only.
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

class CareGraphNodeType(str, Enum):
    PATIENT_STATE = "patient_state"
    SYMPTOM = "symptom"
    PHYSICAL_FINDING = "physical_finding"
    VITAL = "vital"
    IMPRESSION = "impression"
    INTERVENTION = "intervention"
    MEDICATION = "medication"
    DEVICE_STATE = "device_state"
    PROTOCOL_STATE = "protocol_state"
    TRANSPORT_STATE = "transport_state"
    DISPOSITION = "disposition"
    RESPONSE = "response"
    REASSESSMENT = "reassessment"
    OUTCOME = "outcome"


class CareGraphEdgeType(str, Enum):
    CAUSALITY = "causality"
    TIMING = "timing"
    INTENT = "intent"
    EVIDENCE_SUPPORT = "evidence_support"
    CLINICAL_RESPONSE = "clinical_response"
    ESCALATION = "escalation"
    DOWNGRADE = "downgrade"
    PROTOCOL_LINKAGE = "protocol_linkage"
    TERMINOLOGY_BINDING = "terminology_binding"
    EXPORT_MAPPING = "export_mapping"
    REASSESSMENT_DELTA = "reassessment_delta"
    INTERVENTION_RESPONSE = "intervention_response"


class EvidenceStrength(str, Enum):
    CONFIRMED = "confirmed"
    PROBABLE = "probable"
    POSSIBLE = "possible"
    RULED_OUT = "ruled_out"


class SyncSafetyState(str, Enum):
    CLEAN = "clean"
    PENDING_SYNC = "pending_sync"
    CONFLICT_DETECTED = "conflict_detected"
    CONFLICT_RESOLVED = "conflict_resolved"


# ---------------------------------------------------------------------------
# CareGraph Node — every clinical statement
# ---------------------------------------------------------------------------

class CareGraphNode(Base):
    """Single node in the CareGraph clinical truth graph.

    Every clinical statement (symptom, finding, vital, impression, intervention,
    medication, device state, protocol state, transport state, disposition,
    response, reassessment, outcome) is a node.

    Nodes are immutable once confirmed. Mutations create new versions.
    """
    __tablename__ = "epcr_caregraph_nodes"

    id = Column(String(36), primary_key=True, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    node_type = Column(SQLEnum(CareGraphNodeType), nullable=False, index=True)
    label = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Evidence and provenance
    evidence_strength = Column(SQLEnum(EvidenceStrength), default=EvidenceStrength.CONFIRMED, nullable=False)
    evidence_source_ids_json = Column(Text, nullable=True)  # JSON list of source artifact IDs
    provenance_json = Column(Text, nullable=True)  # structured provenance record

    # Terminology bindings
    snomed_code = Column(String(32), nullable=True)
    snomed_display = Column(String(255), nullable=True)
    icd10_code = Column(String(32), nullable=True)
    icd10_display = Column(String(255), nullable=True)
    rxnorm_code = Column(String(32), nullable=True)
    rxnorm_display = Column(String(255), nullable=True)
    nemsis_element = Column(String(64), nullable=True)
    nemsis_value = Column(String(255), nullable=True)

    # Clinical payload (structured JSON for node-type-specific data)
    clinical_payload_json = Column(Text, nullable=True)

    # Attribution
    provider_id = Column(String(255), nullable=False)
    provider_role = Column(String(64), nullable=True)

    # Sync safety
    sync_state = Column(SQLEnum(SyncSafetyState), default=SyncSafetyState.CLEAN, nullable=False)
    local_sequence_number = Column(Integer, nullable=True)  # for offline replay ordering
    device_id = Column(String(64), nullable=True)

    # Timestamps
    occurred_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    outgoing_edges = relationship(
        "CareGraphEdge",
        foreign_keys="CareGraphEdge.source_node_id",
        back_populates="source_node",
        cascade="all, delete-orphan",
    )
    incoming_edges = relationship(
        "CareGraphEdge",
        foreign_keys="CareGraphEdge.target_node_id",
        back_populates="target_node",
        cascade="all, delete-orphan",
    )


# ---------------------------------------------------------------------------
# CareGraph Edge — relationships between clinical statements
# ---------------------------------------------------------------------------

class CareGraphEdge(Base):
    """Directed edge between two CareGraph nodes.

    Edges encode clinical relationships: causality, timing, intent,
    evidence support, clinical response, escalation, downgrade,
    protocol linkage, terminology binding, export mapping relevance,
    reassessment delta, and intervention-to-response relationship.
    """
    __tablename__ = "epcr_caregraph_edges"

    id = Column(String(36), primary_key=True, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    source_node_id = Column(String(36), ForeignKey("epcr_caregraph_nodes.id"), nullable=False, index=True)
    target_node_id = Column(String(36), ForeignKey("epcr_caregraph_nodes.id"), nullable=False, index=True)

    edge_type = Column(SQLEnum(CareGraphEdgeType), nullable=False, index=True)
    weight = Column(Float, nullable=True)  # clinical significance weight
    metadata_json = Column(Text, nullable=True)  # edge-type-specific metadata

    provider_id = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    source_node = relationship("CareGraphNode", foreign_keys=[source_node_id], back_populates="outgoing_edges")
    target_node = relationship("CareGraphNode", foreign_keys=[target_node_id], back_populates="incoming_edges")


# ---------------------------------------------------------------------------
# OPQRST Symptom Engine
# ---------------------------------------------------------------------------

class OPQRSTSymptom(Base):
    """Conditionally instantiated OPQRST symptom structure.

    Triggered for: pain, dyspnea, dizziness, headache, abdominal complaint,
    chest discomfort, neurologic complaint, and other applicable categories.

    OPQRST is linked to a CareGraph symptom node and drives impression/reassessment.
    It is NOT stored as plain text — every field is structured.
    """
    __tablename__ = "epcr_opqrst_symptoms"

    id = Column(String(36), primary_key=True, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    caregraph_node_id = Column(String(36), ForeignKey("epcr_caregraph_nodes.id"), nullable=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    # Trigger context
    symptom_category = Column(String(64), nullable=False)  # pain, dyspnea, dizziness, etc.
    symptom_label = Column(String(255), nullable=False)

    # OPQRST fields — all structured, not free text
    onset_description = Column(String(500), nullable=True)
    onset_time = Column(DateTime(timezone=True), nullable=True)
    onset_sudden = Column(Boolean, nullable=True)

    provocation_factors_json = Column(Text, nullable=True)   # JSON list of provoking factors
    palliation_factors_json = Column(Text, nullable=True)    # JSON list of palliating factors

    quality_descriptors_json = Column(Text, nullable=True)   # JSON list: sharp, dull, pressure, etc.

    radiation_present = Column(Boolean, nullable=True)
    radiation_locations_json = Column(Text, nullable=True)   # JSON list of radiation sites

    region_primary = Column(String(64), nullable=True)
    region_secondary_json = Column(Text, nullable=True)

    severity_scale = Column(Integer, nullable=True)          # 0-10 NRS
    severity_functional_impact = Column(String(255), nullable=True)

    time_duration_minutes = Column(Integer, nullable=True)
    time_progression = Column(String(64), nullable=True)     # constant, intermittent, worsening, improving
    time_prior_episodes = Column(Boolean, nullable=True)
    time_last_episode_at = Column(DateTime(timezone=True), nullable=True)

    associated_symptoms_json = Column(Text, nullable=True)   # JSON list of associated symptom labels
    baseline_comparison = Column(String(255), nullable=True)
    recurrence_pattern = Column(String(255), nullable=True)
    witness_context = Column(String(500), nullable=True)

    # Attribution
    provider_id = Column(String(255), nullable=False)
    documented_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------------------
# Reassessment Delta
# ---------------------------------------------------------------------------

class ReassessmentDelta(Base):
    """Structured reassessment delta comparing two clinical states.

    Links a prior CareGraph node to a reassessment node and captures
    the structured delta: what changed, what improved, what worsened,
    what resolved, and what new findings appeared.
    """
    __tablename__ = "epcr_reassessment_deltas"

    id = Column(String(36), primary_key=True, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    prior_node_id = Column(String(36), ForeignKey("epcr_caregraph_nodes.id"), nullable=False, index=True)
    reassessment_node_id = Column(String(36), ForeignKey("epcr_caregraph_nodes.id"), nullable=False, index=True)

    delta_type = Column(String(64), nullable=False)  # improved, worsened, unchanged, resolved, new
    delta_description = Column(Text, nullable=False)
    delta_payload_json = Column(Text, nullable=True)  # structured delta fields

    intervention_trigger_id = Column(String(36), nullable=True)  # intervention that prompted reassessment
    reassessed_at = Column(DateTime(timezone=True), nullable=False)
    provider_id = Column(String(255), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------------------
# CareGraph Audit Event
# ---------------------------------------------------------------------------

class CareGraphAuditEvent(Base):
    """Immutable audit event for every CareGraph mutation.

    Every node creation, edge creation, node update, and node deletion
    is recorded here with full before/after state, actor, and timestamp.
    """
    __tablename__ = "epcr_caregraph_audit_events"

    id = Column(String(36), primary_key=True, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    entity_type = Column(String(64), nullable=False)  # node, edge
    entity_id = Column(String(36), nullable=False, index=True)
    action = Column(String(64), nullable=False)  # create, update, delete, accept, reject

    actor_id = Column(String(255), nullable=False)
    actor_role = Column(String(64), nullable=True)
    device_id = Column(String(64), nullable=True)

    before_state_json = Column(Text, nullable=True)
    after_state_json = Column(Text, nullable=True)

    performed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    sync_sequence = Column(Integer, nullable=True)  # for offline replay ordering
