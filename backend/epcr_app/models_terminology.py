"""Terminology Fabric — four distinct but linked layers.

The architecture explicitly separates:
- SNOMED CT: clinical meaning (symptoms, findings, impressions, assessments)
- ICD-10-CM: impression classification and billing support
- RxNorm: medication normalization
- NEMSIS: regulated export mapping

These layers are NEVER collapsed into a single generic code field.
Provenance for code suggestions is NEVER lost.
Stale static code tables without version metadata are FORBIDDEN.
Terminology suggestion bypass review where clinical truth is affected is FORBIDDEN.
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
# SNOMED CT Reference
# ---------------------------------------------------------------------------

class SnomedConcept(Base):
    """SNOMED CT concept reference.

    Used for: symptoms, findings, impressions, assessments, body findings,
    continuity semantics.

    NOT used for: billing, NEMSIS export.
    """
    __tablename__ = "ref_snomed_concepts"

    id = Column(String(36), primary_key=True, index=True)
    concept_id = Column(String(32), unique=True, nullable=False, index=True)
    fsn = Column(String(512), nullable=False)  # Fully Specified Name
    preferred_term = Column(String(512), nullable=False)
    semantic_tag = Column(String(128), nullable=True)  # (disorder), (finding), (procedure), etc.
    hierarchy_code = Column(String(32), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    version_date = Column(String(32), nullable=False)  # SNOMED release date
    source_artifact_version = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


# ---------------------------------------------------------------------------
# ICD-10-CM Reference
# ---------------------------------------------------------------------------

class ICD10Code(Base):
    """ICD-10-CM code reference.

    Used for: impression classification, billing support, reporting,
    denial-risk modeling, coding review.

    NOT used as: NEMSIS export truth, clinical terminology truth.
    """
    __tablename__ = "ref_icd10_codes"

    id = Column(String(36), primary_key=True, index=True)
    code = Column(String(16), unique=True, nullable=False, index=True)
    description = Column(String(512), nullable=False)
    category_code = Column(String(8), nullable=True, index=True)
    category_description = Column(String(512), nullable=True)
    is_billable = Column(Boolean, nullable=False, default=True)
    is_active = Column(Boolean, nullable=False, default=True)
    fiscal_year = Column(String(16), nullable=False)
    source_artifact_version = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


# ---------------------------------------------------------------------------
# RxNorm Reference
# ---------------------------------------------------------------------------

class RxNormConcept(Base):
    """RxNorm concept reference.

    Used for: administered medications, home medications, medication search,
    dose normalization, infusion standardization, label recognition.

    NOT used for: NEMSIS export (NEMSIS has its own medication value sets).
    """
    __tablename__ = "ref_rxnorm_concepts"

    id = Column(String(36), primary_key=True, index=True)
    rxcui = Column(String(16), unique=True, nullable=False, index=True)
    name = Column(String(512), nullable=False)
    tty = Column(String(32), nullable=True)  # term type: IN, BN, SCD, SBD, etc.
    is_active = Column(Boolean, nullable=False, default=True)
    version_date = Column(String(32), nullable=False)
    source_artifact_version = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


# ---------------------------------------------------------------------------
# NEMSIS Value Set Reference
# ---------------------------------------------------------------------------

class NemsisValueSet(Base):
    """NEMSIS 3.5.1 value set reference.

    Used for: regulated export, export readiness, blockers,
    regex constraints, cardinality constraints, XML-valid output.

    NOT used as: clinical terminology truth, billing truth.
    """
    __tablename__ = "ref_nemsis_value_sets"

    id = Column(String(36), primary_key=True, index=True)
    element_number = Column(String(32), nullable=False, index=True)  # e.g., eSituation.11
    element_name = Column(String(255), nullable=False)
    code = Column(String(64), nullable=False, index=True)
    display = Column(String(512), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    nemsis_version = Column(String(16), nullable=False, default="3.5.1")
    source_artifact_version = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


# ---------------------------------------------------------------------------
# NEMSIS Regex Rules
# ---------------------------------------------------------------------------

class NemsisRegexRule(Base):
    """NEMSIS 3.5.1 regex validation rule for an element."""

    __tablename__ = "ref_nemsis_regex_rules"

    id = Column(String(36), primary_key=True, index=True)
    element_number = Column(String(32), nullable=False, unique=True, index=True)
    element_name = Column(String(255), nullable=False)
    regex_pattern = Column(String(512), nullable=False)
    description = Column(Text, nullable=True)
    nemsis_version = Column(String(16), nullable=False, default="3.5.1")
    source_artifact_version = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


# ---------------------------------------------------------------------------
# Impression Binding
# ---------------------------------------------------------------------------

class ImpressionBinding(Base):
    """Multi-layer terminology binding for a clinical impression.

    An impression may bind to:
    - Internal Adaptix clinical label
    - SNOMED CT concept
    - ICD-10-CM code
    - NEMSIS-compatible export value
    - Evidence links
    - Confidence state
    - Provenance state
    - User-selected or AI-suggested status

    ICD-10 is NOT NEMSIS export truth.
    SNOMED is NOT billing truth.
    NEMSIS is NOT clinical terminology truth.
    AI-suggested impressions MUST NOT become truth without user acceptance.
    """
    __tablename__ = "epcr_impression_bindings"

    id = Column(String(36), primary_key=True, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    caregraph_node_id = Column(String(36), nullable=True, index=True)

    # Impression classification
    impression_class = Column(String(64), nullable=False)  # primary, secondary, differential, ruled_out, billing
    adaptix_label = Column(String(255), nullable=False)

    # SNOMED binding
    snomed_code = Column(String(32), nullable=True)
    snomed_display = Column(String(512), nullable=True)
    snomed_confidence = Column(String(32), nullable=True)  # confirmed, probable, possible

    # ICD-10-CM binding
    icd10_code = Column(String(16), nullable=True)
    icd10_display = Column(String(512), nullable=True)
    icd10_confidence = Column(String(32), nullable=True)

    # NEMSIS binding
    nemsis_element = Column(String(64), nullable=True)
    nemsis_value = Column(String(64), nullable=True)
    nemsis_export_valid = Column(Boolean, nullable=True)
    nemsis_export_blocker = Column(Text, nullable=True)

    # Evidence and provenance
    evidence_node_ids_json = Column(Text, nullable=True)
    provenance_json = Column(Text, nullable=True)

    # Review state
    is_ai_suggested = Column(Boolean, nullable=False, default=False)
    review_state = Column(String(64), nullable=False, default="direct_confirmed")
    reviewer_id = Column(String(255), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)

    provider_id = Column(String(255), nullable=False)
    documented_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------------------
# Differential Impression
# ---------------------------------------------------------------------------

class DifferentialImpression(Base):
    """Differential impression with evidence and ruling-out state."""

    __tablename__ = "epcr_differential_impressions"

    id = Column(String(36), primary_key=True, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    impression_binding_id = Column(String(36), nullable=True, index=True)

    adaptix_label = Column(String(255), nullable=False)
    snomed_code = Column(String(32), nullable=True)
    icd10_code = Column(String(16), nullable=True)

    differential_state = Column(String(64), nullable=False, default="active")  # active, ruled_out, confirmed
    ruling_out_evidence_json = Column(Text, nullable=True)
    ruling_out_reason = Column(Text, nullable=True)

    provider_id = Column(String(255), nullable=False)
    documented_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------------------
# Terminology Version Metadata
# ---------------------------------------------------------------------------

class TerminologyVersionMetadata(Base):
    """Version metadata for loaded terminology artifacts.

    Tracks which version of each terminology system is loaded,
    preventing stale static code tables.
    """
    __tablename__ = "ref_terminology_versions"

    id = Column(String(36), primary_key=True, index=True)
    terminology_system = Column(String(32), nullable=False, index=True)  # snomed, icd10, rxnorm, nemsis
    version_identifier = Column(String(64), nullable=False)
    release_date = Column(String(32), nullable=True)
    record_count = Column(Integer, nullable=True)
    is_current = Column(Boolean, nullable=False, default=True)
    loaded_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    loaded_by = Column(String(255), nullable=True)
    source_artifact_path = Column(String(512), nullable=True)
