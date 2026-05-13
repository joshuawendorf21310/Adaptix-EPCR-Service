"""ePCR domain models: ePCR charts, NEMSIS 3.5.1 compliance, clinical data.

This module defines the SQLAlchemy ORM models for the epcr domain,
including chart lifecycle, clinical vitals, assessments, and NEMSIS 3.5.1
compliance tracking for emergency patient care records.
"""
from datetime import datetime, UTC
from enum import Enum
from sqlalchemy import (
    CheckConstraint,
    Column,
    String,
    DateTime,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    ForeignKey,
    Boolean,
    Float,
    Enum as SQLEnum,
    text,
    event,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class ChartStatus(str, Enum):
    """ePCR chart lifecycle status enumeration.
    
    Represents the state of an ePCR chart as it progresses through
    documentation, review, and finalization stages.
    """
    NEW = "new"
    IN_PROGRESS = "in_progress"
    UNDER_REVIEW = "under_review"
    FINALIZED = "finalized"
    LOCKED = "locked"


class ComplianceStatus(str, Enum):
    """NEMSIS 3.5.1 compliance status enumeration.
    
    Indicates the level of compliance with NEMSIS 3.5.1 mandatory fields
    required for a patient care report to be submission-ready.
    """
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    PARTIALLY_COMPLIANT = "partially_compliant"
    FULLY_COMPLIANT = "fully_compliant"
    NON_COMPLIANT = "non_compliant"


class FieldSource(str, Enum):
    """Source of NEMSIS field values enumeration.
    
    Tracks the provenance of data entered into NEMSIS fields to support
    audit trails and understanding how each value was populated.
    """
    MANUAL = "manual"
    OCR = "ocr"
    DEVICE = "device"
    SYSTEM = "system"


class ReviewState(str, Enum):
    """Review state for visual or assisted clinical findings."""

    DIRECT_CONFIRMED = "direct_confirmed"
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EDITED_AND_ACCEPTED = "edited_and_accepted"


class FindingEvolution(str, Enum):
    """Progression state for reassessment-aware clinical findings."""

    NEW = "new"
    IMPROVING = "improving"
    WORSENING = "worsening"
    UNCHANGED = "unchanged"
    RESOLVED = "resolved"


class ArSessionStatus(str, Enum):
    """Lifecycle state for an ARCOS session."""

    ACTIVE = "active"
    COMPLETED = "completed"
    ABORTED = "aborted"


class AddressValidationState(str, Enum):
    """Validation state for structured scene and destination addresses."""

    NEEDS_REVIEW = "needs_review"
    MANUAL_VERIFIED = "manual_verified"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    VALIDATED = "validated"


class ProtocolFamily(str, Enum):
    """Supported deterministic protocol guidance families."""

    ACLS = "acls"
    PALS = "pals"
    NRP = "nrp"
    TPATC = "tpatc"
    GENERAL = "general"


class InterventionExportState(str, Enum):
    """Export state for intervention mapping into downstream outputs."""

    PENDING_MAPPING = "pending_mapping"
    MAPPED_READY = "mapped_ready"
    BLOCKED = "blocked"


class ClinicalNoteReviewState(str, Enum):
    """Review state for captured clinical text and vision-assisted intake."""

    PENDING_REVIEW = "pending_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ProtocolRecommendationState(str, Enum):
    """Lifecycle state of a protocol recommendation."""

    OPEN = "open"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"


class DerivedOutputType(str, Enum):
    """Derived output families generated from CareGraph truth."""

    NARRATIVE = "narrative"
    HANDOFF = "handoff"
    CLINICAL_SUMMARY = "clinical_summary"


class AgencyProfile(Base):
    """Agency onboarding/provisioning record used by incident numbering."""

    __tablename__ = "agency_profiles"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "agency_code",
            name="uq_agency_profiles_tenant_agency_code",
        ),
    )

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    agency_code = Column(String(12), nullable=False, index=True)
    agency_name = Column(String(255), nullable=False)
    agency_type = Column(String(64), nullable=True)
    state = Column(String(8), nullable=True)
    operational_mode = Column(String(64), nullable=True)
    billing_mode = Column(String(64), nullable=True)
    numbering_policy_json = Column(Text, nullable=False, default="{}")
    activated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)


class EpcrNumberingSequence(Base):
    """Tenant + agency + year-scoped incident sequence state."""

    __tablename__ = "epcr_numbering_sequences"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "agency_code",
            "sequence_year",
            name="uq_epcr_numbering_sequences_scope",
        ),
    )

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    agency_code = Column(String(12), nullable=False, index=True)
    sequence_year = Column(Integer, nullable=False)
    next_incident_sequence = Column(Integer, nullable=False, server_default=text("1"))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


class Chart(Base):
    """ePCR chart model: single patient encounter record.
    
    Represents a complete emergency patient care report for a single call,
    including patient demographics, incident context, clinical findings,
    and NEMSIS 3.5.1 compliance status.
    
    Attributes:
        id: Unique chart identifier (UUID v4).
        tenant_id: Tenant identifier for multi-tenant isolation.
        call_number: Dispatch/call identifier (unique per tenant).
        patient_id: Optional patient identifier (may be unknown at creation).
        incident_type: Type of incident (medical, trauma, behavioral, other).
        status: Chart lifecycle status (new, in_progress, under_review, finalized, locked).
        created_by_user_id: User ID of chart creator.
        created_at: Timestamp when chart was created (UTC).
        updated_at: Timestamp when chart was last modified (UTC).
        finalized_at: Timestamp when chart was finalized (UTC), NULL if not finalized.
        deleted_at: Soft delete timestamp (UTC), NULL if active.
        vitals: List of Vitals records for this chart.
        assessment: Assessment findings for this chart.
        nemsis_mappings: List of NemsisMappingRecord for field tracking.
        nemsis_compliance: NemsisCompliance compliance tracking record.
    """
    __tablename__ = "epcr_charts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "call_number",
            name="uq_epcr_charts_tenant_call_number",
        ),
    )

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    call_number = Column(String(50), nullable=False, index=True)
    agency_code = Column(String(12), nullable=True, index=True)
    incident_year = Column(Integer, nullable=True)
    incident_sequence = Column(Integer, nullable=True)
    response_sequence = Column(Integer, nullable=True)
    pcr_sequence = Column(Integer, nullable=True)
    billing_sequence = Column(Integer, nullable=True)
    incident_number = Column(String(64), nullable=True, index=True)
    response_number = Column(String(72), nullable=True, index=True)
    pcr_number = Column(String(76), nullable=True, index=True)
    billing_case_number = Column(String(80), nullable=True, index=True)
    cad_incident_number = Column(String(64), nullable=True)
    external_incident_number = Column(String(64), nullable=True)
    patient_id = Column(String(36), nullable=True)
    incident_type = Column(String(50), default="medical", nullable=False)
    status = Column(SQLEnum(ChartStatus), default=ChartStatus.NEW, nullable=False)
    created_by_user_id = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    finalized_at = Column(DateTime(timezone=True), nullable=True)
    narrative = Column(Text, nullable=True)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)
    
    vitals = relationship("Vitals", back_populates="chart", cascade="all, delete-orphan")
    assessment = relationship("Assessment", back_populates="chart", uselist=False, cascade="all, delete-orphan")
    findings = relationship("AssessmentFinding", back_populates="chart", cascade="all, delete-orphan")
    visual_overlays = relationship("VisualOverlay", back_populates="chart", cascade="all, delete-orphan")
    ar_sessions = relationship("ArSession", back_populates="chart", cascade="all, delete-orphan")
    patient_profile = relationship("PatientProfile", back_populates="chart", uselist=False, cascade="all, delete-orphan")
    scene_address = relationship("ChartAddress", back_populates="chart", uselist=False, cascade="all, delete-orphan")
    medications = relationship("MedicationAdministration", back_populates="chart", cascade="all, delete-orphan")
    signatures = relationship("EpcrSignatureArtifact", back_populates="chart", cascade="all, delete-orphan")
    interventions = relationship("ClinicalIntervention", back_populates="chart", cascade="all, delete-orphan")
    clinical_notes = relationship("ClinicalNote", back_populates="chart", cascade="all, delete-orphan")
    protocol_recommendations = relationship("ProtocolRecommendation", back_populates="chart", cascade="all, delete-orphan")
    derived_outputs = relationship("DerivedChartOutput", back_populates="chart", cascade="all, delete-orphan")
    nemsis_mappings = relationship("NemsisMappingRecord", back_populates="chart", cascade="all, delete-orphan")
    nemsis_compliance = relationship("NemsisCompliance", back_populates="chart", uselist=False, cascade="all, delete-orphan")


class FireIncidentLink(Base):
    """Durable receipt of a Fire incident event inside the ePCR domain."""

    __tablename__ = "epcr_fire_incident_links"

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=True)
    fire_incident_id = Column(String(36), index=True, nullable=False)
    fire_incident_number = Column(String(50), nullable=False)
    fire_address = Column(Text, nullable=False)
    fire_incident_type = Column(String(100), nullable=False)
    link_status = Column(String(50), nullable=False, default="pending")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


@event.listens_for(Chart, "before_update")
def _increment_chart_version(mapper, connection, target):
    target.version = (target.version or 1) + 1


class Vitals(Base):
    """Vital signs recorded during patient encounter.
    
    Represents a single set of vital sign measurements recorded during
    the encounter, including heart rate, blood pressure, temperature,
    respiration rate, oxygen saturation, and blood glucose.
    
    Attributes:
        id: Unique vital signs record identifier (UUID v4).
        chart_id: Foreign key to the Chart this record belongs to.
        tenant_id: Tenant identifier for multi-tenant isolation.
        bp_sys: Systolic blood pressure (mmHg), optional.
        bp_dia: Diastolic blood pressure (mmHg), optional.
        hr: Heart rate (beats per minute), optional.
        rr: Respiration rate (breaths per minute), optional.
        temp_f: Temperature (Fahrenheit), optional.
        spo2: Oxygen saturation (%), optional.
        glucose: Blood glucose (mg/dL), optional.
        recorded_at: Timestamp when vitals were measured (UTC).
        deleted_at: Soft delete timestamp (UTC), NULL if active.
    """
    __tablename__ = "epcr_vitals"
    
    id = Column(String(36), primary_key=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False)
    tenant_id = Column(String(36), index=True, nullable=False)
    bp_sys = Column(Integer, nullable=True)
    bp_dia = Column(Integer, nullable=True)
    hr = Column(Integer, nullable=True)
    rr = Column(Integer, nullable=True)
    temp_f = Column(Float, nullable=True)
    spo2 = Column(Integer, nullable=True)
    glucose = Column(Integer, nullable=True)
    recorded_at = Column(DateTime(timezone=True), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    
    chart = relationship("Chart", back_populates="vitals")


class Assessment(Base):
    """Clinical assessment and findings for patient encounter.
    
    Represents the paramedic's clinical assessment of the patient,
    including chief complaint, field diagnosis, and clinical impression.
    
    Attributes:
        id: Unique assessment record identifier (UUID v4).
        chart_id: Foreign key to the Chart this assessment belongs to (unique).
        tenant_id: Tenant identifier for multi-tenant isolation.
        chief_complaint: Patient's stated chief complaint (what prompted EMS call).
        field_diagnosis: Paramedic's field assessment of the patient's condition.
        documented_at: Timestamp when assessment was documented (UTC).
        deleted_at: Soft delete timestamp (UTC), NULL if active.
    """
    __tablename__ = "epcr_assessments"
    
    id = Column(String(36), primary_key=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, unique=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    chief_complaint = Column(String(500), nullable=True)
    field_diagnosis = Column(String(500), nullable=True)
    primary_impression = Column(String(255), nullable=True)
    secondary_impression = Column(String(255), nullable=True)
    impression_notes = Column(Text, nullable=True)
    snomed_code = Column(String(32), nullable=True)
    icd10_code = Column(String(32), nullable=True)
    acuity = Column(String(32), nullable=True)
    documented_at = Column(DateTime(timezone=True), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    
    chart = relationship("Chart", back_populates="assessment")


class PatientProfile(Base):
    """Chart-scoped patient demographics and allergy context."""

    __tablename__ = "epcr_patient_profiles"

    id = Column(String(36), primary_key=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, unique=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    first_name = Column(String(120), nullable=True)
    middle_name = Column(String(120), nullable=True)
    last_name = Column(String(120), nullable=True)
    date_of_birth = Column(String(32), nullable=True)
    age_years = Column(Integer, nullable=True)
    sex = Column(String(32), nullable=True)
    phone_number = Column(String(32), nullable=True)
    weight_kg = Column(Float, nullable=True)
    allergies_json = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    chart = relationship("Chart", back_populates="patient_profile")


class PatientRegistryProfile(Base):
    """Tenant-scoped repeat-patient registry profile."""

    __tablename__ = "patient_registry_profiles"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "canonical_patient_key",
            name="uq_patient_registry_profiles_tenant_canonical_key",
        ),
    )

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    canonical_patient_key = Column(String(64), index=True, nullable=True)
    first_name = Column(String(120), nullable=True)
    middle_name = Column(String(120), nullable=True)
    last_name = Column(String(120), nullable=True)
    first_name_norm = Column(String(120), nullable=True)
    last_name_norm = Column(String(120), nullable=True)
    date_of_birth = Column(String(32), nullable=True)
    sex = Column(String(32), nullable=True)
    phone_last4 = Column(String(4), nullable=True)
    primary_phone_hash = Column(String(64), nullable=True)
    merged_into_patient_id = Column(String(36), ForeignKey("patient_registry_profiles.id"), nullable=True, index=True)
    ai_assisted = Column(Boolean, nullable=False, server_default=text("0"))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    version = Column(Integer, nullable=False, server_default=text("1"))


class PatientRegistryIdentifier(Base):
    """Hashed identifiers attached to a registry profile."""

    __tablename__ = "patient_registry_identifiers"
    __table_args__ = (
        UniqueConstraint(
            "patient_registry_profile_id",
            "identifier_type",
            "identifier_hash",
            name="uq_patient_registry_identifiers_profile_identifier",
        ),
    )

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    patient_registry_profile_id = Column(
        String(36),
        ForeignKey("patient_registry_profiles.id"),
        nullable=False,
        index=True,
    )
    identifier_type = Column(String(32), nullable=False)
    identifier_hash = Column(String(64), nullable=False, index=True)
    identifier_last4 = Column(String(16), nullable=True)
    is_primary = Column(Boolean, nullable=False, server_default=text("0"))
    source_chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    version = Column(Integer, nullable=False, server_default=text("1"))


class PatientRegistryChartLink(Base):
    """Tenant-scoped link between a chart and a registry profile."""

    __tablename__ = "patient_registry_chart_links"
    __table_args__ = (
        UniqueConstraint("chart_id", name="uq_patient_registry_chart_links_chart_id"),
    )

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    patient_registry_profile_id = Column(
        String(36),
        ForeignKey("patient_registry_profiles.id"),
        nullable=False,
        index=True,
    )
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    link_status = Column(String(32), nullable=False, server_default=text("'linked'"))
    confidence_status = Column(String(32), nullable=True)
    linked_by_user_id = Column(String(255), nullable=True)
    rejected_reason = Column(Text, nullable=True)
    linked_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    version = Column(Integer, nullable=False, server_default=text("1"))


class EpcrChartingAcceleratorImport(Base):
    """Provider-confirmed charting accelerator import audit."""

    __tablename__ = "epcr_charting_accelerator_imports"
    __table_args__ = (
        UniqueConstraint(
            "chart_id",
            "source_chart_id",
            "section_name",
            "dedupe_key",
            name="uq_epcr_charting_accelerator_imports_scope",
        ),
    )

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    source_chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    section_name = Column(String(64), nullable=False)
    dedupe_key = Column(String(128), nullable=False)
    imported_fields_json = Column(Text, nullable=True)
    provider_confirmed = Column(Boolean, nullable=False, server_default=text("0"))
    confirmed_by_user_id = Column(String(255), nullable=True)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    version = Column(Integer, nullable=False, server_default=text("1"))


class PatientRegistryMergeCandidate(Base):
    """Scored duplicate candidate awaiting review."""

    __tablename__ = "patient_registry_merge_candidates"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "left_patient_id",
            "right_patient_id",
            name="uq_patient_registry_merge_candidates_pair",
        ),
    )

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    left_patient_id = Column(String(36), ForeignKey("patient_registry_profiles.id"), nullable=False, index=True)
    right_patient_id = Column(String(36), ForeignKey("patient_registry_profiles.id"), nullable=False, index=True)
    confidence_status = Column(String(32), nullable=False)
    score = Column(Float, nullable=False, server_default=text("0"))
    requires_human_review = Column(Boolean, nullable=False, server_default=text("1"))
    match_reasons_json = Column(Text, nullable=True)
    conflicting_signals_json = Column(Text, nullable=True)
    review_status = Column(String(32), nullable=False, server_default=text("'pending'"))
    reviewed_by_user_id = Column(String(255), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    version = Column(Integer, nullable=False, server_default=text("1"))


class PatientRegistryMergeAudit(Base):
    """Immutable audit record for merge and rollback actions."""

    __tablename__ = "patient_registry_merge_audit"

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    canonical_patient_id = Column(String(36), ForeignKey("patient_registry_profiles.id"), nullable=False, index=True)
    merged_patient_id = Column(String(36), ForeignKey("patient_registry_profiles.id"), nullable=False, index=True)
    snapshot_json = Column(Text, nullable=False)
    merged_by_user_id = Column(String(255), nullable=False)
    merged_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    rolled_back_at = Column(DateTime(timezone=True), nullable=True)
    rolled_back_by_user_id = Column(String(255), nullable=True)
    rollback_snapshot_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    version = Column(Integer, nullable=False, server_default=text("1"))


class PatientRegistryAlias(Base):
    """Alias mapping preserved after patient merges."""

    __tablename__ = "patient_registry_aliases"
    __table_args__ = (
        UniqueConstraint("tenant_id", "alias_patient_id", name="uq_patient_registry_aliases_tenant_alias"),
    )

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    canonical_patient_id = Column(String(36), ForeignKey("patient_registry_profiles.id"), nullable=False, index=True)
    alias_patient_id = Column(String(36), ForeignKey("patient_registry_profiles.id"), nullable=False, index=True)
    alias_reason = Column(String(64), nullable=False)
    created_by_user_id = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    version = Column(Integer, nullable=False, server_default=text("1"))


class AssessmentFinding(Base):
    """Structured CPAE finding linked to an anatomical region and system."""

    __tablename__ = "epcr_assessment_findings"

    id = Column(String(36), primary_key=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    anatomy = Column(String(64), nullable=False)
    system = Column(String(64), nullable=False)
    finding_type = Column(String(64), nullable=False)
    severity = Column(String(32), nullable=False)
    laterality = Column(String(32), nullable=True)
    evolution = Column(SQLEnum(FindingEvolution), default=FindingEvolution.NEW, nullable=False)
    characteristics_json = Column(Text, nullable=True)
    detection_method = Column(String(64), nullable=False)
    review_state = Column(SQLEnum(ReviewState), default=ReviewState.DIRECT_CONFIRMED, nullable=False)
    provider_id = Column(String(255), nullable=False)
    source_artifact_ids_json = Column(Text, nullable=True)
    observed_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    chart = relationship("Chart", back_populates="findings")
    visual_overlays = relationship("VisualOverlay", back_populates="finding", cascade="all, delete-orphan")


class VisualOverlay(Base):
    """Governed VAS overlay bound to a structured assessment finding."""

    __tablename__ = "epcr_visual_overlays"

    id = Column(String(36), primary_key=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    finding_id = Column(String(36), ForeignKey("epcr_assessment_findings.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    patient_model = Column(String(32), nullable=False)
    anatomical_view = Column(String(32), nullable=False)
    overlay_type = Column(String(64), nullable=False)
    anchor_region = Column(String(64), nullable=False)
    geometry_reference = Column(Text, nullable=False)
    severity = Column(String(32), nullable=False)
    evolution = Column(SQLEnum(FindingEvolution), default=FindingEvolution.NEW, nullable=False)
    review_state = Column(SQLEnum(ReviewState), default=ReviewState.DIRECT_CONFIRMED, nullable=False)
    provider_id = Column(String(255), nullable=False)
    evidence_artifact_ids_json = Column(Text, nullable=True)
    rendered_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    chart = relationship("Chart", back_populates="visual_overlays")
    finding = relationship("AssessmentFinding", back_populates="visual_overlays")


class ArSession(Base):
    """ARCOS session representing AR-guided chart capture for a patient."""

    __tablename__ = "epcr_ar_sessions"

    id = Column(String(36), primary_key=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    patient_model = Column(String(32), nullable=False)
    mode = Column(String(64), nullable=False)
    status = Column(SQLEnum(ArSessionStatus), default=ArSessionStatus.ACTIVE, nullable=False)
    started_by_user_id = Column(String(255), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    chart = relationship("Chart", back_populates="ar_sessions")
    anchors = relationship("ArAnchor", back_populates="session", cascade="all, delete-orphan")


class ArAnchor(Base):
    """Anatomical anchor captured during an ARCOS session."""

    __tablename__ = "epcr_ar_anchors"

    id = Column(String(36), primary_key=True)
    session_id = Column(String(36), ForeignKey("epcr_ar_sessions.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    anatomy = Column(String(64), nullable=False)
    anatomical_view = Column(String(32), nullable=False)
    confidence = Column(Float, nullable=False)
    anchored_by_user_id = Column(String(255), nullable=False)
    anchored_at = Column(DateTime(timezone=True), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    session = relationship("ArSession", back_populates="anchors")


class ChartAddress(Base):
    """Structured address intelligence captured for a chart."""

    __tablename__ = "epcr_chart_addresses"

    id = Column(String(36), primary_key=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, unique=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    raw_text = Column(Text, nullable=False)
    street_line_one = Column(String(255), nullable=True)
    street_line_two = Column(String(255), nullable=True)
    city = Column(String(100), nullable=True)
    state = Column(String(32), nullable=True)
    postal_code = Column(String(20), nullable=True)
    county = Column(String(100), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    validation_state = Column(SQLEnum(AddressValidationState), default=AddressValidationState.NEEDS_REVIEW, nullable=False)
    intelligence_source = Column(String(64), nullable=False)
    intelligence_detail = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    chart = relationship("Chart", back_populates="scene_address")


class MedicationAdministration(Base):
    """Medication administrations documented as ePCR-owned clinical truth."""

    __tablename__ = "epcr_medication_administrations"

    id = Column(String(36), primary_key=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    medication_name = Column(String(128), nullable=False)
    rxnorm_code = Column(String(32), nullable=True)
    dose_value = Column(String(32), nullable=True)
    dose_unit = Column(String(32), nullable=True)
    route = Column(String(64), nullable=False)
    indication = Column(Text, nullable=False)
    response = Column(Text, nullable=True)
    export_state = Column(SQLEnum(InterventionExportState), default=InterventionExportState.PENDING_MAPPING, nullable=False)
    administered_at = Column(DateTime(timezone=True), nullable=False)
    administered_by_user_id = Column(String(255), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    chart = relationship("Chart", back_populates="medications")


class EpcrSignatureArtifact(Base):
    """Authoritative signature artifact bound to chart completion workflows."""

    __tablename__ = "epcr_signature_artifacts"

    id = Column(String(36), primary_key=True, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    source_domain = Column(String(50), nullable=False, default="field_mobile")
    source_capture_id = Column(String(36), nullable=False, index=True)
    incident_id = Column(String(36), nullable=True, index=True)
    page_id = Column(String(36), nullable=True, index=True)

    signature_class = Column(String(100), nullable=False, index=True)
    signature_method = Column(String(50), nullable=False)
    workflow_policy = Column(String(64), nullable=False)
    policy_pack_version = Column(String(120), nullable=False)
    payer_class = Column(String(80), nullable=False)
    jurisdiction_country = Column(String(8), nullable=False)
    jurisdiction_state = Column(String(8), nullable=False)

    signer_identity = Column(String(255), nullable=True)
    signer_relationship = Column(String(100), nullable=True)
    signer_authority_basis = Column(String(120), nullable=True)
    patient_capable_to_sign = Column(Boolean, nullable=True)
    incapacity_reason = Column(String(500), nullable=True)

    receiving_facility = Column(String(255), nullable=True)
    receiving_clinician_name = Column(String(255), nullable=True)
    receiving_role_title = Column(String(120), nullable=True)
    transfer_of_care_time = Column(DateTime(timezone=True), nullable=True)
    transfer_exception_reason_code = Column(String(64), nullable=True)
    transfer_exception_reason_detail = Column(String(500), nullable=True)

    signature_on_file_reference = Column(String(120), nullable=True)
    ambulance_employee_exception = Column(Boolean, nullable=False, default=False)
    receiving_facility_verification_status = Column(String(40), nullable=False, default="not_required")

    signature_artifact_data_url = Column(Text, nullable=True)
    compliance_decision = Column(String(80), nullable=False, index=True)
    compliance_why = Column(String(500), nullable=False)
    missing_requirements_json = Column(Text, nullable=False, default="[]")
    billing_readiness_effect = Column(String(40), nullable=False)
    chart_completion_effect = Column(String(40), nullable=False)
    retention_requirements_json = Column(Text, nullable=False, default="[]")
    ai_decision_explanation_json = Column(Text, nullable=False, default="{}")

    transfer_etimes12_recorded = Column(Boolean, nullable=False, default=False)
    wards_export_safe = Column(Boolean, nullable=False, default=True)
    nemsis_export_safe = Column(Boolean, nullable=False, default=True)

    created_by_user_id = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    chart = relationship("Chart", back_populates="signatures")


class ClinicalIntervention(Base):
    """Structured intervention workflow record with protocol and terminology context."""

    __tablename__ = "epcr_interventions"

    id = Column(String(36), primary_key=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    category = Column(String(64), nullable=False)
    name = Column(String(128), nullable=False)
    indication = Column(Text, nullable=False)
    intent = Column(Text, nullable=False)
    expected_response = Column(Text, nullable=False)
    actual_response = Column(Text, nullable=True)
    reassessment_due_at = Column(DateTime(timezone=True), nullable=True)
    protocol_family = Column(SQLEnum(ProtocolFamily), default=ProtocolFamily.GENERAL, nullable=False)
    snomed_code = Column(String(32), nullable=True)
    icd10_code = Column(String(32), nullable=True)
    rxnorm_code = Column(String(32), nullable=True)
    export_state = Column(SQLEnum(InterventionExportState), default=InterventionExportState.PENDING_MAPPING, nullable=False)
    performed_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    provider_id = Column(String(255), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    chart = relationship("Chart", back_populates="interventions")


class ClinicalNote(Base):
    """Captured clinical text with deterministic derived summary and provenance."""

    __tablename__ = "epcr_clinical_notes"

    id = Column(String(36), primary_key=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    raw_text = Column(Text, nullable=False)
    source = Column(String(64), nullable=False)
    provenance_json = Column(Text, nullable=True)
    derived_summary = Column(Text, nullable=False)
    review_state = Column(SQLEnum(ClinicalNoteReviewState), default=ClinicalNoteReviewState.PENDING_REVIEW, nullable=False)
    captured_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    provider_id = Column(String(255), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    chart = relationship("Chart", back_populates="clinical_notes")


class ProtocolRecommendation(Base):
    """Deterministic protocol intelligence derived from chart state."""

    __tablename__ = "epcr_protocol_recommendations"

    id = Column(String(36), primary_key=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    protocol_family = Column(SQLEnum(ProtocolFamily), default=ProtocolFamily.GENERAL, nullable=False)
    title = Column(String(255), nullable=False)
    rationale = Column(Text, nullable=False)
    action_priority = Column(Integer, nullable=False, default=1)
    evidence_json = Column(Text, nullable=True)
    state = Column(SQLEnum(ProtocolRecommendationState), default=ProtocolRecommendationState.OPEN, nullable=False)
    generated_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    chart = relationship("Chart", back_populates="protocol_recommendations")


class DerivedChartOutput(Base):
    """Persisted derived chart outputs generated from CareGraph truth."""

    __tablename__ = "epcr_derived_outputs"

    id = Column(String(36), primary_key=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    output_type = Column(SQLEnum(DerivedOutputType), nullable=False)
    content_text = Column(Text, nullable=False)
    source_revision = Column(String(64), nullable=False)
    generated_at = Column(DateTime(timezone=True), nullable=False)
    generated_by_user_id = Column(String(255), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    chart = relationship("Chart", back_populates="derived_outputs")


class NemsisMappingRecord(Base):
    """NEMSIS field mapping with provenance tracking.
    
    Records the mapping between chart data and NEMSIS 3.5.1 field identifiers,
    including the source of each value (manual entry, OCR extraction, device,
    or system-generated) for audit trail and quality assurance.
    
    Attributes:
        id: Unique mapping record identifier (UUID v4).
        chart_id: Foreign key to the Chart this mapping belongs to.
        tenant_id: Tenant identifier for multi-tenant isolation.
        nemsis_field: NEMSIS field identifier (e.g., 'eRecord.01').
        nemsis_value: The value assigned to this NEMSIS field.
        source: Source of this value (manual, ocr, device, system).
        created_at: Timestamp when mapping was created (UTC).
        updated_at: Timestamp when mapping was last updated (UTC).
    """
    __tablename__ = "epcr_nemsis_mappings"
    
    id = Column(String(36), primary_key=True, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    nemsis_field = Column(String(255), nullable=False, index=True)
    nemsis_value = Column(Text, nullable=True)
    source = Column(SQLEnum(FieldSource), default=FieldSource.MANUAL, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    
    chart = relationship("Chart", back_populates="nemsis_mappings")


class NemsisCompliance(Base):
    """NEMSIS 3.5.1 compliance tracking for ePCR chart.
    
    Tracks compliance status of an ePCR chart against NEMSIS 3.5.1
    mandatory field requirements, enabling identification of missing
    required data before chart submission.
    
    Attributes:
        id: Unique compliance record identifier (UUID v4).
        chart_id: Foreign key to the Chart (unique relationship).
        tenant_id: Tenant identifier for multi-tenant isolation.
        compliance_status: Overall compliance status (not_started, in_progress, etc).
        mandatory_fields_filled: Count of mandatory fields that are populated.
        mandatory_fields_required: Total count of mandatory fields for this incident type.
        missing_mandatory_fields: JSON list of missing mandatory field IDs.
        compliance_checked_at: Timestamp of last compliance check (UTC).
        created_at: Timestamp when record was created (UTC).
        updated_at: Timestamp when record was last updated (UTC).
    """
    __tablename__ = "epcr_nemsis_compliance"
    
    id = Column(String(36), primary_key=True, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, unique=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    compliance_status = Column(SQLEnum(ComplianceStatus), default=ComplianceStatus.NOT_STARTED, nullable=False)
    mandatory_fields_filled = Column(Integer, default=0, nullable=False)
    mandatory_fields_required = Column(Integer, default=0, nullable=False)
    missing_mandatory_fields = Column(Text, nullable=True)
    compliance_checked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    
    chart = relationship("Chart", back_populates="nemsis_compliance")


class NemsisExportHistory(Base):
    """NEMSIS 3.5.1 export record tracking all submission attempts.

    Each row records one export attempt for a chart, storing the export
    payload snapshot, success/failure state, and the acting user. Never
    fabricates export success.

    Attributes:
        id: Unique export record identifier.
        chart_id: Foreign key to Chart exported.
        tenant_id: Tenant identifier for multi-tenant isolation.
        exported_by_user_id: User who triggered the export.
        export_status: success or failed.
        export_payload_json: JSON snapshot of NEMSIS fields at export time.
        error_message: Error detail if export_status is failed.
        exported_at: Timestamp of export attempt (UTC).
    """
    __tablename__ = "epcr_nemsis_export_history"

    id = Column(String(36), primary_key=True, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    exported_by_user_id = Column(String(255), nullable=False)
    export_status = Column(String(20), nullable=False)
    export_payload_json = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    exported_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    chart = relationship("Chart", backref="export_history")


class EpcrAuditLog(Base):
    """Audit trail for all ePCR chart operations.

    Records every create, update, finalize, and export action with full
    context for traceability, compliance, and security review.

    Attributes:
        id: Unique audit log entry identifier.
        chart_id: Chart this action applies to.
        tenant_id: Tenant identifier.
        user_id: User who performed the action.
        action: Action type (create, update, finalize, export, compliance_check).
        detail_json: JSON detail of what changed or was checked.
        performed_at: Timestamp of the action (UTC).
    """
    __tablename__ = "epcr_audit_log"

    id = Column(String(36), primary_key=True, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    user_id = Column(String(255), nullable=False)
    action = Column(String(50), nullable=False, index=True)
    detail_json = Column(Text, nullable=True)
    performed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)


class EpcrAnatomicalFinding(Base):
    """3D Physical Assessment finding bound to a chart and anatomical region.

    Captures region-level clinical findings emitted by the Adaptix 3D
    Physical Assessment module. Each row is scoped to a chart and
    tenant, and may carry severity, laterality, CMS distal assessment,
    burn surface area, and/or a pain score. ``pertinent_negative`` is
    True when the provider explicitly recorded the region as
    unremarkable.

    Enum-like columns are stored as portable string values; the canonical
    value sets live in
    :mod:`epcr_app.services.anatomical_finding_validation`.
    """

    __tablename__ = "epcr_anatomical_finding"
    __table_args__ = (
        CheckConstraint(
            "pain_scale IS NULL OR (pain_scale >= 0 AND pain_scale <= 10)",
            name="ck_epcr_anatomical_finding_pain_scale_range",
        ),
        CheckConstraint(
            "burn_tbsa_percent IS NULL OR "
            "(burn_tbsa_percent >= 0 AND burn_tbsa_percent <= 100)",
            name="ck_epcr_anatomical_finding_burn_tbsa_range",
        ),
        Index(
            "ix_epcr_anatomical_finding_tenant_chart_deleted",
            "tenant_id",
            "chart_id",
            "deleted_at",
        ),
    )

    id = Column(String(36), primary_key=True)
    chart_id = Column(
        String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True
    )
    tenant_id = Column(String(36), index=True, nullable=False)

    region_id = Column(String(64), nullable=False, index=True)
    region_label = Column(String(128), nullable=False)
    body_view = Column(String(16), nullable=False)
    finding_type = Column(String(128), nullable=False)
    severity = Column(String(32), nullable=True)
    laterality = Column(String(32), nullable=True)
    pain_scale = Column(SmallInteger, nullable=True)
    burn_tbsa_percent = Column(Numeric(5, 2), nullable=True)
    cms_pulse = Column(String(32), nullable=True)
    cms_motor = Column(String(32), nullable=True)
    cms_sensation = Column(String(32), nullable=True)
    cms_capillary_refill = Column(String(32), nullable=True)
    pertinent_negative = Column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    notes = Column(Text, nullable=True)
    assessed_at = Column(DateTime(timezone=True), nullable=False)
    assessed_by = Column(String(64), nullable=False)

    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)
    version = Column(Integer, nullable=False, server_default=text("1"))


class EpcrECustomFieldDefinition(Base):
    """Tenant/agency-scoped definition of an eCustom NEMSIS field.

    Captures the schema for an agency-defined custom data element used to
    extend the standard ePCR / NEMSIS dataset. The ``nemsis_relationship``
    column records the NEMSIS element this custom field anchors to (e.g.
    ``eCustomConfiguration.01``); see
    :mod:`epcr_app.services.ecustom_field_validation` for canonical
    ``data_type`` values and conditional rule semantics.
    """

    __tablename__ = "epcr_ecustom_field_definition"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "agency_id",
            "field_key",
            "version",
            name="uq_epcr_ecustom_field_definition_key_version",
        ),
        Index(
            "ix_epcr_ecustom_field_definition_tenant_agency_key",
            "tenant_id",
            "agency_id",
            "field_key",
        ),
    )

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    agency_id = Column(String(36), index=True, nullable=False)

    field_key = Column(String(128), nullable=False)
    label = Column(String(255), nullable=False)
    data_type = Column(String(32), nullable=False)
    allowed_values_json = Column(Text, nullable=True)
    required = Column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    conditional_rule_json = Column(Text, nullable=True)
    nemsis_relationship = Column(String(128), nullable=True)
    state_profile = Column(String(64), nullable=True)
    version = Column(Integer, nullable=False, server_default=text("1"))
    retired = Column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )

    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class EpcrECustomFieldValue(Base):
    """Per-chart value for an :class:`EpcrECustomFieldDefinition`.

    Stores the captured value as JSON in ``value_json`` so heterogeneous
    data types (string / number / boolean / date / select / multi_select)
    share a single storage column. ``validation_result_json`` captures the
    most recent validator outcome for the value, enabling downstream
    NEMSIS export gates without re-running validation.
    """

    __tablename__ = "epcr_ecustom_field_value"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "chart_id",
            "field_definition_id",
            name="uq_epcr_ecustom_field_value_chart_definition",
        ),
        Index(
            "ix_epcr_ecustom_field_value_tenant_chart",
            "tenant_id",
            "chart_id",
        ),
    )

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    chart_id = Column(
        String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True
    )
    field_definition_id = Column(
        String(36),
        ForeignKey("epcr_ecustom_field_definition.id"),
        nullable=False,
        index=True,
    )
    value_json = Column(Text, nullable=True)
    validation_result_json = Column(Text, nullable=True)
    audit_user_id = Column(String(255), nullable=True)

    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )



class EpcrSentenceEvidence(Base):
    """AI-narrative sentence -> structured-evidence linkage row.

    Each row captures the deterministic mapping between a single sentence
    of an AI-generated ePCR narrative and a referenced piece of
    structured chart evidence (a field, vital, treatment, medication,
    procedure, anatomical finding, prior chart, prior ECG, OCR snippet,
    map waypoint, protocol, or provider note).

    The provider can confirm or unlink a row at any time; both actions
    write an :class:`EpcrAiAuditEvent`. Rows are produced by
    :mod:`epcr_app.services.sentence_evidence_service`, which wraps (but
    never modifies) the existing narrative AI service. The linker itself
    is pure-Python and performs no LLM calls.

    Canonical ``evidence_kind`` values:
    ``field``, ``vital``, ``treatment``, ``medication``, ``procedure``,
    ``anatomical_finding``, ``prior_chart``, ``prior_ecg``, ``ocr``,
    ``map``, ``protocol``, ``provider_note``.
    """

    __tablename__ = "epcr_sentence_evidence"
    __table_args__ = (
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_epcr_sentence_evidence_confidence_range",
        ),
        CheckConstraint(
            "sentence_index >= 0",
            name="ck_epcr_sentence_evidence_sentence_index_nonneg",
        ),
        Index(
            "ix_epcr_sentence_evidence_tenant_chart",
            "tenant_id",
            "chart_id",
        ),
    )

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    chart_id = Column(
        String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True
    )
    # Soft FK: narratives may live in a non-DB-backed store today.
    narrative_id = Column(String(64), nullable=True, index=True)
    sentence_index = Column(Integer, nullable=False)
    sentence_text = Column(Text, nullable=False)
    evidence_kind = Column(String(32), nullable=False)
    evidence_ref_id = Column(String(64), nullable=True)
    confidence = Column(Numeric(3, 2), nullable=False)
    provider_confirmed = Column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class EpcrAiAuditEvent(Base):
    """Audit event for AI-narrative and sentence-evidence lifecycle.

    Captures every state change in the AI-evidence pillar so the
    provider, compliance, and downstream consumers can replay exactly
    what happened to a narrative and its evidence links.

    Canonical ``event_kind`` values:
    ``narrative.draft``, ``narrative.accepted``, ``narrative.rejected``,
    ``sentence.evidence_added``, ``sentence.evidence_unlinked``,
    ``phrase.inserted``, ``phrase.edited``, ``phrase.removed``.
    """

    __tablename__ = "epcr_ai_audit_event"
    __table_args__ = (
        Index(
            "ix_epcr_ai_audit_event_tenant_chart",
            "tenant_id",
            "chart_id",
        ),
    )

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    chart_id = Column(
        String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True
    )
    event_kind = Column(String(64), nullable=False, index=True)
    user_id = Column(String(255), nullable=True)
    payload_json = Column(Text, nullable=True)
    performed_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class EpcrRxNormMedicationMatch(Base):
    """RxNorm normalization match for a documented medication administration.

    Each row links a free-text medication administration captured on a
    chart to a normalized RxNorm concept (RxCUI + TTY + dose form +
    strength) along with a provenance ``source`` indicating whether the
    match came from the live RxNav API, a local cached prior match, or
    explicit provider confirmation. The table also serves as the local
    cache: repeated normalization requests prefer existing rows for the
    same ``(tenant_id, medication_admin_id)`` over re-calling RxNav.

    The service layer NEVER fabricates an ``rxcui``. When RxNav is
    unavailable and no cached match exists, the row is simply not
    persisted (``raw_text`` is always preserved on
    :class:`MedicationAdministration`).
    """

    __tablename__ = "epcr_rxnorm_medication_match"
    __table_args__ = (
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_epcr_rxnorm_match_confidence_range",
        ),
        Index(
            "ix_epcr_rxnorm_match_tenant_chart",
            "tenant_id",
            "chart_id",
        ),
        Index(
            "ix_epcr_rxnorm_match_medication_admin",
            "medication_admin_id",
        ),
    )

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    chart_id = Column(
        String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True
    )
    # Soft FK: stored as String(36) without a DB-level FOREIGN KEY so that
    # archival/soft-delete of a medication administration does not cascade
    # into the normalization match log.
    medication_admin_id = Column(String(36), nullable=False, index=True)

    raw_text = Column(Text, nullable=False)
    normalized_name = Column(String(256), nullable=True)
    rxcui = Column(String(32), nullable=True, index=True)
    tty = Column(String(16), nullable=True)  # 'IN' | 'BN' | 'SCD' | 'SBD'
    dose_form = Column(String(64), nullable=True)
    strength = Column(String(64), nullable=True)
    confidence = Column(Numeric(3, 2), nullable=True)
    source = Column(String(32), nullable=False)  # 'rxnav_api' | 'local_cache' | 'provider_confirmed'
    provider_confirmed = Column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    provider_id = Column(String(64), nullable=True)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class EpcrIcd10DocumentationSuggestion(Base):
    """ICD-10 documentation specificity *prompt* bound to a chart.

    This row represents a **prompt** to the clinician for documentation
    specificity (laterality, body region, mechanism, encounter context,
    symptom vs. diagnosis, general specificity). It is NEVER a diagnosis.

    The service that produces these rows MUST NEVER auto-assign,
    auto-select, or otherwise bind an ICD-10 code on behalf of the
    provider. ``candidate_codes_json`` is informational only -- a
    serialized JSON list of ``{"code", "description"}`` objects shown to
    the clinician as candidates they may *choose* to adopt. Adoption is
    captured exclusively via the explicit acknowledgement flow
    (:meth:`Icd10DocumentationService.acknowledge`), which sets
    ``provider_selected_code`` based on the clinician's choice. A
    clinician may also reject the suggestion entirely, in which case
    ``provider_selected_code`` remains ``NULL`` and
    ``provider_acknowledged`` is set to ``True``.
    """

    __tablename__ = "epcr_icd10_documentation_suggestion"
    __table_args__ = (
        Index(
            "ix_epcr_icd10_doc_suggestion_tenant_chart",
            "tenant_id",
            "chart_id",
        ),
    )

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    chart_id = Column(
        String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True
    )
    complaint_text = Column(Text, nullable=True)
    prompt_kind = Column(String(48), nullable=False, index=True)
    prompt_text = Column(Text, nullable=False)
    candidate_codes_json = Column(Text, nullable=True)
    provider_acknowledged = Column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    provider_selected_code = Column(String(32), nullable=True)
    provider_selected_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class EpcrMapLocationContext(Base):
    """Geospatial location context for a chart (Mapbox-backed).

    One row per discrete location capture (scene address, destination
    facility, staging area, breadcrumb). The row carries the raw
    coordinates plus optional reverse-geocoded address, accuracy, and a
    classified ``facility_type`` for destinations.

    Honesty contract: ``reverse_geocoded`` is True only when an actual
    Mapbox reverse-geocode call populated ``address_text``. If the
    Mapbox token is not configured at write time, the service records
    the row with ``reverse_geocoded=False`` and ``address_text=None``
    rather than fabricating address data. ``facility_type`` is
    populated only from a real classifier and is never inferred from
    free text. Enum-like columns are stored as portable strings; the
    canonical value sets are enforced in
    :mod:`epcr_app.services.map_location_service`.
    """

    __tablename__ = "epcr_map_location_context"
    __table_args__ = (
        Index(
            "ix_epcr_map_location_context_tenant_chart",
            "tenant_id",
            "chart_id",
        ),
        Index(
            "ix_epcr_map_location_context_chart_kind",
            "chart_id",
            "kind",
        ),
    )

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    chart_id = Column(
        String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True
    )
    kind = Column(String(32), nullable=False)
    address_text = Column(Text, nullable=True)
    latitude = Column(Numeric(9, 6), nullable=False)
    longitude = Column(Numeric(9, 6), nullable=False)
    accuracy_meters = Column(Numeric(10, 2), nullable=True)
    reverse_geocoded = Column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    facility_type = Column(String(32), nullable=True)
    distance_meters = Column(Numeric(12, 2), nullable=True)
    captured_at = Column(DateTime(timezone=True), nullable=False)

    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class EpcrRepeatPatientMatch(Base):
    """Candidate repeat-patient match discovered for a chart.

    Rows are produced by :class:`RepeatPatientService.find_matches` and
    represent a tenant-scoped link between the current chart's patient
    context and a previously-known patient profile. Carry-forward of
    values from the matched profile is gated on a provider review:
    ``reviewed`` must be ``True`` and ``carry_forward_allowed`` must be
    ``True``.

    ``matched_profile_id`` is a soft FK to ``epcr_patient_profiles.id``
    (no enforced FK clause) so registry merges and historical replays
    remain free of cascade churn.
    """

    __tablename__ = "epcr_repeat_patient_match"
    __table_args__ = (
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_epcr_repeat_patient_match_confidence_range",
        ),
        Index(
            "ix_epcr_repeat_patient_match_tenant_chart",
            "tenant_id",
            "chart_id",
        ),
    )

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    chart_id = Column(String(36), index=True, nullable=False)
    matched_profile_id = Column(String(36), index=True, nullable=False)
    confidence = Column(Numeric(3, 2), nullable=False)
    match_reason_json = Column(Text, nullable=False)
    reviewed = Column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    reviewed_by = Column(String(64), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    carry_forward_allowed = Column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class EpcrPriorChartReference(Base):
    """Snapshot reference linking a chart to a prior chart for the same identity.

    Lightweight read-side row produced alongside repeat-patient match
    discovery. ``prior_chart_id`` is a soft FK to ``epcr_charts.id``.
    """

    __tablename__ = "epcr_prior_chart_reference"
    __table_args__ = (
        Index(
            "ix_epcr_prior_chart_reference_tenant_chart",
            "tenant_id",
            "chart_id",
        ),
    )

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    chart_id = Column(String(36), index=True, nullable=False)
    prior_chart_id = Column(String(36), index=True, nullable=False)
    encounter_at = Column(DateTime(timezone=True), nullable=True)
    chief_complaint = Column(String(255), nullable=True)
    disposition = Column(String(128), nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class EpcrPriorEcgReference(Base):
    """Reference to a prior 12-lead ECG available for clinician comparison.

    Captures the existence and provenance of a prior ECG bound to the
    current chart. This row is metadata-only; it never carries an
    interpretation. The presence of the row means a provider can
    compare the current ECG against the prior, but the comparison
    itself lives in :class:`EpcrEcgComparisonResult` and is strictly
    provider-attested.

    Note: ``prior_chart_id`` is a soft foreign key (no DB-level FK
    constraint) so prior ECGs sourced from imports or archived charts
    do not block insertion.
    """

    __tablename__ = "epcr_prior_ecg_reference"

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    chart_id = Column(
        String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True
    )
    prior_chart_id = Column(String(36), nullable=True, index=True)
    captured_at = Column(DateTime(timezone=True), nullable=False)
    encounter_context = Column(String(128), nullable=False)
    image_storage_uri = Column(String(512), nullable=True)
    monitor_imported = Column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    quality = Column(String(32), nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class EpcrEcgComparisonResult(Base):
    """Provider-attested comparison of the current ECG against a prior ECG.

    The service layer NEVER produces an interpretation. Acceptable
    comparison_state values are pre-enumerated and chosen by the
    provider: 'similar', 'different', 'unable_to_compare',
    'not_relevant'. NEMSIS export and downstream consumers must check
    provider_confirmed=True before using this row.
    """

    __tablename__ = "epcr_ecg_comparison_result"

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    chart_id = Column(
        String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True
    )
    prior_ecg_id = Column(
        String(36),
        ForeignKey("epcr_prior_ecg_reference.id"),
        nullable=False,
        index=True,
    )
    comparison_state = Column(String(32), nullable=False)
    provider_confirmed = Column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    provider_id = Column(String(64), nullable=True)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    confidence = Column(Numeric(3, 2), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class EpcrSmartTextSuggestion(Base):
    """Smart-text suggestion offered for a chart field.

    Each row is one renderable suggestion produced by the
    :mod:`epcr_app.services.smart_text_service` resolver for a given
    ``(tenant_id, chart_id, section, field_key)`` slot. Suggestions
    carry an explicit provenance ``source`` (agency library, provider
    favorite, protocol, AI), a numeric ``confidence`` in [0, 1], and a
    ``compliance_state`` so the workspace can render the correct review
    affordance.

    Acceptance state lives on the suggestion itself: ``accepted`` is
    ``NULL`` while the suggestion is offered, ``True`` after the
    provider accepts it, and ``False`` after rejection. The audit trail
    is written to :class:`EpcrAuditLog` with action
    ``smart_text.accepted`` or ``smart_text.rejected``.

    ``evidence_link_id`` is a soft (non-enforced) reference to
    :class:`EpcrSentenceEvidence` (``epcr_sentence_evidence.id``); the
    hard FK will be wired in a later slice.
    """

    __tablename__ = "epcr_smart_text_suggestion"
    __table_args__ = (
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_epcr_smart_text_suggestion_confidence_range",
        ),
        CheckConstraint(
            "source IN ('agency_library','provider_favorite','protocol','ai')",
            name="ck_epcr_smart_text_suggestion_source",
        ),
        CheckConstraint(
            "compliance_state IN ('approved','pending','risk')",
            name="ck_epcr_smart_text_suggestion_compliance_state",
        ),
        Index(
            "ix_epcr_smart_text_suggestion_tenant_chart_section_field",
            "tenant_id",
            "chart_id",
            "section",
            "field_key",
        ),
    )

    id = Column(String(36), primary_key=True)
    chart_id = Column(
        String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True
    )
    tenant_id = Column(String(36), nullable=False, index=True)

    section = Column(String(64), nullable=False)
    field_key = Column(String(128), nullable=False)
    phrase = Column(Text, nullable=False)

    source = Column(String(32), nullable=False)
    confidence = Column(Numeric(3, 2), nullable=False)
    compliance_state = Column(String(16), nullable=False)

    evidence_link_id = Column(String(36), nullable=True)

    accepted = Column(Boolean, nullable=True)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    performed_by = Column(String(255), nullable=True)

    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class EpcrMultiPatientIncident(Base):
    """Multi-Patient Incident (MCI / multi-victim event) parent record.

    Represents the umbrella event linking multiple ePCR charts that
    share a single scene (e.g. mass-casualty incidents, multi-victim
    MVAs, fire-rescues). Each row aggregates the scene-level context
    that is identical across all attached patients: scene address,
    mechanism of injury, on-scene hazards, MCI flag, and the
    declared patient count. Individual patient chart rows are linked
    via :class:`EpcrMultiPatientLink` with a per-patient label
    ('A', 'B', 'C', ...).

    ``parent_incident_number`` is the externally-visible incident
    identifier (often a CAD or agency-assigned number) that providers
    use to recognize the event across charts. ``scene_address_json``
    is stored as a JSON blob so heterogeneous address formats
    (structured, lat/long-only, geohash, mile-marker) share a single
    column without schema drift.
    """

    __tablename__ = "epcr_multi_patient_incident"
    __table_args__ = (
        Index(
            "ix_epcr_multi_patient_incident_tenant_parent",
            "tenant_id",
            "parent_incident_number",
        ),
        CheckConstraint(
            "patient_count >= 0",
            name="ck_epcr_multi_patient_incident_patient_count_nonneg",
        ),
    )

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    parent_incident_number = Column(String(64), nullable=False, index=True)
    scene_address_json = Column(Text, nullable=True)
    mci_flag = Column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    patient_count = Column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    mechanism = Column(String(128), nullable=True)
    hazards_text = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class EpcrMultiPatientLink(Base):
    """Per-patient link between an :class:`EpcrMultiPatientIncident`
    parent and a specific ePCR chart.

    ``patient_label`` is the human-readable provider-assigned label
    ('A', 'B', 'C', ...) or an ``unknown_N`` placeholder when no
    canonical label has been assigned. ``triage_category`` carries
    the standard START / SALT colors ('green' | 'yellow' | 'red' |
    'black'). ``acuity``, ``transport_priority``, and
    ``destination_id`` are nullable for incidents documented before
    triage / transport decisions are made.

    The FK to ``epcr_charts.id`` is *soft* (no DB-level FOREIGN KEY)
    so cross-tenant chart archival and incident-level merges/splits
    do not need cascading. Soft delete via ``removed_at``.
    """

    __tablename__ = "epcr_multi_patient_link"
    __table_args__ = (
        Index(
            "ix_epcr_multi_patient_link_tenant_chart",
            "tenant_id",
            "chart_id",
        ),
        Index(
            "ix_epcr_multi_patient_link_tenant_incident",
            "tenant_id",
            "multi_incident_id",
        ),
    )

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    multi_incident_id = Column(
        String(36),
        ForeignKey("epcr_multi_patient_incident.id"),
        nullable=False,
        index=True,
    )
    # Soft FK by string; see class docstring.
    chart_id = Column(String(36), nullable=False, index=True)
    patient_label = Column(String(32), nullable=False)
    triage_category = Column(String(16), nullable=True)
    acuity = Column(String(32), nullable=True)
    transport_priority = Column(String(32), nullable=True)
    destination_id = Column(String(64), nullable=True)

    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    removed_at = Column(DateTime(timezone=True), nullable=True, index=True)


class EpcrProviderOverride(Base):
    """Provider override / supervisor-confirmation audit row.

    Captures the canonical record of a provider's documented override of
    a validation warning, lock blocker, state-required field, agency-
    required field, or rejected AI suggestion. ``reason_text`` is
    REQUIRED with a minimum length of 8 characters (enforced both at the
    application layer in
    :class:`epcr_app.services.provider_override_service.ProviderOverrideService`
    and via a portable CHECK constraint here).

    A supervisor confirmation is optional: when the override workflow
    requires a second signer, ``supervisor_id`` is populated and
    ``supervisor_confirmed_at`` is set when the supervisor explicitly
    confirms the override. Every state change additionally writes an
    :class:`EpcrAuditLog` row so downstream consumers (audit-trail
    query, compliance export) can replay the lifecycle.

    Canonical ``kind`` values:
    ``validation_warning``, ``lock_blocker``, ``state_required``,
    ``agency_required``, ``ai_suggestion_rejected``.
    """

    __tablename__ = "epcr_provider_override"
    __table_args__ = (
        CheckConstraint(
            "length(reason_text) >= 8",
            name="ck_epcr_provider_override_reason_min_length",
        ),
        Index(
            "ix_epcr_provider_override_tenant_chart",
            "tenant_id",
            "chart_id",
        ),
    )

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    chart_id = Column(
        String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True
    )
    section = Column(String(64), nullable=False)
    field_key = Column(String(128), nullable=False)
    kind = Column(String(32), nullable=False, index=True)
    reason_text = Column(Text, nullable=False)
    overrode_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    overrode_by = Column(String(255), nullable=False)
    supervisor_id = Column(String(64), nullable=True)
    supervisor_confirmed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )


class EpcrProtocolContext(Base):
    """Live protocol engagement context for a chart.

    Tracks which clinical protocol pack (ACLS, PALS, NRP, CCT, ...) is
    currently engaged for a given ePCR chart, when it was engaged and by
    whom, and a snapshot of the pack's required-field satisfaction at the
    point of engagement.

    A single chart MAY have at most one row with ``disengaged_at IS NULL``
    at a time (the active context). Historical rows are preserved
    (disengaged) for audit replay.

    Attributes:
        id: Unique context record identifier (UUID v4).
        tenant_id: Tenant identifier (multi-tenant isolation).
        chart_id: FK to ``epcr_charts.id`` the context applies to.
        active_pack: Pack key — e.g. 'ACLS' | 'PALS' | 'NRP' | 'CCT' |
            None (disengaged sentinel rows). The canonical set of packs
            supported by the in-process AI engine lives in
            :data:`epcr_app.ai_clinical_engine.PROTOCOL_PACKS`. Packs not
            present in that registry are still permitted at the model
            layer and surfaced as ``pack_unknown`` advisories by the
            service layer.
        engaged_at: UTC timestamp the pack was engaged.
        engaged_by: User id who engaged the pack.
        disengaged_at: UTC timestamp the pack was disengaged, NULL while
            the context is still active.
        required_field_satisfaction_json: JSON-serialized snapshot of the
            satisfaction map at engagement time. Shape matches the
            ``LockReadinessService`` payload contract.
        pack_version: Free-form version string for the pack definition
            (e.g. ``'engine:2026-05'``); allows replay of historical
            engagements even if the engine pack content changes.
        created_at, updated_at: Audit timestamps.
    """

    __tablename__ = "epcr_protocol_context"
    __table_args__ = (
        Index(
            "ix_epcr_protocol_context_tenant_chart_active",
            "tenant_id",
            "chart_id",
            "disengaged_at",
        ),
        Index(
            "ix_epcr_protocol_context_tenant_chart",
            "tenant_id",
            "chart_id",
        ),
    )

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    chart_id = Column(
        String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True
    )
    active_pack = Column(String(32), nullable=True)
    engaged_at = Column(DateTime(timezone=True), nullable=False)
    engaged_by = Column(String(255), nullable=False)
    disengaged_at = Column(DateTime(timezone=True), nullable=True)
    required_field_satisfaction_json = Column(Text, nullable=True)
    pack_version = Column(String(64), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
