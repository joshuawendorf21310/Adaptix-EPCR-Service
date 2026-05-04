"""Adaptix Vision integration models — governed perception layer.

Vision may ingest, classify, extract, project, and propose.
Vision may NEVER silently write clinical truth.

All Vision outputs are proposals until accepted by a clinician.
Every proposal preserves:
- Provenance
- Confidence scoring
- Source hash
- Model version
- Extraction history
- Review state

Forbidden:
- Vision writing chart truth directly
- Vision silently merging patients
- Vision assigning impressions without review
- Hiding low confidence
- Destroying provenance
- Creating orphan extractions
- Storing public media URLs
- Client-side-only trust for acceptance state
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

class VisionIngestionSource(str, Enum):
    MOBILE_CAMERA = "mobile_camera"
    GALLERY_IMPORT = "gallery_import"
    SCANNER_UPLOAD = "scanner_upload"
    PDF_DOCUMENT = "pdf_document"
    ECG_PRINTOUT = "ecg_printout"
    MONITOR_SCREENSHOT = "monitor_screenshot"
    VENTILATOR_SCREEN = "ventilator_screen"
    INFUSION_PUMP_SCREEN = "infusion_pump_screen"
    MEDICATION_LABEL = "medication_label"
    WRISTBAND = "wristband"
    TRANSFER_PAPERWORK = "transfer_paperwork"
    DISCHARGE_PAPERWORK = "discharge_paperwork"
    FACE_SHEET = "face_sheet"
    INJURY_PHOTO = "injury_photo"
    SCENE_PHOTO = "scene_photo"
    EQUIPMENT_PHOTO = "equipment_photo"
    BARCODE = "barcode"
    QR_CODE = "qr_code"


class VisionJobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


class VisionReviewAction(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    EDIT_AND_ACCEPT = "edit_and_accept"
    ROUTE_FOR_RECAPTURE = "route_for_recapture"
    ESCALATE = "escalate"
    SUPERVISOR_REVIEW = "supervisor_review"


class VisionProposalTarget(str, Enum):
    PATIENT_IDENTITY = "patient_identity"
    WRISTBAND_IDENTITY = "wristband_identity"
    MEDICATION = "medication"
    RXNORM = "rxnorm"
    VITAL = "vital"
    DEVICE_SETTING = "device_setting"
    VENTILATOR_SETTING = "ventilator_setting"
    PUMP_SETTING = "pump_setting"
    INJURY_BODY_MAP = "injury_body_map"
    ADDRESS = "address"
    FACILITY = "facility"
    IMPRESSION_SUPPORT = "impression_support"
    ECG_RHYTHM = "ecg_rhythm"
    DOCUMENT_TYPE = "document_type"


# ---------------------------------------------------------------------------
# Vision Artifact
# ---------------------------------------------------------------------------

class VisionArtifact(Base):
    """Ingested artifact awaiting or having undergone Vision processing.

    Media URLs are NEVER stored publicly. Artifacts reference secure
    internal storage paths only.
    """
    __tablename__ = "vision_artifacts"

    id = Column(String(36), primary_key=True, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    ingestion_source = Column(String(64), nullable=False)  # VisionIngestionSource
    original_filename = Column(String(255), nullable=True)
    content_type = Column(String(64), nullable=False)
    storage_path = Column(String(512), nullable=False)  # internal secure path only
    storage_bucket = Column(String(128), nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    source_hash_sha256 = Column(String(64), nullable=False, index=True)

    # Processing state
    processing_status = Column(String(32), nullable=False, default="pending")
    processing_error = Column(Text, nullable=True)

    # Attribution
    uploaded_by_user_id = Column(String(255), nullable=False)
    device_id = Column(String(64), nullable=True)

    uploaded_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    versions = relationship("VisionArtifactVersion", back_populates="artifact", cascade="all, delete-orphan")
    ingestion_jobs = relationship("VisionIngestionJob", back_populates="artifact", cascade="all, delete-orphan")
    extractions = relationship("VisionExtraction", back_populates="artifact", cascade="all, delete-orphan")
    chart_links = relationship("VisionChartLink", back_populates="artifact", cascade="all, delete-orphan")
    quality_flags = relationship("VisionQualityFlag", back_populates="artifact", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# Vision Artifact Version
# ---------------------------------------------------------------------------

class VisionArtifactVersion(Base):
    """Version history for a Vision artifact (e.g., recapture, re-upload)."""

    __tablename__ = "vision_artifact_versions"

    id = Column(String(36), primary_key=True, index=True)
    artifact_id = Column(String(36), ForeignKey("vision_artifacts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    version_number = Column(Integer, nullable=False)
    storage_path = Column(String(512), nullable=False)
    source_hash_sha256 = Column(String(64), nullable=False)
    reason = Column(String(255), nullable=True)
    created_by_user_id = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)

    artifact = relationship("VisionArtifact", back_populates="versions")


# ---------------------------------------------------------------------------
# Vision Ingestion Job
# ---------------------------------------------------------------------------

class VisionIngestionJob(Base):
    """Processing job for a Vision artifact ingestion pipeline run."""

    __tablename__ = "vision_ingestion_jobs"

    id = Column(String(36), primary_key=True, index=True)
    artifact_id = Column(String(36), ForeignKey("vision_artifacts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    status = Column(String(32), nullable=False, default="queued")  # VisionJobStatus
    model_version = Column(String(64), nullable=True)
    pipeline_version = Column(String(64), nullable=True)

    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_detail = Column(Text, nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=3)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)

    artifact = relationship("VisionArtifact", back_populates="ingestion_jobs")
    extraction_runs = relationship("VisionExtractionRun", back_populates="job", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# Vision Extraction Run
# ---------------------------------------------------------------------------

class VisionExtractionRun(Base):
    """Single extraction run within an ingestion job."""

    __tablename__ = "vision_extraction_runs"

    id = Column(String(36), primary_key=True, index=True)
    job_id = Column(String(36), ForeignKey("vision_ingestion_jobs.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    extraction_type = Column(String(64), nullable=False)  # ocr, classification, body_map, device_reading
    model_version = Column(String(64), nullable=True)
    status = Column(String(32), nullable=False, default="pending")
    raw_output_json = Column(Text, nullable=True)
    error_detail = Column(Text, nullable=True)

    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    job = relationship("VisionIngestionJob", back_populates="extraction_runs")


# ---------------------------------------------------------------------------
# Vision Extraction (individual extracted value)
# ---------------------------------------------------------------------------

class VisionExtraction(Base):
    """Individual value extracted from a Vision artifact.

    Every extraction preserves provenance, confidence, source hash,
    model version, and review state. Extractions are proposals only.
    """
    __tablename__ = "vision_extractions"

    id = Column(String(36), primary_key=True, index=True)
    artifact_id = Column(String(36), ForeignKey("vision_artifacts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    proposal_target = Column(String(64), nullable=False)  # VisionProposalTarget
    extracted_value_json = Column(Text, nullable=False)  # structured extracted value
    raw_text = Column(Text, nullable=True)  # raw OCR/extraction text

    confidence = Column(Float, nullable=False)
    model_version = Column(String(64), nullable=True)
    source_hash_sha256 = Column(String(64), nullable=False)

    # Review state — NEVER auto-accepted
    review_state = Column(String(64), nullable=False, default="pending_review")
    reviewer_id = Column(String(255), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    reviewer_notes = Column(Text, nullable=True)
    edited_value_json = Column(Text, nullable=True)  # if edited before acceptance

    # Chart linkage (set after acceptance)
    accepted_chart_field = Column(String(128), nullable=True)
    accepted_chart_record_id = Column(String(36), nullable=True)

    extracted_at = Column(DateTime(timezone=True), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    artifact = relationship("VisionArtifact", back_populates="extractions")
    bounding_regions = relationship("VisionBoundingRegion", back_populates="extraction", cascade="all, delete-orphan")
    annotations = relationship("VisionAnnotation", back_populates="extraction", cascade="all, delete-orphan")
    provenance_records = relationship("VisionProvenanceRecord", back_populates="extraction", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# Vision Classification
# ---------------------------------------------------------------------------

class VisionClassification(Base):
    """Document/artifact type classification result from Vision."""

    __tablename__ = "vision_classifications"

    id = Column(String(36), primary_key=True, index=True)
    artifact_id = Column(String(36), ForeignKey("vision_artifacts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    document_type = Column(String(64), nullable=False)  # face_sheet, ecg, medication_label, etc.
    confidence = Column(Float, nullable=False)
    model_version = Column(String(64), nullable=True)
    review_state = Column(String(64), nullable=False, default="pending_review")
    classified_at = Column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# Vision Bounding Region
# ---------------------------------------------------------------------------

class VisionBoundingRegion(Base):
    """Bounding box/region for a Vision extraction within an artifact."""

    __tablename__ = "vision_bounding_regions"

    id = Column(String(36), primary_key=True, index=True)
    extraction_id = Column(String(36), ForeignKey("vision_extractions.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    page_number = Column(Integer, nullable=True)
    x = Column(Float, nullable=False)
    y = Column(Float, nullable=False)
    width = Column(Float, nullable=False)
    height = Column(Float, nullable=False)
    confidence = Column(Float, nullable=True)

    extraction = relationship("VisionExtraction", back_populates="bounding_regions")


# ---------------------------------------------------------------------------
# Vision Annotation
# ---------------------------------------------------------------------------

class VisionAnnotation(Base):
    """Structured annotation on a Vision extraction."""

    __tablename__ = "vision_annotations"

    id = Column(String(36), primary_key=True, index=True)
    extraction_id = Column(String(36), ForeignKey("vision_extractions.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    annotation_type = Column(String(64), nullable=False)
    annotation_value = Column(Text, nullable=False)
    confidence = Column(Float, nullable=True)

    extraction = relationship("VisionExtraction", back_populates="annotations")


# ---------------------------------------------------------------------------
# Vision Review Queue
# ---------------------------------------------------------------------------

class VisionReviewQueue(Base):
    """Review queue entry for a Vision extraction awaiting clinician review."""

    __tablename__ = "vision_review_queue"

    id = Column(String(36), primary_key=True, index=True)
    extraction_id = Column(String(36), ForeignKey("vision_extractions.id"), nullable=False, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    priority = Column(Integer, nullable=False, default=5)  # 1=highest, 10=lowest
    assigned_to_user_id = Column(String(255), nullable=True)
    queue_state = Column(String(64), nullable=False, default="pending")  # pending, in_review, completed, escalated
    escalation_reason = Column(Text, nullable=True)

    queued_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    version = Column(Integer, nullable=False, server_default=text("1"))

    review_actions = relationship("VisionReviewActionRecord", back_populates="queue_entry", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# Vision Review Action Record
# ---------------------------------------------------------------------------

class VisionReviewActionRecord(Base):
    """Audit record for a clinician review action on a Vision extraction."""

    __tablename__ = "vision_review_actions"

    id = Column(String(36), primary_key=True, index=True)
    queue_entry_id = Column(String(36), ForeignKey("vision_review_queue.id"), nullable=False, index=True)
    extraction_id = Column(String(36), ForeignKey("vision_extractions.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    action = Column(String(64), nullable=False)  # VisionReviewAction
    actor_id = Column(String(255), nullable=False)
    notes = Column(Text, nullable=True)
    edited_value_json = Column(Text, nullable=True)
    performed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)

    queue_entry = relationship("VisionReviewQueue", back_populates="review_actions")


# ---------------------------------------------------------------------------
# Vision Provenance Record
# ---------------------------------------------------------------------------

class VisionProvenanceRecord(Base):
    """Immutable provenance record for a Vision extraction.

    Provenance is NEVER destroyed. Every extraction has a complete
    lineage from source artifact to accepted chart value.
    """
    __tablename__ = "vision_provenance_records"

    id = Column(String(36), primary_key=True, index=True)
    extraction_id = Column(String(36), ForeignKey("vision_extractions.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    provenance_type = Column(String(64), nullable=False)  # source, model, review, acceptance
    provenance_detail_json = Column(Text, nullable=False)
    recorded_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)

    extraction = relationship("VisionExtraction", back_populates="provenance_records")


# ---------------------------------------------------------------------------
# Vision Model Version Registry
# ---------------------------------------------------------------------------

class VisionModelVersion(Base):
    """Registry of Vision model versions used for extractions."""

    __tablename__ = "vision_model_versions"

    id = Column(String(36), primary_key=True, index=True)
    model_name = Column(String(128), nullable=False, index=True)
    version = Column(String(64), nullable=False)
    capabilities_json = Column(Text, nullable=False)  # JSON list of supported proposal targets
    is_active = Column(Boolean, nullable=False, default=True)
    deployed_at = Column(DateTime(timezone=True), nullable=False)
    deprecated_at = Column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------------------
# Vision Chart Link
# ---------------------------------------------------------------------------

class VisionChartLink(Base):
    """Links a Vision artifact to a chart for context and audit."""

    __tablename__ = "vision_chart_links"

    id = Column(String(36), primary_key=True, index=True)
    artifact_id = Column(String(36), ForeignKey("vision_artifacts.id"), nullable=False, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    link_reason = Column(String(128), nullable=True)
    linked_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)

    artifact = relationship("VisionArtifact", back_populates="chart_links")


# ---------------------------------------------------------------------------
# Vision Quality Flag
# ---------------------------------------------------------------------------

class VisionQualityFlag(Base):
    """Quality flag raised during Vision processing."""

    __tablename__ = "vision_quality_flags"

    id = Column(String(36), primary_key=True, index=True)
    artifact_id = Column(String(36), ForeignKey("vision_artifacts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    flag_type = Column(String(64), nullable=False)  # low_confidence, blur, partial_capture, duplicate
    flag_detail = Column(Text, nullable=True)
    severity = Column(String(32), nullable=False, default="warning")  # info, warning, error
    flagged_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by_user_id = Column(String(255), nullable=True)

    artifact = relationship("VisionArtifact", back_populates="quality_flags")


# ---------------------------------------------------------------------------
# Vision Duplicate Cluster
# ---------------------------------------------------------------------------

class VisionDuplicateCluster(Base):
    """Cluster of potentially duplicate Vision artifacts."""

    __tablename__ = "vision_duplicate_clusters"

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)

    artifact_ids_json = Column(Text, nullable=False)  # JSON list of artifact IDs in cluster
    similarity_score = Column(Float, nullable=False)
    resolution_state = Column(String(64), nullable=False, default="pending")  # pending, resolved, dismissed
    resolved_by_user_id = Column(String(255), nullable=True)
    detected_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
