"""Offline Sync Engine models — mandatory offline-first operation.

Offline operation is mandatory, not optional.

Required behavior:
- Encrypted local database (Android/tablet)
- Append-only event log
- Offline chart creation, assessment, vitals, meds, procedures
- Offline Vision queue
- Offline signatures and attachments
- Resumable uploads
- Deterministic replay
- Conflict-safe merge
- Sync health visibility
- Explicit degraded-state handling

Forbidden:
- Fake sync completion
- Silent drop of failed uploads
- Hidden local-only clinical truth
- Overwriting server state without conflict handling
- Losing audit events during offline mode
- Marking chart finalized while offline unless backend confirms
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

class SyncEventType(str, Enum):
    CHART_CREATE = "chart_create"
    CHART_UPDATE = "chart_update"
    CHART_FINALIZE = "chart_finalize"
    VITALS_CREATE = "vitals_create"
    VITALS_UPDATE = "vitals_update"
    FINDING_CREATE = "finding_create"
    FINDING_UPDATE = "finding_update"
    OVERLAY_CREATE = "overlay_create"
    OVERLAY_UPDATE = "overlay_update"
    MEDICATION_CREATE = "medication_create"
    MEDICATION_UPDATE = "medication_update"
    INTERVENTION_CREATE = "intervention_create"
    INTERVENTION_UPDATE = "intervention_update"
    OPQRST_CREATE = "opqrst_create"
    OPQRST_UPDATE = "opqrst_update"
    SIGNATURE_CREATE = "signature_create"
    ATTACHMENT_CREATE = "attachment_create"
    VISION_ARTIFACT_QUEUE = "vision_artifact_queue"
    CAREGRAPH_NODE_CREATE = "caregraph_node_create"
    CAREGRAPH_EDGE_CREATE = "caregraph_edge_create"
    IMPRESSION_CREATE = "impression_create"
    IMPRESSION_UPDATE = "impression_update"
    CRITICAL_CARE_CREATE = "critical_care_create"
    CRITICAL_CARE_UPDATE = "critical_care_update"


class SyncEventStatus(str, Enum):
    PENDING = "pending"
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    FAILED = "failed"
    CONFLICT_DETECTED = "conflict_detected"
    CONFLICT_RESOLVED = "conflict_resolved"
    RETRYING = "retrying"


class ConflictResolutionStrategy(str, Enum):
    SERVER_WINS = "server_wins"
    CLIENT_WINS = "client_wins"
    MERGE = "merge"
    MANUAL_REVIEW = "manual_review"


class SyncHealthState(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    SYNC_FAILED = "sync_failed"
    PARTIAL = "partial"


# ---------------------------------------------------------------------------
# Sync Event Log (append-only)
# ---------------------------------------------------------------------------

class SyncEventLog(Base):
    """Append-only event log for offline-first sync.

    Every mutation made while offline is recorded as an event.
    Events are replayed deterministically on reconnection.
    Events are NEVER deleted — only marked as uploaded or failed.

    This is the source of truth for offline replay ordering.
    """
    __tablename__ = "epcr_sync_event_log"

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    chart_id = Column(String(36), nullable=True, index=True)  # nullable for pre-chart events
    device_id = Column(String(64), nullable=False, index=True)
    user_id = Column(String(255), nullable=False)

    event_type = Column(String(64), nullable=False, index=True)  # SyncEventType
    event_payload_json = Column(Text, nullable=False)  # full event payload for replay
    entity_type = Column(String(64), nullable=False)  # chart, vitals, finding, etc.
    entity_id = Column(String(36), nullable=False, index=True)

    # Ordering for deterministic replay
    local_sequence_number = Column(Integer, nullable=False, index=True)
    device_timestamp = Column(DateTime(timezone=True), nullable=False)

    # Sync state
    status = Column(String(32), nullable=False, default="pending", index=True)
    upload_attempts = Column(Integer, nullable=False, default=0)
    last_upload_attempt_at = Column(DateTime(timezone=True), nullable=True)
    uploaded_at = Column(DateTime(timezone=True), nullable=True)
    server_acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    error_detail = Column(Text, nullable=True)

    # Idempotency key for safe retry
    idempotency_key = Column(String(64), nullable=False, unique=True, index=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


# ---------------------------------------------------------------------------
# Sync Conflict Record
# ---------------------------------------------------------------------------

class SyncConflict(Base):
    """Conflict record when server and client state diverge.

    Conflicts are NEVER silently resolved. Every conflict is:
    - Recorded with full before/after state
    - Presented to the user or supervisor for resolution
    - Resolved with an explicit strategy
    - Audited
    """
    __tablename__ = "epcr_sync_conflicts"

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    chart_id = Column(String(36), nullable=False, index=True)
    device_id = Column(String(64), nullable=False)
    user_id = Column(String(255), nullable=False)

    sync_event_id = Column(String(36), ForeignKey("epcr_sync_event_log.id"), nullable=False, index=True)
    entity_type = Column(String(64), nullable=False)
    entity_id = Column(String(36), nullable=False, index=True)

    client_state_json = Column(Text, nullable=False)
    server_state_json = Column(Text, nullable=False)
    conflict_fields_json = Column(Text, nullable=False)  # JSON list of conflicting field names

    resolution_strategy = Column(String(64), nullable=True)  # ConflictResolutionStrategy
    resolved_state_json = Column(Text, nullable=True)
    resolved_by_user_id = Column(String(255), nullable=True)
    resolution_notes = Column(Text, nullable=True)

    detected_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    version = Column(Integer, nullable=False, server_default=text("1"))


# ---------------------------------------------------------------------------
# Upload Queue
# ---------------------------------------------------------------------------

class UploadQueueItem(Base):
    """Resumable upload queue item for media and attachments.

    Supports resumable uploads for Vision artifacts, signatures,
    and attachments captured offline.
    """
    __tablename__ = "epcr_upload_queue"

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    chart_id = Column(String(36), nullable=True, index=True)
    device_id = Column(String(64), nullable=False)
    user_id = Column(String(255), nullable=False)

    upload_type = Column(String(64), nullable=False)  # vision_artifact, signature, attachment
    local_path = Column(String(512), nullable=False)  # encrypted local storage path
    file_size_bytes = Column(Integer, nullable=True)
    content_type = Column(String(64), nullable=False)
    source_hash_sha256 = Column(String(64), nullable=False)

    # Resumable upload state
    upload_status = Column(String(32), nullable=False, default="pending")
    bytes_uploaded = Column(Integer, nullable=False, default=0)
    upload_session_id = Column(String(255), nullable=True)  # server-side resumable session ID
    upload_url = Column(String(512), nullable=True)

    upload_attempts = Column(Integer, nullable=False, default=0)
    last_attempt_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_detail = Column(Text, nullable=True)

    # Idempotency
    idempotency_key = Column(String(64), nullable=False, unique=True, index=True)

    queued_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))


# ---------------------------------------------------------------------------
# Sync Health Record
# ---------------------------------------------------------------------------

class SyncHealthRecord(Base):
    """Sync health snapshot for a device/session.

    Tracks the current sync state, pending event count, failed uploads,
    and last successful sync time. Displayed to the user as sync health.
    """
    __tablename__ = "epcr_sync_health"

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    device_id = Column(String(64), nullable=False, unique=True, index=True)
    user_id = Column(String(255), nullable=False)

    health_state = Column(String(32), nullable=False, default="healthy")  # SyncHealthState
    pending_events_count = Column(Integer, nullable=False, default=0)
    failed_events_count = Column(Integer, nullable=False, default=0)
    pending_uploads_count = Column(Integer, nullable=False, default=0)
    failed_uploads_count = Column(Integer, nullable=False, default=0)
    unresolved_conflicts_count = Column(Integer, nullable=False, default=0)

    last_successful_sync_at = Column(DateTime(timezone=True), nullable=True)
    last_sync_attempt_at = Column(DateTime(timezone=True), nullable=True)
    last_error_detail = Column(Text, nullable=True)

    # Degraded state context
    is_degraded = Column(Boolean, nullable=False, default=False)
    degraded_reason = Column(String(255), nullable=True)
    degraded_since = Column(DateTime(timezone=True), nullable=True)

    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


# ---------------------------------------------------------------------------
# Audit Envelope (offline audit events)
# ---------------------------------------------------------------------------

class AuditEnvelope(Base):
    """Offline audit envelope — audit events captured while offline.

    Audit events captured offline are stored in envelopes and uploaded
    as part of the sync process. Audit events are NEVER lost during
    offline mode.
    """
    __tablename__ = "epcr_audit_envelopes"

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    chart_id = Column(String(36), nullable=True, index=True)
    device_id = Column(String(64), nullable=False)
    user_id = Column(String(255), nullable=False)

    audit_events_json = Column(Text, nullable=False)  # JSON array of audit events
    event_count = Column(Integer, nullable=False)
    sequence_start = Column(Integer, nullable=False)
    sequence_end = Column(Integer, nullable=False)

    upload_status = Column(String(32), nullable=False, default="pending")
    uploaded_at = Column(DateTime(timezone=True), nullable=True)
    idempotency_key = Column(String(64), nullable=False, unique=True, index=True)

    captured_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
