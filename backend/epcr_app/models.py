"""ePCR domain models: ePCR charts, NEMSIS 3.5.1 compliance, clinical data.

This module defines the SQLAlchemy ORM models for the epcr domain,
including chart lifecycle, clinical vitals, assessments, and NEMSIS 3.5.1
compliance tracking for emergency patient care records.
"""
from datetime import datetime, UTC
from enum import Enum
from sqlalchemy import Column, String, DateTime, Integer, Text, ForeignKey, Boolean, Float, Enum as SQLEnum
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
    
    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    call_number = Column(String(50), unique=True, nullable=False, index=True)
    patient_id = Column(String(36), nullable=True)
    incident_type = Column(String(50), default="medical", nullable=False)
    status = Column(SQLEnum(ChartStatus), default=ChartStatus.NEW, nullable=False)
    created_by_user_id = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    finalized_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)
    
    vitals = relationship("Vitals", back_populates="chart", cascade="all, delete-orphan")
    assessment = relationship("Assessment", back_populates="chart", uselist=False, cascade="all, delete-orphan")
    nemsis_mappings = relationship("NemsisMappingRecord", back_populates="chart", cascade="all, delete-orphan")
    nemsis_compliance = relationship("NemsisCompliance", back_populates="chart", uselist=False, cascade="all, delete-orphan")


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
    documented_at = Column(DateTime(timezone=True), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    
    chart = relationship("Chart", back_populates="assessment")


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
