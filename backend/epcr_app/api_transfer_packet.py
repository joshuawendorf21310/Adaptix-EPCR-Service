"""Transfer packet review API.

Router prefix: /api/v1/epcr/transfer-packet
Tag:           transfer_packet

Endpoints
---------
POST  /charts/{chart_id}/import
GET   /charts/{chart_id}/imports
GET   /charts/{chart_id}/imports/{import_id}/manifest
POST  /charts/{chart_id}/imports/{import_id}/accept-field
POST  /charts/{chart_id}/imports/{import_id}/accept-all
POST  /charts/{chart_id}/imports/{import_id}/reject-field
POST  /charts/{chart_id}/imports/{import_id}/complete
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, UTC
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.models import PatientProfile, Assessment, MedicationAdministration
from epcr_app.models.ocr import OcrFieldCandidate, OcrJob, OcrFieldReviewStatus
from epcr_app.models_audit import ChartFieldAuditEvent
from epcr_app.transfer_packet_service import TransferPacketService, TransferPacketExtraction

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/epcr/transfer-packet",
    tags=["transfer_packet"],
)

_service = TransferPacketService()


# ---------------------------------------------------------------------------
# In-memory manifest store (keyed by import_id).
# In production this would be a DB table; here we keep it lightweight.
# ---------------------------------------------------------------------------
_import_store: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class TransferImportRequest(BaseModel):
    """Body for POST /charts/{chart_id}/import."""

    model_config = ConfigDict(extra="forbid")

    ocr_job_id: str


class AcceptFieldRequest(BaseModel):
    """Body for POST …/accept-field."""

    model_config = ConfigDict(extra="forbid")

    field_key: str
    section: str
    value: Any
    nemsis_element: str | None = None
    reason: str | None = None


class RejectFieldRequest(BaseModel):
    """Body for POST …/reject-field."""

    model_config = ConfigDict(extra="forbid")

    field_key: str
    section: str
    reason: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_import_or_404(chart_id: str, import_id: str) -> dict:
    record = _import_store.get(import_id)
    if not record or record.get("chart_id") != chart_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "transfer packet import not found", "import_id": import_id},
        )
    return record


async def _write_audit_event(
    session: AsyncSession,
    chart_id: str,
    tenant_id: str,
    actor: CurrentUser,
    section: str,
    field_key: str,
    new_value: Any,
    source_artifact_id: str,
    nemsis_element: str | None = None,
    reason: str | None = None,
) -> None:
    event = ChartFieldAuditEvent(
        id=str(uuid.uuid4()),
        chart_id=chart_id,
        tenant_id=tenant_id,
        section=section,
        nemsis_element=nemsis_element,
        field_key=field_key,
        prior_value=None,
        new_value=str(new_value) if new_value is not None else None,
        source_type="transfer_import",
        source_artifact_id=source_artifact_id,
        source_artifact_type="transfer_packet",
        actor_id=str(actor.user_id),
        actor_role=actor.roles[0] if actor.roles else "unknown",
        reason_for_change=reason,
        is_late_entry=False,
        occurred_at=datetime.now(UTC),
    )
    session.add(event)


async def _apply_field_to_chart(
    session: AsyncSession,
    chart_id: str,
    tenant_id: str,
    section: str,
    field_key: str,
    value: Any,
) -> None:
    """Write the accepted field value into the appropriate chart table/column."""
    if section == "ePatient":
        result = await session.execute(
            select(PatientProfile).where(
                PatientProfile.chart_id == chart_id,
                PatientProfile.tenant_id == tenant_id,
            )
        )
        profile = result.scalars().first()
        if profile and hasattr(profile, field_key):
            setattr(profile, field_key, value)
            session.add(profile)

    elif section == "eHistory":
        # eHistory fields are stored as chart assessment impression / notes or
        # as structured JSON on the assessment row for now.
        result = await session.execute(
            select(Assessment).where(
                Assessment.chart_id == chart_id,
                Assessment.tenant_id == tenant_id,
            )
        )
        assessment = result.scalars().first()
        if assessment:
            if field_key == "primary_diagnosis":
                assessment.field_diagnosis = str(value) if value else None
            elif field_key in {"past_medical_history", "allergies", "imaging_findings",
                                "procedures", "active_lines", "oxygen_requirements",
                                "vent_settings", "isolation_status", "code_status",
                                "dnr_polst_documented", "mobility_status", "sending_provider"}:
                import json
                notes = assessment.impression_notes or "{}"
                try:
                    notes_dict = json.loads(notes)
                except Exception:
                    notes_dict = {}
                notes_dict[field_key] = value
                assessment.impression_notes = json.dumps(notes_dict)
            session.add(assessment)

    elif section == "eMedications":
        # Transfer-packet medications are informational only; store them as a
        # new MedicationAdministration row tagged with the import source.
        if field_key == "current_medications" and isinstance(value, list):
            for med in value:
                med_name = med.get("name", "unknown") if isinstance(med, dict) else str(med)
                new_med = MedicationAdministration(
                    id=str(uuid.uuid4()),
                    chart_id=chart_id,
                    tenant_id=tenant_id,
                    medication_name=med_name,
                    dose_value=med.get("dose") if isinstance(med, dict) else None,
                    dose_unit=med.get("unit") if isinstance(med, dict) else None,
                    route=med.get("route", "unknown") if isinstance(med, dict) else "unknown",
                    indication="transfer_import",
                    administered_at=datetime.now(UTC),
                    administered_by_user_id="system",
                )
                session.add(new_med)

    # labs, allergies, eDisposition — additional section writers can be added
    # as those tables are created.  For now we record the audit event only.


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post(
    "/charts/{chart_id}/import",
    status_code=status.HTTP_201_CREATED,
)
async def submit_transfer_packet_import(
    chart_id: str,
    body: TransferImportRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Submit a transfer packet OCR job for AI mapping.

    Fetches OcrFieldCandidates for the given job, runs TransferPacketService
    extraction and section mapping, and returns the extraction + review manifest.
    """
    # Load candidates for this job scoped to the chart
    result = await session.execute(
        select(OcrJob).where(
            OcrJob.id == body.ocr_job_id,
            OcrJob.tenant_id == str(user.tenant_id),
        )
    )
    job = result.scalars().first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "OCR job not found", "ocr_job_id": body.ocr_job_id},
        )

    cand_result = await session.execute(
        select(OcrFieldCandidate).where(
            OcrFieldCandidate.job_id == body.ocr_job_id,
            OcrFieldCandidate.review_status != OcrFieldReviewStatus.REJECTED,
        )
    )
    candidates = cand_result.scalars().all()

    extraction: TransferPacketExtraction = await _service.extract_from_ocr_candidates(
        candidates=list(candidates),
        chart_id=chart_id,
        tenant_id=str(user.tenant_id),
    )

    mapped_sections = _service.map_to_epcr_sections(extraction)
    manifest = _service.build_review_manifest(mapped_sections)

    import_id = str(uuid.uuid4())
    _import_store[import_id] = {
        "import_id": import_id,
        "chart_id": chart_id,
        "tenant_id": str(user.tenant_id),
        "ocr_job_id": body.ocr_job_id,
        "status": "pending_review",
        "manifest": manifest,
        "field_states": {
            item["field_key"]: "pending"
            for item in manifest.get("items", [])
        },
        "submitted_by": str(user.user_id),
        "submitted_at": datetime.now(UTC).isoformat(),
        "completed_at": None,
    }

    return {
        "import_id": import_id,
        "chart_id": chart_id,
        "extraction": {
            "source_document_id": extraction.source_document_id,
            "extraction_id": extraction.extraction_id,
            "sending_facility": extraction.sending_facility,
            "receiving_facility": extraction.receiving_facility,
            "primary_diagnosis": extraction.primary_diagnosis,
            "diagnosis_list": extraction.diagnosis_list,
            "pmh": extraction.pmh,
            "allergies": extraction.allergies,
            "current_medications": extraction.current_medications,
            "current_infusions": extraction.current_infusions,
            "active_lines": extraction.active_lines,
            "oxygen_requirements": extraction.oxygen_requirements,
            "vent_settings": extraction.vent_settings,
            "labs": extraction.labs,
            "imaging_findings": extraction.imaging_findings,
            "procedures": extraction.procedures,
            "isolation_status": extraction.isolation_status,
            "code_status": extraction.code_status,
            "dnr_polst_documented": extraction.dnr_polst_documented,
            "mobility_status": extraction.mobility_status,
            "transfer_reason": extraction.transfer_reason,
            "confidence_scores": extraction.confidence_scores,
            "review_required_fields": extraction.review_required_fields,
            "extraction_warnings": extraction.extraction_warnings,
        },
        "manifest": manifest,
    }


@router.get("/charts/{chart_id}/imports")
async def list_transfer_packet_imports(
    chart_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """List all transfer packet imports for a chart."""
    items = [
        {
            "import_id": v["import_id"],
            "ocr_job_id": v["ocr_job_id"],
            "status": v["status"],
            "submitted_by": v["submitted_by"],
            "submitted_at": v["submitted_at"],
            "completed_at": v.get("completed_at"),
            "total_fields": v["manifest"]["total"],
            "high_risk_count": v["manifest"]["high_risk_count"],
        }
        for v in _import_store.values()
        if v.get("chart_id") == chart_id and v.get("tenant_id") == str(user.tenant_id)
    ]
    return {"chart_id": chart_id, "count": len(items), "items": items}


@router.get("/charts/{chart_id}/imports/{import_id}/manifest")
async def get_transfer_packet_manifest(
    chart_id: str,
    import_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Return the review manifest for a specific transfer packet import."""
    record = _get_import_or_404(chart_id, import_id)
    return {
        "import_id": import_id,
        "chart_id": chart_id,
        "status": record["status"],
        "manifest": record["manifest"],
        "field_states": record["field_states"],
    }


@router.post("/charts/{chart_id}/imports/{import_id}/accept-field")
async def accept_transfer_packet_field(
    chart_id: str,
    import_id: str,
    body: AcceptFieldRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Accept a single mapped field into the chart.

    1. Writes a ChartFieldAuditEvent (source_type=transfer_import).
    2. Applies the field value to the correct chart table/column.
    3. Marks the field as accepted in the in-memory manifest.
    """
    record = _get_import_or_404(chart_id, import_id)

    try:
        await _write_audit_event(
            session=session,
            chart_id=chart_id,
            tenant_id=str(user.tenant_id),
            actor=user,
            section=body.section,
            field_key=body.field_key,
            new_value=body.value,
            source_artifact_id=import_id,
            nemsis_element=body.nemsis_element,
            reason=body.reason,
        )
        await _apply_field_to_chart(
            session=session,
            chart_id=chart_id,
            tenant_id=str(user.tenant_id),
            section=body.section,
            field_key=body.field_key,
            value=body.value,
        )
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.exception("accept-field failed for chart=%s field=%s", chart_id, body.field_key)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Failed to accept field", "error": str(exc)},
        ) from exc

    record["field_states"][body.field_key] = "accepted"
    return {
        "import_id": import_id,
        "chart_id": chart_id,
        "field_key": body.field_key,
        "result": "accepted",
    }


@router.post("/charts/{chart_id}/imports/{import_id}/accept-all")
async def accept_all_transfer_packet_fields(
    chart_id: str,
    import_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Accept all non-high-risk fields at once.

    High-risk fields are skipped and must be accepted individually.
    """
    record = _get_import_or_404(chart_id, import_id)
    items = record["manifest"].get("items", [])
    accepted: list[str] = []
    skipped_high_risk: list[str] = []
    errors: list[str] = []

    for item in items:
        if item.get("high_risk"):
            skipped_high_risk.append(item["field_key"])
            continue
        if record["field_states"].get(item["field_key"]) in {"accepted", "rejected"}:
            continue
        try:
            await _write_audit_event(
                session=session,
                chart_id=chart_id,
                tenant_id=str(user.tenant_id),
                actor=user,
                section=item["section"],
                field_key=item["field_key"],
                new_value=item["value"],
                source_artifact_id=import_id,
                nemsis_element=item.get("nemsis_element"),
            )
            await _apply_field_to_chart(
                session=session,
                chart_id=chart_id,
                tenant_id=str(user.tenant_id),
                section=item["section"],
                field_key=item["field_key"],
                value=item["value"],
            )
            record["field_states"][item["field_key"]] = "accepted"
            accepted.append(item["field_key"])
        except Exception as exc:
            logger.warning("accept-all: failed field=%s err=%s", item["field_key"], exc)
            errors.append(item["field_key"])

    try:
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Commit failed during accept-all", "error": str(exc)},
        ) from exc

    return {
        "import_id": import_id,
        "chart_id": chart_id,
        "accepted_count": len(accepted),
        "accepted_fields": accepted,
        "skipped_high_risk": skipped_high_risk,
        "error_fields": errors,
    }


@router.post("/charts/{chart_id}/imports/{import_id}/reject-field")
async def reject_transfer_packet_field(
    chart_id: str,
    import_id: str,
    body: RejectFieldRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Reject a single mapped field — it will not be applied to the chart."""
    record = _get_import_or_404(chart_id, import_id)

    # Write an audit event for the rejection (new_value=None, prior_value=None)
    try:
        event = ChartFieldAuditEvent(
            id=str(uuid.uuid4()),
            chart_id=chart_id,
            tenant_id=str(user.tenant_id),
            section=body.section,
            field_key=body.field_key,
            source_type="transfer_import",
            source_artifact_id=import_id,
            source_artifact_type="transfer_packet",
            actor_id=str(user.user_id),
            actor_role=user.roles[0] if user.roles else "unknown",
            reason_for_change=body.reason,
            is_late_entry=False,
            review_state="rejected",
            occurred_at=datetime.now(UTC),
        )
        session.add(event)
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Failed to record rejection", "error": str(exc)},
        ) from exc

    record["field_states"][body.field_key] = "rejected"
    return {
        "import_id": import_id,
        "chart_id": chart_id,
        "field_key": body.field_key,
        "result": "rejected",
    }


@router.post("/charts/{chart_id}/imports/{import_id}/complete")
async def complete_transfer_packet_import(
    chart_id: str,
    import_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Mark a transfer packet import review as complete."""
    record = _get_import_or_404(chart_id, import_id)
    record["status"] = "review_complete"
    record["completed_at"] = datetime.now(UTC).isoformat()
    record["completed_by"] = str(user.user_id)
    return {
        "import_id": import_id,
        "chart_id": chart_id,
        "status": "review_complete",
        "completed_at": record["completed_at"],
    }


__all__ = ["router"]
