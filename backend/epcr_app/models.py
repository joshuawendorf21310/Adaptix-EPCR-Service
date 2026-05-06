"""ePCR domain models: ePCR charts, NEMSIS 3.5.1 compliance, clinical data.

This module defines the SQLAlchemy ORM models for the epcr domain,
including chart lifecycle, clinical vitals, assessments, and NEMSIS 3.5.1
compliance tracking for emergency patient care records.
"""
from datetime import datetime, UTC
from enum import Enum
from sqlalchemy import (
    Column,
    String,
    DateTime,
    Integer,
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
