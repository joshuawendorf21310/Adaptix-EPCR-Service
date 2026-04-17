"""NEMSIS submission pipeline ORM models for the epcr domain.

Defines tables for resource packs, state submission lifecycle,
submission status history, and compliance studio scenario management.
All models align to the PostgreSQL schema in migration 004_add_nemsis_submission_pipeline.
"""
from datetime import datetime, UTC

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from epcr_app.models import Base


class NemsisPack(Base):
    """NEMSIS resource pack: a versioned collection of validation assets.

    Tracks a named bundle of NEMSIS 3.5.1 XSD schemas, Schematron rules,
    WSDL files, state datasets, or compliance studio scenario assets stored
    in S3. Each pack moves through a pending -> staged -> active -> archived
    lifecycle.

    Attributes:
        id: Unique pack identifier (UUID v4).
        tenant_id: Tenant identifier for multi-tenant isolation.
        name: Human-readable name for the pack.
        pack_type: Category of pack content (national_xsd, national_schematron,
            wi_state_dataset, wi_schematron, cs_scenarios, bundle).
        nemsis_version: NEMSIS specification version targeted by this pack.
        status: Lifecycle status (pending, staged, active, archived).
        s3_bucket: S3 bucket holding pack assets.
        s3_prefix: S3 key prefix under which all pack files are stored.
        file_count: Number of files contained in the pack.
        size_bytes: Aggregate size in bytes of all pack files.
        activated_at: Timestamp when the pack was set to active.
        created_at: Timestamp when the pack record was created (UTC).
        created_by_user_id: User who created the pack record.
        files: List of NemsisPackFile records belonging to this pack.
    """

    __tablename__ = "nemsis_resource_packs"

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    pack_type = Column(String(64), nullable=False)
    nemsis_version = Column(String(32), nullable=False, default="3.5.1")
    status = Column(String(32), nullable=False, default="pending")
    s3_bucket = Column(String(255), nullable=True)
    s3_prefix = Column(String(1024), nullable=True)
    file_count = Column(Integer, default=0, nullable=False)
    size_bytes = Column(BigInteger, default=0, nullable=False)
    activated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    created_by_user_id = Column(String(255), nullable=False)

    files = relationship("NemsisPackFile", backref="pack", cascade="all, delete-orphan")


class NemsisPackFile(Base):
    """A single file within a NEMSIS resource pack.

    Represents one asset file (XSD, Schematron, WSDL, scenario, or sample)
    that belongs to a NemsisPack. Stores the S3 key and integrity hash for
    verification.

    Attributes:
        id: Unique file record identifier (UUID v4).
        pack_id: Foreign key to the owning NemsisPack.
        file_name: Original filename of the asset.
        file_role: Functional role of the file (xsd, schematron, wsdl, scenario, sample).
        s3_key: Full S3 object key for the stored file.
        size_bytes: File size in bytes.
        sha256: SHA-256 hex digest of the file content for integrity verification.
        uploaded_at: Timestamp when the file was uploaded to S3 (UTC).
        pack: Relationship back to the owning NemsisPack.
    """

    __tablename__ = "nemsis_pack_files"

    id = Column(String(36), primary_key=True)
    pack_id = Column(String(36), ForeignKey("nemsis_resource_packs.id"), nullable=False)
    file_name = Column(String(512), nullable=False)
    file_role = Column(String(64), nullable=True)
    s3_key = Column(String(1024), nullable=True)
    size_bytes = Column(BigInteger, default=0, nullable=False)
    sha256 = Column(String(64), nullable=True)
    uploaded_at = Column(DateTime(timezone=True), nullable=False)


class NemsisSubmissionResult(Base):
    """State submission lifecycle record for a single NEMSIS 3.5.1 export.

    Tracks the full round-trip of submitting a NEMSIS-compliant PCR XML
    document to the state reporting endpoint, from initial queuing through
    acknowledgment or rejection. S3 references store the submitted XML,
    the state acknowledgment, and the full response payload.

    Attributes:
        id: Unique submission record identifier (UUID v4).
        tenant_id: Tenant identifier for multi-tenant isolation.
        chart_id: Foreign key to the epcr_charts table for the source PCR.
        export_id: Optional reference to a NEMSIS export record.
        submission_number: Unique submission tracking number assigned at submission time.
        state_endpoint_url: URL of the state SOAP or REST endpoint used.
        submission_status: Current status (pending, submitted, acknowledged,
            accepted, rejected, error).
        xml_s3_bucket: S3 bucket holding the submitted XML payload.
        xml_s3_key: S3 key for the submitted XML payload.
        ack_s3_bucket: S3 bucket holding the state acknowledgment document.
        ack_s3_key: S3 key for the state acknowledgment document.
        response_s3_bucket: S3 bucket holding the full state response document.
        response_s3_key: S3 key for the full state response document.
        payload_sha256: SHA-256 hex digest of the submitted XML for integrity verification.
        soap_message_id: SOAP message identifier from the submission envelope.
        soap_response_code: SOAP response code returned by the state endpoint.
        rejection_reason: Human-readable reason if submission was rejected.
        comparison_report_ref: S3 reference or identifier for a TAC comparison report.
        submitted_at: Timestamp when the XML was sent to the state endpoint.
        acknowledged_at: Timestamp when the state acknowledged receipt.
        resolved_at: Timestamp when the submission reached a terminal state.
        created_at: Timestamp when this record was created (UTC).
        created_by_user_id: User who initiated the submission.
        history: List of NemsisSubmissionStatusHistory records for this submission.
    """

    __tablename__ = "nemsis_submission_results"

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), nullable=False, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    export_id = Column(String(36), nullable=True)
    submission_number = Column(String(64), nullable=False)
    state_endpoint_url = Column(String(2048), nullable=True)
    submission_status = Column(String(32), nullable=False, default="pending")
    xml_s3_bucket = Column(String(255), nullable=True)
    xml_s3_key = Column(String(1024), nullable=True)
    ack_s3_bucket = Column(String(255), nullable=True)
    ack_s3_key = Column(String(1024), nullable=True)
    response_s3_bucket = Column(String(255), nullable=True)
    response_s3_key = Column(String(1024), nullable=True)
    payload_sha256 = Column(String(64), nullable=True)
    soap_message_id = Column(String(255), nullable=True)
    soap_response_code = Column(String(32), nullable=True)
    rejection_reason = Column(Text, nullable=True)
    comparison_report_ref = Column(String(1024), nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    created_by_user_id = Column(String(255), nullable=False)

    history = relationship(
        "NemsisSubmissionStatusHistory",
        backref="submission",
        cascade="all, delete-orphan",
    )


class NemsisSubmissionStatusHistory(Base):
    """Immutable status transition log for a NEMSIS state submission.

    Every change to a NemsisSubmissionResult's submission_status is recorded
    here, preserving from/to state, the acting user, an optional note, and
    an optional JSON snapshot of the payload at transition time.

    Attributes:
        id: Unique history entry identifier (UUID v4).
        submission_id: Foreign key to the owning NemsisSubmissionResult.
        tenant_id: Tenant identifier for multi-tenant isolation.
        from_status: Submission status before the transition (null for initial entry).
        to_status: Submission status after the transition.
        actor_user_id: User who caused the transition (null for system transitions).
        note: Optional operator note recorded at transition time.
        payload_snapshot_json: Optional JSON snapshot of relevant state at transition.
        transitioned_at: Timestamp when the transition occurred (UTC).
        submission: Relationship back to the owning NemsisSubmissionResult.
    """

    __tablename__ = "nemsis_submission_status_history"

    id = Column(String(36), primary_key=True)
    submission_id = Column(
        String(36),
        ForeignKey("nemsis_submission_results.id"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(String(36), nullable=False, index=True)
    from_status = Column(String(32), nullable=True)
    to_status = Column(String(32), nullable=False)
    actor_user_id = Column(String(255), nullable=True)
    note = Column(Text, nullable=True)
    payload_snapshot_json = Column(Text, nullable=True)
    transitioned_at = Column(DateTime(timezone=True), nullable=False)


class NemsisScenario(Base):
    """NEMSIS 2026 TAC Compliance Studio scenario definition and run state.

    Represents a named compliance studio (CS) test scenario sourced from
    the TAC 2026 scenario bundle. Scenarios may be global (tenant_id null)
    or tenant-scoped. Asset content is stored in S3 or embedded as JSON for
    local execution. Run state tracks the most recent execution result.

    Attributes:
        id: Unique scenario identifier (UUID v4).
        tenant_id: Tenant identifier; null indicates a global/system scenario.
        scenario_code: Unique TAC-assigned scenario code (e.g. 2026_DEM_1).
        title: Human-readable scenario title.
        description: Optional detailed description of the scenario.
        year: TAC specification year this scenario belongs to.
        category: Scenario category (DEM for demographic, EMS for clinical).
        asset_s3_bucket: S3 bucket holding the scenario asset files.
        asset_s3_key: S3 key for the scenario asset archive or definition file.
        asset_json: Embedded scenario definition JSON for local execution.
        status: Current run state (available, running, completed, failed).
        last_run_at: Timestamp of the most recent execution attempt.
        last_submission_id: Optional FK to the nemsis_submission_results record
            produced by the most recent run.
        created_at: Timestamp when the scenario record was created (UTC).
    """

    __tablename__ = "nemsis_cs_scenarios"

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), nullable=True)
    scenario_code = Column(String(64), nullable=False, unique=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    year = Column(Integer, nullable=False)
    category = Column(String(32), nullable=False)
    asset_s3_bucket = Column(String(255), nullable=True)
    asset_s3_key = Column(String(1024), nullable=True)
    asset_json = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="available")
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    last_submission_id = Column(String(36), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
