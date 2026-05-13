"""Pillar supplemental endpoints.

Registers the remaining pillar routes that are not covered by
``api_chart_workspace.py``. All routes enforce the standard tenant/auth
dependency stack and never commit inside the service layer — the handler
owns ``await session.commit()``.

Routes added here:
  POST   /api/v1/epcr/multi-patient-incidents                                (multi-patient)
  DELETE /api/v1/epcr/multi-patient-links/{link_id}                          (multi-patient)
  POST   /api/v1/epcr/chart-workspaces/{id}/prior-ecg/attach                 (prior-ecg)
  GET    /api/v1/epcr/chart-workspaces/{id}/protocol/satisfaction             (protocol)
  POST   /api/v1/epcr/chart-workspaces/{id}/overrides/{oid}/request-supervisor (audit/override)
  POST   /api/v1/epcr/chart-workspaces/{id}/overrides/{oid}/supervisor-confirm (audit/override)
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.services.multi_patient_service import (
    MultiPatientService,
    MultiPatientServiceError,
)
from epcr_app.services import prior_ecg_service as _prior_ecg_service
from epcr_app.services.protocol_context_service import ProtocolContextService
from epcr_app.services.provider_override_service import (
    ProviderOverrideService,
    ProviderOverrideValidationError,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/epcr",
    tags=["pillars"],
)


# ---------------------------------------------------------------------------
# Multi-patient pillar — top-level incident management
# ---------------------------------------------------------------------------

@router.post("/multi-patient-incidents", status_code=201)
async def create_multi_patient_incident(
    payload: dict = Body(default_factory=dict),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> Any:
    """Create a multi-patient incident parent row.

    Accepts the payload shape described in the multi-patient pillar
    handoff: ``parentIncidentNumber``, ``sceneAddress``, ``mciFlag``,
    ``patientCount``, ``mechanism``, ``hazardsText``, ``seedChartId``.
    """
    try:
        result = await MultiPatientService.create_incident(
            session,
            tenant_id=str(current_user.tenant_id),
            user_id=str(current_user.user_id),
            payload=payload,
            seed_chart_id=payload.get("seedChartId") or payload.get("seed_chart_id"),
        )
        await session.commit()
        return result
    except MultiPatientServiceError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc
    except Exception as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc


@router.delete("/multi-patient-links/{link_id}", status_code=200)
async def detach_multi_patient_link(
    link_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> Any:
    """Soft-delete (detach) a multi-patient link row."""
    try:
        result = await MultiPatientService.detach_chart(
            session,
            tenant_id=str(current_user.tenant_id),
            user_id=str(current_user.user_id),
            link_id=link_id,
        )
        await session.commit()
        return result
    except MultiPatientServiceError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail={"message": str(exc)}) from exc


# ---------------------------------------------------------------------------
# Prior-ECG pillar — attach endpoint
# ---------------------------------------------------------------------------

@router.post("/chart-workspaces/{chart_id}/prior-ecg/attach", status_code=201)
async def attach_prior_ecg(
    chart_id: str,
    payload: dict = Body(default_factory=dict),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> Any:
    """Attach a prior-ECG reference to a chart.

    Body keys (camelCase): ``priorChartId``, ``imageStorageUri``,
    ``encounterContext`` (required), ``monitorImported`` (bool),
    ``quality`` (one of good/acceptable/poor/unable_to_compare),
    ``capturedAt``, ``notes``.
    """
    try:
        row = await _prior_ecg_service.attach_prior(
            session,
            tenant_id=str(current_user.tenant_id),
            chart_id=chart_id,
            user_id=str(current_user.user_id),
            prior_chart_id=payload.get("priorChartId") or payload.get("prior_chart_id"),
            image_storage_uri=payload.get("imageStorageUri") or payload.get("image_storage_uri"),
            encounter_context=payload.get("encounterContext") or payload.get("encounter_context") or "",
            monitor_imported=bool(payload.get("monitorImported") or payload.get("monitor_imported", False)),
            quality=payload.get("quality") or "unable_to_compare",
            captured_at=payload.get("capturedAt") or payload.get("captured_at"),
            notes=payload.get("notes"),
        )
        await session.commit()
        return {
            "id": row.id,
            "chartId": row.chart_id,
            "capturedAt": row.captured_at.isoformat() if row.captured_at else None,
            "encounterContext": row.encounter_context,
            "imageStorageUri": row.image_storage_uri,
            "monitorImported": bool(row.monitor_imported),
            "quality": row.quality,
            "notes": row.notes,
        }
    except Exception as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc


# ---------------------------------------------------------------------------
# Protocol context pillar — satisfaction probe
# ---------------------------------------------------------------------------

@router.get("/chart-workspaces/{chart_id}/protocol/satisfaction")
async def get_protocol_satisfaction(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> Any:
    """Return the latest protocol required-field satisfaction payload."""
    try:
        return await ProtocolContextService.evaluate_required_field_satisfaction(
            session,
            str(current_user.tenant_id),
            chart_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc


# ---------------------------------------------------------------------------
# Provider-override pillar — supervisor workflow
# ---------------------------------------------------------------------------

@router.post("/chart-workspaces/{chart_id}/overrides/{override_id}/request-supervisor")
async def request_supervisor_for_override(
    chart_id: str,
    override_id: str,
    payload: dict = Body(default_factory=dict),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> Any:
    """Request supervisor confirmation for an existing provider override.

    Body: ``{ "supervisorId": "<user-id>" }``.
    """
    supervisor_id = payload.get("supervisorId") or payload.get("supervisor_id", "")
    try:
        result = await ProviderOverrideService.request_supervisor(
            session,
            tenant_id=str(current_user.tenant_id),
            chart_id=chart_id,
            user_id=str(current_user.user_id),
            override_id=override_id,
            supervisor_id=supervisor_id,
        )
        await session.commit()
        return result
    except ProviderOverrideValidationError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=422,
            detail={"errors": [{"field": getattr(exc, "field", None), "message": str(exc)}]},
        ) from exc
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail={"message": str(exc)}) from exc


@router.post("/chart-workspaces/{chart_id}/overrides/{override_id}/supervisor-confirm")
async def supervisor_confirm_override(
    chart_id: str,
    override_id: str,
    payload: dict = Body(default_factory=dict),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> Any:
    """Record the supervisor confirmation of a provider override.

    Body: ``{ "supervisorId": "<user-id>" }``.
    """
    supervisor_id = payload.get("supervisorId") or payload.get("supervisor_id", "")
    try:
        result = await ProviderOverrideService.supervisor_confirm(
            session,
            tenant_id=str(current_user.tenant_id),
            chart_id=chart_id,
            user_id=str(current_user.user_id),
            override_id=override_id,
            supervisor_id=supervisor_id,
        )
        await session.commit()
        return result
    except ProviderOverrideValidationError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=422,
            detail={"errors": [{"field": getattr(exc, "field", None), "message": str(exc)}]},
        ) from exc
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail={"message": str(exc)}) from exc
