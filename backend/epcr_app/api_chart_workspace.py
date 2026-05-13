"""Chart workspace API router.

Exposes a single high-level chart workspace contract that delegates to the
canonical EPCR chart, NEMSIS, finalization, export, and submission
services. Every route enforces real authentication via
``get_current_user`` and a real database session via ``get_session``. No
fabricated success.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.chart_workspace_service import (
    ALL_SECTIONS,
    ChartWorkspaceError,
    ChartWorkspaceService,
)
from epcr_app.db import get_session
from epcr_app.dependencies import CurrentUser, get_current_user

logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/epcr/chart-workspaces",
    tags=["chart-workspaces"],
)


class CreateWorkspaceRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    call_number: str | None = None
    incident_type: str = Field(..., min_length=1)
    client_reference_id: str | None = None
    patient_id: str | None = None
    agency_id: str | None = None
    agency_code: str | None = None
    incident_datetime: str | None = None
    cad_incident_number: str | None = None


class UpdateFieldRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    value: Any = None


def _raise_for_workspace_error(exc: ChartWorkspaceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.post("", status_code=201)
async def create_chart_workspace(
    payload: CreateWorkspaceRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Create a new chart and return its initial workspace payload."""
    try:
        return await ChartWorkspaceService.create_workspace_chart(
            session, current_user, payload.model_dump(exclude_none=True)
        )
    except ChartWorkspaceError as exc:
        _raise_for_workspace_error(exc)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Unexpected error creating chart workspace")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Failed to create chart workspace", "error": str(exc)},
        ) from exc


@router.get("/{chart_id}")
async def get_chart_workspace(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        return await ChartWorkspaceService.get_workspace(session, current_user, chart_id)
    except ChartWorkspaceError as exc:
        _raise_for_workspace_error(exc)


@router.patch("/{chart_id}/sections/{section}")
async def update_chart_workspace_section(
    chart_id: str,
    section: str,
    payload: dict = Body(default_factory=dict),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    if section not in ALL_SECTIONS:
        raise HTTPException(
            status_code=400,
            detail={"message": f"Unknown workspace section '{section}'", "section": section},
        )
    try:
        return await ChartWorkspaceService.update_workspace_section(
            session, current_user, chart_id, section, payload
        )
    except ChartWorkspaceError as exc:
        _raise_for_workspace_error(exc)


@router.patch("/{chart_id}/fields/{section}/{field_key}")
async def update_chart_workspace_field(
    chart_id: str,
    section: str,
    field_key: str,
    payload: UpdateFieldRequest = Body(default_factory=UpdateFieldRequest),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    if section not in ALL_SECTIONS:
        raise HTTPException(
            status_code=400,
            detail={"message": f"Unknown workspace section '{section}'", "section": section},
        )
    try:
        return await ChartWorkspaceService.update_workspace_field(
            session, current_user, chart_id, section, field_key, payload.value
        )
    except ChartWorkspaceError as exc:
        _raise_for_workspace_error(exc)


@router.get("/{chart_id}/readiness")
async def get_chart_workspace_readiness(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        return await ChartWorkspaceService.get_workspace_readiness(
            session, current_user, chart_id
        )
    except ChartWorkspaceError as exc:
        _raise_for_workspace_error(exc)


@router.post("/{chart_id}/validate")
async def validate_chart_workspace(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        return await ChartWorkspaceService.validate_workspace(
            session, current_user, chart_id
        )
    except ChartWorkspaceError as exc:
        _raise_for_workspace_error(exc)


@router.post("/{chart_id}/finalize")
async def finalize_chart_workspace(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        return await ChartWorkspaceService.finalize_workspace(
            session, current_user, chart_id
        )
    except ChartWorkspaceError as exc:
        _raise_for_workspace_error(exc)


@router.post("/{chart_id}/export")
async def export_chart_workspace(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        return await ChartWorkspaceService.export_workspace(
            session, current_user, chart_id
        )
    except ChartWorkspaceError as exc:
        _raise_for_workspace_error(exc)


@router.post("/{chart_id}/submit")
async def submit_chart_workspace(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        return await ChartWorkspaceService.submit_workspace(
            session, current_user, chart_id
        )
    except ChartWorkspaceError as exc:
        _raise_for_workspace_error(exc)


@router.get("/{chart_id}/status")
async def get_chart_workspace_status(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        return await ChartWorkspaceService.get_workspace_status(
            session, current_user, chart_id
        )
    except ChartWorkspaceError as exc:
        _raise_for_workspace_error(exc)


# --------------------------------------------------------------------------- #
# Pillar endpoints — one per shipped pillar. All routes share the workspace   #
# router prefix `/api/v1/epcr/chart-workspaces`, enforce the standard auth    #
# dependency, and translate service ValidationError / LookupError into HTTP   #
# 400/404 via ChartWorkspaceError. Each route is the minimum endpoint needed  #
# to satisfy the Five-Artifact Rule for its pillar.                           #
# --------------------------------------------------------------------------- #

from epcr_app.services import smart_text_service as _smart_text_service
from epcr_app.services import prior_ecg_service as _prior_ecg_service
from epcr_app.services import icd10_service as _icd10_service
from epcr_app.services.audit_trail_query_service import AuditTrailQueryService
from epcr_app.services.ecustom_field_service import ECustomFieldService
from epcr_app.services.ecustom_field_validation import (
    ValidationError as ECustomValidationError,
)
from epcr_app.services.map_location_service import MapLocationService
from epcr_app.services.multi_patient_service import (
    MultiPatientService,
    MultiPatientServiceError,
)
from epcr_app.services.protocol_context_service import ProtocolContextService
from epcr_app.services.provider_override_service import (
    ProviderOverrideService,
    ProviderOverrideValidationError,
)
from epcr_app.services.repeat_patient_service import (
    RepeatPatientService,
    RepeatPatientMatchNotFoundError,
    RepeatPatientReviewRequiredError,
)
from epcr_app.services.rxnorm_service import RxNormService
from epcr_app.services.sentence_evidence_service import SentenceEvidenceService


# -- ECustom values write ---------------------------------------------------

@router.patch("/{chart_id}/ecustom")
async def update_ecustom_values(
    chart_id: str,
    payload: dict = Body(default_factory=dict),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        await ECustomFieldService.replace_for_chart(
            session,
            tenant_id=str(current_user.tenant_id),
            chart_id=chart_id,
            user_id=str(current_user.user_id),
            agency_id=payload.get("agency_id") or "",
            values=payload.get("ecustom_values") or {},
        )
        await session.commit()
    except ECustomValidationError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=400,
            detail={"errors": list(exc.errors)},
        ) from exc
    return await ChartWorkspaceService.get_workspace(session, current_user, chart_id)


# -- Smart text -------------------------------------------------------------

@router.post("/{chart_id}/smart-text/resolve")
async def smart_text_resolve(
    chart_id: str,
    payload: dict = Body(default_factory=dict),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    section = (payload.get("section") or "").strip()
    field_key = (payload.get("fieldKey") or payload.get("field_key") or "").strip()
    if not section or not field_key:
        raise HTTPException(
            status_code=400,
            detail={"message": "section and fieldKey are required"},
        )
    return await _smart_text_service.resolve_for_field(
        session,
        str(current_user.tenant_id),
        chart_id,
        section,
        field_key,
    )


@router.post("/{chart_id}/smart-text/accept")
async def smart_text_accept(
    chart_id: str,
    payload: dict = Body(default_factory=dict),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    suggestion_id = payload.get("suggestionId") or payload.get("suggestion_id")
    if not suggestion_id:
        raise HTTPException(
            status_code=400, detail={"message": "suggestionId required"}
        )
    try:
        out = await _smart_text_service.accept(
            session,
            str(current_user.tenant_id),
            chart_id,
            str(current_user.user_id),
            suggestion_id,
        )
        await session.commit()
        return out
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"message": str(exc)}) from exc


@router.post("/{chart_id}/smart-text/reject")
async def smart_text_reject(
    chart_id: str,
    payload: dict = Body(default_factory=dict),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    suggestion_id = payload.get("suggestionId") or payload.get("suggestion_id")
    if not suggestion_id:
        raise HTTPException(
            status_code=400, detail={"message": "suggestionId required"}
        )
    try:
        out = await _smart_text_service.reject(
            session,
            str(current_user.tenant_id),
            chart_id,
            str(current_user.user_id),
            suggestion_id,
        )
        await session.commit()
        return out
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"message": str(exc)}) from exc


# -- Sentence evidence ------------------------------------------------------

@router.get("/{chart_id}/narrative/{narrative_id}/evidence")
async def list_sentence_evidence(
    chart_id: str,
    narrative_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    rows = await SentenceEvidenceService.list_for_chart(
        session,
        tenant_id=str(current_user.tenant_id),
        chart_id=chart_id,
        narrative_id=narrative_id,
    )
    return [
        {
            "id": r.id,
            "sentenceIndex": r.sentence_index,
            "sentenceText": r.sentence_text,
            "evidenceKind": r.evidence_kind,
            "evidenceRefId": r.evidence_ref_id,
            "confidence": float(r.confidence) if r.confidence is not None else 0.0,
            "providerConfirmed": bool(r.provider_confirmed),
        }
        for r in rows
    ]


@router.post(
    "/{chart_id}/narrative/{narrative_id}/evidence/{evidence_id}/confirm"
)
async def confirm_sentence_evidence(
    chart_id: str,
    narrative_id: str,
    evidence_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    row = await SentenceEvidenceService.confirm(
        session,
        tenant_id=str(current_user.tenant_id),
        chart_id=chart_id,
        user_id=str(current_user.user_id),
        evidence_id=evidence_id,
    )
    await session.commit()
    return {
        "id": row.id,
        "providerConfirmed": bool(row.provider_confirmed),
        "evidenceKind": row.evidence_kind,
    }


# -- Repeat patient ---------------------------------------------------------

@router.get("/{chart_id}/repeat-patient/matches")
async def list_repeat_patient_matches(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    # idempotent re-discovery would require the current patient payload; we
    # honestly return the persisted matches without re-running discovery.
    ws = await ChartWorkspaceService.get_workspace(session, current_user, chart_id)
    return ws.get("repeat_patient", {"matches": [], "priorCharts": []})


@router.post("/{chart_id}/repeat-patient/matches/{match_id}/review")
async def review_repeat_patient_match(
    chart_id: str,
    match_id: str,
    payload: dict = Body(default_factory=dict),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        row = await RepeatPatientService.review(
            session,
            tenant_id=str(current_user.tenant_id),
            chart_id=chart_id,
            user_id=str(current_user.user_id),
            match_id=match_id,
            carry_forward_allowed=bool(payload.get("carryForwardAllowed", False)),
        )
        await session.commit()
        return {"id": row.id, "reviewed": bool(row.reviewed),
                "carryForwardAllowed": bool(row.carry_forward_allowed)}
    except RepeatPatientMatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"message": str(exc)}) from exc


# -- Prior ECG --------------------------------------------------------------

@router.get("/{chart_id}/prior-ecg")
async def list_prior_ecg(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    rows = await _prior_ecg_service.list_prior_for_chart(
        session, str(current_user.tenant_id), chart_id
    )
    return [
        {
            "id": r.id,
            "capturedAt": r.captured_at.isoformat() if r.captured_at else None,
            "encounterContext": r.encounter_context,
            "imageStorageUri": r.image_storage_uri,
            "monitorImported": bool(r.monitor_imported),
            "quality": r.quality,
            "notes": r.notes,
        }
        for r in rows
    ]


@router.post("/{chart_id}/prior-ecg/{prior_id}/comparison")
async def record_prior_ecg_comparison(
    chart_id: str,
    prior_id: str,
    payload: dict = Body(default_factory=dict),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        row = await _prior_ecg_service.record_comparison(
            session,
            tenant_id=str(current_user.tenant_id),
            chart_id=chart_id,
            user_id=str(current_user.user_id),
            prior_ecg_id=prior_id,
            comparison_state=payload.get("comparison_state") or payload.get("comparisonState"),
            notes=payload.get("notes"),
        )
        await session.commit()
        return {
            "id": row.id,
            "priorEcgId": row.prior_ecg_id,
            "comparisonState": row.comparison_state,
            "providerConfirmed": bool(row.provider_confirmed),
        }
    except Exception as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc


# -- RxNorm -----------------------------------------------------------------

@router.post("/{chart_id}/medications/{med_id}/normalize")
async def normalize_rxnorm(
    chart_id: str,
    med_id: str,  # noqa: ARG001 - service iterates all admins for the chart
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    client = RxNormService.build_client() if hasattr(RxNormService, "build_client") else None
    try:
        outcomes = await RxNormService.normalize_for_chart(
            session,
            tenant_id=str(current_user.tenant_id),
            chart_id=chart_id,
            client=client,
        )
        await session.commit()
        return {"outcomes": [
            o.__dict__ if hasattr(o, "__dict__") else o for o in outcomes
        ]}
    finally:
        if client is not None and hasattr(client, "aclose"):
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001
                pass


# -- ICD-10 -----------------------------------------------------------------

@router.post("/{chart_id}/icd10/generate")
async def generate_icd10_prompts(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    prompts = await _icd10_service.generate_prompts_for_chart(
        session, str(current_user.tenant_id), chart_id
    )
    persisted = await _icd10_service.persist_prompts(
        session, prompts, user_id=str(current_user.user_id)
    )
    await session.commit()
    return {"suggestions": [_icd10_service.serialize(r) for r in persisted]}


@router.post("/{chart_id}/icd10/{suggestion_id}/acknowledge")
async def acknowledge_icd10_prompt(
    chart_id: str,
    suggestion_id: str,
    payload: dict = Body(default_factory=dict),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        row = await _icd10_service.acknowledge(
            session,
            str(current_user.tenant_id),
            chart_id,
            str(current_user.user_id),
            suggestion_id,
            payload.get("selected_code"),
        )
        await session.commit()
        return _icd10_service.serialize(row)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"message": str(exc)}) from exc


# -- Map location -----------------------------------------------------------

@router.post("/{chart_id}/map-locations")
async def record_map_location(
    chart_id: str,
    payload: dict = Body(default_factory=dict),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        result = await MapLocationService.record_location(
            session,
            tenant_id=str(current_user.tenant_id),
            chart_id=chart_id,
            kind=payload.get("kind"),
            lat=payload.get("latitude"),
            lng=payload.get("longitude"),
            accuracy=payload.get("accuracyMeters"),
            captured_at=payload.get("capturedAt"),
            user_id=str(current_user.user_id),
            facility_type=payload.get("facilityType"),
        )
        await session.commit()
        return result
    except Exception as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc


@router.post("/{chart_id}/route")
async def compute_route(
    chart_id: str,  # noqa: ARG001
    payload: dict = Body(default_factory=dict),
    session: AsyncSession = Depends(get_session),  # noqa: ARG001
    current_user: CurrentUser = Depends(get_current_user),  # noqa: ARG001
):
    return await MapLocationService.compute_route(
        payload.get("scene") or {}, payload.get("destination") or {}
    )


# -- Multi-patient ----------------------------------------------------------

@router.post("/{chart_id}/multi-patient/attach")
async def attach_to_multi_patient_incident(
    chart_id: str,
    payload: dict = Body(default_factory=dict),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        result = await MultiPatientService.attach_chart(
            session,
            tenant_id=str(current_user.tenant_id),
            user_id=str(current_user.user_id),
            incident_id=payload.get("incidentId"),
            chart_id=chart_id,
            patient_label=payload.get("patientLabel"),
            triage_category=payload.get("triageCategory"),
            acuity=payload.get("acuity"),
            transport_priority=payload.get("transportPriority"),
            destination_id=payload.get("destinationId"),
        )
        await session.commit()
        return result
    except MultiPatientServiceError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc


# -- Protocol context -------------------------------------------------------

@router.post("/{chart_id}/protocol/engage", status_code=201)
async def engage_protocol(
    chart_id: str,
    payload: dict = Body(default_factory=dict),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        row = await ProtocolContextService.engage(
            session,
            tenant_id=str(current_user.tenant_id),
            chart_id=chart_id,
            user_id=str(current_user.user_id),
            pack=payload.get("pack", ""),
        )
        await session.commit()
        return {
            "id": row.id,
            "active_pack": row.active_pack,
            "engaged_at": row.engaged_at.isoformat() if row.engaged_at else None,
            "engaged_by": row.engaged_by,
            "pack_version": row.pack_version,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc


@router.post("/{chart_id}/protocol/disengage")
async def disengage_protocol(
    chart_id: str,
    payload: dict = Body(default_factory=dict),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        row = await ProtocolContextService.disengage(
            session,
            tenant_id=str(current_user.tenant_id),
            chart_id=chart_id,
            user_id=str(current_user.user_id),
            reason=payload.get("reason", ""),
        )
        await session.commit()
        if row is None:
            return {"active_pack": None, "noop": True}
        return {
            "id": row.id,
            "active_pack": row.active_pack,
            "disengaged_at": row.disengaged_at.isoformat() if row.disengaged_at else None,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc


# -- Audit trail + provider override ---------------------------------------

@router.get("/{chart_id}/audit-trail")
async def list_audit_trail(
    chart_id: str,
    limit: int = 200,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    return await AuditTrailQueryService.list_for_chart(
        session,
        tenant_id=str(current_user.tenant_id),
        chart_id=chart_id,
        limit=limit,
    )


@router.post("/{chart_id}/overrides")
async def record_provider_override(
    chart_id: str,
    payload: dict = Body(default_factory=dict),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        result = await ProviderOverrideService.record(
            session,
            tenant_id=str(current_user.tenant_id),
            chart_id=chart_id,
            user_id=str(current_user.user_id),
            section=payload.get("section", ""),
            field_key=payload.get("fieldKey") or payload.get("field_key", ""),
            kind=payload.get("kind", ""),
            reason_text=payload.get("reasonText") or payload.get("reason_text", ""),
        )
        await session.commit()
        return result
    except ProviderOverrideValidationError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=422,
            detail={"errors": [{"field": getattr(exc, "field", None), "message": str(exc)}]},
        ) from exc
