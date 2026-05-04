"""Vision integration API routes — governed perception layer.

Vision may ingest, classify, extract, project, and propose.
Vision may NEVER silently write clinical truth.
All proposals require explicit clinician review before acceptance.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, UTC
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.dependencies import get_current_user, get_tenant_id
from epcr_app.models_vision import (
    VisionArtifact,
    VisionExtraction,
    VisionReviewQueue,
    VisionReviewActionRecord,
    VisionIngestionJob,
    VisionChartLink,
    VisionQualityFlag,
    VisionProvenanceRecord,
)

router = APIRouter(prefix="/api/v1/epcr/vision", tags=["vision"])


class VisionArtifactIngest(BaseModel):
    chart_id: str
    ingestion_source: str
    content_type: str
    storage_path: str  # internal secure path — never public URL
    storage_bucket: Optional[str] = None
    file_size_bytes: Optional[int] = None
    source_hash_sha256: str
    original_filename: Optional[str] = None
    device_id: Optional[str] = None


class VisionReviewActionRequest(BaseModel):
    action: str  # accept, reject, edit_and_accept, route_for_recapture, escalate
    notes: Optional[str] = None
    edited_value_json: Optional[str] = None


@router.post("/artifacts", status_code=status.HTTP_201_CREATED)
async def ingest_vision_artifact(
    body: VisionArtifactIngest,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Ingest a Vision artifact for processing.

    Media URLs are NEVER stored publicly. Only internal secure storage paths.
    """
    artifact_id = str(uuid.uuid4())
    now = datetime.now(UTC)

    artifact = VisionArtifact(
        id=artifact_id,
        chart_id=body.chart_id,
        tenant_id=tenant_id,
        ingestion_source=body.ingestion_source,
        original_filename=body.original_filename,
        content_type=body.content_type,
        storage_path=body.storage_path,
        storage_bucket=body.storage_bucket,
        file_size_bytes=body.file_size_bytes,
        source_hash_sha256=body.source_hash_sha256,
        processing_status="pending",
        uploaded_by_user_id=user.user_id,
        device_id=body.device_id,
        uploaded_at=now,
        updated_at=now,
    )
    session.add(artifact)

    # Create ingestion job
    job_id = str(uuid.uuid4())
    session.add(VisionIngestionJob(
        id=job_id,
        artifact_id=artifact_id,
        tenant_id=tenant_id,
        status="queued",
        created_at=now,
    ))

    # Link to chart
    session.add(VisionChartLink(
        id=str(uuid.uuid4()),
        artifact_id=artifact_id,
        chart_id=body.chart_id,
        tenant_id=tenant_id,
        link_reason="ingestion",
        linked_at=now,
    ))

    await session.commit()
    return {
        "artifact_id": artifact_id,
        "job_id": job_id,
        "status": "queued",
        "processing_status": "pending",
    }


@router.get("/artifacts/{artifact_id}")
async def get_vision_artifact(
    artifact_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Get Vision artifact status and metadata."""
    result = await session.execute(
        select(VisionArtifact).where(
            VisionArtifact.id == artifact_id,
            VisionArtifact.tenant_id == tenant_id,
            VisionArtifact.deleted_at.is_(None),
        )
    )
    artifact = result.scalar_one_or_none()
    if not artifact:
        raise HTTPException(status_code=404, detail="artifact_not_found")

    return {
        "id": artifact.id,
        "chart_id": artifact.chart_id,
        "ingestion_source": artifact.ingestion_source,
        "content_type": artifact.content_type,
        "processing_status": artifact.processing_status,
        "processing_error": artifact.processing_error,
        "uploaded_at": artifact.uploaded_at.isoformat() if artifact.uploaded_at else None,
        "version": artifact.version,
    }


@router.get("/charts/{chart_id}/review-queue")
async def get_vision_review_queue(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Get pending Vision review queue items for a chart."""
    result = await session.execute(
        select(VisionReviewQueue).where(
            VisionReviewQueue.chart_id == chart_id,
            VisionReviewQueue.tenant_id == tenant_id,
            VisionReviewQueue.queue_state.in_(["pending", "in_review", "escalated"]),
        ).order_by(VisionReviewQueue.priority)
    )
    items = result.scalars().all()
    return {
        "queue_items": [
            {
                "id": item.id,
                "extraction_id": item.extraction_id,
                "priority": item.priority,
                "queue_state": item.queue_state,
                "assigned_to_user_id": item.assigned_to_user_id,
                "queued_at": item.queued_at.isoformat() if item.queued_at else None,
            }
            for item in items
        ],
        "count": len(items),
    }


@router.post("/review-queue/{queue_id}/action", status_code=status.HTTP_200_OK)
async def perform_vision_review_action(
    queue_id: str,
    body: VisionReviewActionRequest,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Perform a review action on a Vision extraction.

    Actions: accept, reject, edit_and_accept, route_for_recapture, escalate.
    Vision proposals NEVER auto-accept. Every acceptance is explicit.
    """
    result = await session.execute(
        select(VisionReviewQueue).where(
            VisionReviewQueue.id == queue_id,
            VisionReviewQueue.tenant_id == tenant_id,
        )
    )
    queue_item = result.scalar_one_or_none()
    if not queue_item:
        raise HTTPException(status_code=404, detail="queue_item_not_found")

    now = datetime.now(UTC)

    # Record the review action
    action_id = str(uuid.uuid4())
    session.add(VisionReviewActionRecord(
        id=action_id,
        queue_entry_id=queue_id,
        extraction_id=queue_item.extraction_id,
        tenant_id=tenant_id,
        action=body.action,
        actor_id=user.user_id,
        notes=body.notes,
        edited_value_json=body.edited_value_json,
        performed_at=now,
    ))

    # Update queue state
    if body.action in ("accept", "reject", "edit_and_accept"):
        queue_item.queue_state = "completed"
        queue_item.completed_at = now
    elif body.action == "escalate":
        queue_item.queue_state = "escalated"
        queue_item.escalation_reason = body.notes

    # Update extraction review state
    extraction_result = await session.execute(
        select(VisionExtraction).where(VisionExtraction.id == queue_item.extraction_id)
    )
    extraction = extraction_result.scalar_one_or_none()
    if extraction:
        if body.action == "accept":
            extraction.review_state = "accepted"
        elif body.action == "reject":
            extraction.review_state = "rejected"
        elif body.action == "edit_and_accept":
            extraction.review_state = "accepted"
            extraction.edited_value_json = body.edited_value_json
        extraction.reviewer_id = user.user_id
        extraction.reviewed_at = now
        extraction.reviewer_notes = body.notes

        # Record provenance
        session.add(VisionProvenanceRecord(
            id=str(uuid.uuid4()),
            extraction_id=queue_item.extraction_id,
            tenant_id=tenant_id,
            provenance_type="review",
            provenance_detail_json=json.dumps({
                "action": body.action,
                "actor_id": user.user_id,
                "performed_at": now.isoformat(),
            }),
            recorded_at=now,
        ))

    await session.commit()
    return {"action_id": action_id, "status": "recorded", "queue_state": queue_item.queue_state}


@router.get("/extractions/{extraction_id}")
async def get_vision_extraction(
    extraction_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Get a Vision extraction with confidence, provenance, and review state."""
    result = await session.execute(
        select(VisionExtraction).where(
            VisionExtraction.id == extraction_id,
            VisionExtraction.tenant_id == tenant_id,
            VisionExtraction.deleted_at.is_(None),
        )
    )
    extraction = result.scalar_one_or_none()
    if not extraction:
        raise HTTPException(status_code=404, detail="extraction_not_found")

    return {
        "id": extraction.id,
        "proposal_target": extraction.proposal_target,
        "extracted_value_json": extraction.extracted_value_json,
        "raw_text": extraction.raw_text,
        "confidence": extraction.confidence,
        "model_version": extraction.model_version,
        "review_state": extraction.review_state,
        "reviewer_id": extraction.reviewer_id,
        "reviewed_at": extraction.reviewed_at.isoformat() if extraction.reviewed_at else None,
        "edited_value_json": extraction.edited_value_json,
        "accepted_chart_field": extraction.accepted_chart_field,
        "extracted_at": extraction.extracted_at.isoformat() if extraction.extracted_at else None,
    }
