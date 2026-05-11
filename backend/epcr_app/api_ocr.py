"""OCR API router for the EPCR service.

Exposes the OCR job lifecycle and field-candidate review queue under
/api/v1/epcr/ocr. All routes require JWT authentication via get_current_user
except the device-registry read endpoints (no-auth, used by Android).

Route summary:
  POST /jobs                                    — create OCR job
  GET  /jobs/{job_id}                           — get job status
  GET  /charts/{chart_id}/jobs                  — list jobs for chart
  POST /jobs/{job_id}/result                    — submit provider result + candidates
  GET  /charts/{chart_id}/candidates            — list pending candidates
  GET  /charts/{chart_id}/candidates/high-risk  — list high-risk pending
  POST /candidates/{candidate_id}/accept        — accept as-is
  POST /candidates/{candidate_id}/reject        — reject with reason
  POST /candidates/{candidate_id}/edit          — edit then accept
  POST /candidates/{candidate_id}/promote       — promote to chart field
  POST /candidates/{candidate_id}/flag          — flag for supervisor review
  GET  /device-registry                         — full registry (no auth)
  GET  /device-registry/{device_type}           — per-device registry (no auth)
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.device_ocr_registry import (
    DEVICE_FIELD_REGISTRY,
    get_fields_for_device,
)
from epcr_app.models.ocr import OcrFieldReviewAction
from epcr_app.services_ocr import HIGH_RISK_FIELD_KEYS, OcrJobService, OcrServiceError

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/epcr/ocr",
    tags=["ocr"],
)

# ---------------------------------------------------------------------------
# Role constants for promotion gate.
# ---------------------------------------------------------------------------

_PROMOTION_ROLES = {"provider", "supervisor", "admin", "owner", "superadmin"}


def _require_promotion_role(user: CurrentUser) -> None:
    """Raise 403 if the user does not hold a role that permits promotion."""
    user_roles = {r.lower() for r in user.roles}
    if not user_roles.intersection(_PROMOTION_ROLES):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Promoting OCR candidates requires provider, supervisor, or higher role",
                "required_roles": sorted(_PROMOTION_ROLES),
                "user_roles": sorted(user_roles),
            },
        )


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------


class CreateJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chart_id: str = Field(..., description="Chart the document belongs to")
    source_type: str = Field(..., description="OcrSourceType value")
    s3_key: str = Field(..., description="S3 object key for the uploaded document")


class SubmitResultRequest(BaseModel):
    """OCR worker submits raw provider response and extracted field list."""

    model_config = ConfigDict(extra="forbid")

    provider_name: str = Field(..., description="OCR provider name (e.g. textract)")
    raw_result: Any = Field(..., description="Raw provider response (any JSON)")
    device_type: str | None = Field(
        None,
        description=(
            "Device type key from DEVICE_FIELD_REGISTRY. "
            "When provided, extracted_fields entries are validated against the registry."
        ),
    )
    extracted_fields: list["ExtractedFieldItem"] = Field(
        default_factory=list,
        description="Per-field extraction payloads to store as OcrFieldCandidate rows",
    )


class ExtractedFieldItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_key: str
    raw_value: str
    normalized_value: str | None = None
    confidence_score: float = Field(0.0, ge=0.0, le=1.0)
    bounding_box: str | None = None
    nemsis_element: str | None = None
    chart_section: str = "unknown"
    is_high_risk: bool = False


class RejectCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(..., description="Rejection reason for audit trail")


class EditCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    corrected_value: str = Field(..., description="Corrected field value")


class FlagCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(None, description="Optional note for the supervisor")


# Rebuild forward reference
SubmitResultRequest.model_rebuild()


# ---------------------------------------------------------------------------
# Helper: convert ORM instances to plain dicts
# ---------------------------------------------------------------------------


def _job_to_dict(job) -> dict:
    return {
        "id": job.id,
        "tenant_id": job.tenant_id,
        "chart_id": job.chart_id,
        "document_id": job.document_id,
        "source_type": job.source_type.value if job.source_type else None,
        "s3_key": job.s3_key,
        "status": job.status.value if job.status else None,
        "requested_by_user_id": job.requested_by_user_id,
        "submitted_at": job.submitted_at.isoformat() if job.submitted_at else None,
        "extraction_completed_at": (
            job.extraction_completed_at.isoformat()
            if job.extraction_completed_at
            else None
        ),
        "reviewed_at": job.reviewed_at.isoformat() if job.reviewed_at else None,
        "reviewer_user_id": job.reviewer_user_id,
        "failure_reason": job.failure_reason,
    }


def _candidate_to_dict(candidate) -> dict:
    metadata: dict = {}
    if candidate.reviewer_note:
        try:
            parsed = json.loads(candidate.reviewer_note)
            if isinstance(parsed, dict) and "nemsis_element" in parsed:
                metadata = parsed
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "id": candidate.id,
        "job_id": candidate.job_id,
        "field_key": candidate.field_name,
        "raw_value": candidate.extracted_value,
        "normalized_value": candidate.normalized_value,
        "confidence": candidate.confidence.value if candidate.confidence else None,
        "confidence_score": candidate.confidence_score,
        "bounding_box": candidate.bounding_box,
        "review_status": candidate.review_status.value if candidate.review_status else None,
        "corrected_value": candidate.corrected_value,
        "reviewed_at": candidate.reviewed_at.isoformat() if candidate.reviewed_at else None,
        "nemsis_element": metadata.get("nemsis_element"),
        "chart_section": metadata.get("chart_section", "unknown"),
        "is_high_risk": metadata.get("is_high_risk", candidate.field_name in HIGH_RISK_FIELD_KEYS),
    }


def _review_to_dict(review) -> dict:
    return {
        "id": review.id,
        "candidate_id": review.candidate_id,
        "job_id": review.job_id,
        "reviewer_user_id": review.reviewer_user_id,
        "action": review.action.value if review.action else None,
        "corrected_value": review.corrected_value,
        "reviewer_note": review.reviewer_note,
        "reviewed_at": review.reviewed_at.isoformat() if review.reviewed_at else None,
    }


# ---------------------------------------------------------------------------
# Job routes
# ---------------------------------------------------------------------------


@router.post("/jobs", status_code=status.HTTP_201_CREATED)
async def create_ocr_job(
    body: CreateJobRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Create a new QUEUED OCR job for a chart document."""
    try:
        job = await OcrJobService.create_job(
            session,
            chart_id=body.chart_id,
            source_type=body.source_type,
            s3_key=body.s3_key,
            requested_by_user_id=str(user.user_id),
            tenant_id=str(user.tenant_id),
        )
        await session.commit()
    except OcrServiceError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return _job_to_dict(job)


@router.get("/jobs/{job_id}")
async def get_ocr_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Return an OCR job by ID."""
    job = await OcrJobService.get_job(session, job_id, str(user.tenant_id))
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "OCR job not found", "job_id": job_id},
        )
    return _job_to_dict(job)


@router.get("/charts/{chart_id}/jobs")
async def list_ocr_jobs(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """List all OCR jobs for a chart, newest first."""
    jobs = await OcrJobService.list_jobs(session, chart_id, str(user.tenant_id))
    return {
        "chart_id": chart_id,
        "count": len(jobs),
        "items": [_job_to_dict(j) for j in jobs],
    }


# ---------------------------------------------------------------------------
# Provider result submission
# ---------------------------------------------------------------------------


@router.post("/jobs/{job_id}/result", status_code=status.HTTP_201_CREATED)
async def submit_provider_result(
    job_id: str,
    body: SubmitResultRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Submit raw OCR provider result and create OcrFieldCandidate rows.

    Called by the OCR processing worker after the provider has returned
    extraction data. Validates device_type against DEVICE_FIELD_REGISTRY
    when provided, and enforces is_high_risk from HIGH_RISK_FIELD_KEYS.
    """
    tenant_id = str(user.tenant_id)

    # Validate device_type if supplied.
    device_fields_map: dict[str, Any] = {}
    if body.device_type:
        specs = get_fields_for_device(body.device_type)
        if specs is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": f"Unknown device_type '{body.device_type}'",
                    "valid_device_types": sorted(DEVICE_FIELD_REGISTRY.keys()),
                },
            )
        device_fields_map = {spec.field_key: spec for spec in specs}

    try:
        raw_str = (
            body.raw_result
            if isinstance(body.raw_result, str)
            else json.dumps(body.raw_result)
        )
        ocr_result = await OcrJobService.submit_provider_result(
            session,
            job_id=job_id,
            raw_result_json=raw_str,
            provider_name=body.provider_name,
            tenant_id=tenant_id,
        )
    except OcrServiceError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    # Create OcrFieldCandidate rows for each extracted field.
    candidates = []
    for field_item in body.extracted_fields:
        # Merge metadata from registry spec when available.
        spec = device_fields_map.get(field_item.field_key)
        nemsis_element = field_item.nemsis_element
        chart_section = field_item.chart_section
        is_high_risk = field_item.is_high_risk

        if spec is not None:
            if nemsis_element is None:
                nemsis_element = spec.nemsis_element
            if chart_section == "unknown":
                chart_section = spec.chart_section
            # Registry is authoritative for is_high_risk flag.
            is_high_risk = is_high_risk or spec.is_high_risk

        try:
            candidate = await OcrJobService.create_field_candidate(
                session,
                result_id=ocr_result.id,
                field_key=field_item.field_key,
                raw_value=field_item.raw_value,
                normalized_value=field_item.normalized_value,
                confidence_score=field_item.confidence_score,
                bounding_box=field_item.bounding_box,
                nemsis_element=nemsis_element,
                chart_section=chart_section,
                is_high_risk=is_high_risk,
            )
            candidates.append(candidate)
        except OcrServiceError as exc:
            await session.rollback()
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    await session.commit()

    return {
        "job_id": job_id,
        "result_id": ocr_result.id,
        "provider": body.provider_name,
        "candidate_count": len(candidates),
        "candidates": [_candidate_to_dict(c) for c in candidates],
    }


# ---------------------------------------------------------------------------
# Candidate review queue
# ---------------------------------------------------------------------------


@router.get("/charts/{chart_id}/candidates")
async def list_pending_candidates(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Return all PENDING OCR field candidates for a chart."""
    candidates = await OcrJobService.get_pending_candidates(
        session, chart_id, str(user.tenant_id)
    )
    return {
        "chart_id": chart_id,
        "count": len(candidates),
        "items": [_candidate_to_dict(c) for c in candidates],
    }


@router.get("/charts/{chart_id}/candidates/high-risk")
async def list_high_risk_pending(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Return all PENDING high-risk OCR field candidates for a chart."""
    candidates = await OcrJobService.get_high_risk_pending(
        session, chart_id, str(user.tenant_id)
    )
    return {
        "chart_id": chart_id,
        "count": len(candidates),
        "items": [_candidate_to_dict(c) for c in candidates],
    }


@router.post("/candidates/{candidate_id}/accept")
async def accept_candidate(
    candidate_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Accept an OCR field candidate as-is."""
    try:
        candidate = await OcrJobService.accept_candidate(
            session, candidate_id, str(user.user_id)
        )
        await session.commit()
    except OcrServiceError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return _candidate_to_dict(candidate)


@router.post("/candidates/{candidate_id}/reject")
async def reject_candidate(
    candidate_id: str,
    body: RejectCandidateRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Reject an OCR field candidate with a required reason."""
    try:
        candidate = await OcrJobService.reject_candidate(
            session, candidate_id, str(user.user_id), body.reason
        )
        await session.commit()
    except OcrServiceError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return _candidate_to_dict(candidate)


@router.post("/candidates/{candidate_id}/edit")
async def edit_candidate(
    candidate_id: str,
    body: EditCandidateRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Edit an OCR field candidate and accept it with the corrected value."""
    try:
        candidate = await OcrJobService.edit_and_accept(
            session, candidate_id, str(user.user_id), body.corrected_value
        )
        await session.commit()
    except OcrServiceError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return _candidate_to_dict(candidate)


@router.post("/candidates/{candidate_id}/promote")
async def promote_candidate(
    candidate_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Promote an accepted/corrected OCR field candidate into the chart.

    Requires the user to hold provider, supervisor, or higher role.
    High-risk candidates must be explicitly accepted (APPROVED or CORRECTED)
    before promotion — PENDING status is blocked regardless of confidence score.
    """
    _require_promotion_role(user)
    try:
        result = await OcrJobService.promote_to_chart(
            session, candidate_id, str(user.user_id)
        )
        await session.commit()
    except OcrServiceError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return result


@router.post("/candidates/{candidate_id}/flag")
async def flag_candidate(
    candidate_id: str,
    body: FlagCandidateRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Flag an OCR field candidate for supervisor review.

    Creates a REJECTED-family review record with a flag note so the
    supervisor queue can surface it. The candidate review_status is set
    to REJECTED with the flag note preserved.
    """
    note = body.note or "Flagged for supervisor review"
    try:
        candidate = await OcrJobService.reject_candidate(
            session,
            candidate_id,
            str(user.user_id),
            reason=f"[FLAGGED] {note}",
        )
        await session.commit()
    except OcrServiceError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    result = _candidate_to_dict(candidate)
    result["flagged"] = True
    result["flag_note"] = note
    return result


# ---------------------------------------------------------------------------
# Device registry (no auth — called by Android app)
# ---------------------------------------------------------------------------


@router.get("/device-registry")
async def get_device_registry() -> dict:
    """Return the full DEVICE_FIELD_REGISTRY as JSON.

    No authentication required. Used by the Android field app to discover
    which fields each device type exposes.
    """
    serialized: dict[str, list[dict]] = {}
    for device_type, specs in DEVICE_FIELD_REGISTRY.items():
        serialized[device_type] = [asdict(spec) for spec in specs]
    return {
        "device_types": sorted(DEVICE_FIELD_REGISTRY.keys()),
        "registry": serialized,
    }


@router.get("/device-registry/{device_type}")
async def get_device_registry_for_type(device_type: str) -> dict:
    """Return OcrFieldSpec list for a specific device type.

    No authentication required. Device type matching is case-insensitive.
    """
    specs = get_fields_for_device(device_type)
    if specs is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "message": f"Device type '{device_type}' not found in registry",
                "valid_device_types": sorted(DEVICE_FIELD_REGISTRY.keys()),
            },
        )
    return {
        "device_type": device_type.upper(),
        "field_count": len(specs),
        "fields": [asdict(spec) for spec in specs],
    }


__all__ = ["router"]
