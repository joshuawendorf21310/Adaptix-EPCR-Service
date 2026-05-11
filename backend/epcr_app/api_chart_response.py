"""NEMSIS eResponse API router.

Tenant-scoped HTTP surface for the chart response section: 1:1
metadata (agency, unit, vehicle dispatch location, odometers, response
mode, additional response descriptors) plus the 1:M typed-delay
children. Every route enforces real authentication via
``get_current_user`` and uses a real database session via
``get_session``. Tenant isolation is delegated to the service layer
and verified at the SQL level.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.models_chart_response import RESPONSE_DELAY_KINDS
from epcr_app.projection_chart_response import project_chart_response
from epcr_app.services_chart_response import (
    ChartResponseDelayPayload,
    ChartResponseError,
    ChartResponsePayload,
    ChartResponseService,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/epcr/charts/{chart_id}/response",
    tags=["nemsis-eresponse"],
)


class ChartResponseRequest(BaseModel):
    """Caller request body for PUT /response.

    Every field is optional. Omitting a field leaves its current value
    intact. ``additional_response_descriptors_json`` follows list
    semantics: pass ``[]`` to clear; omit (or send ``null``) to leave
    unchanged.
    """

    model_config = ConfigDict(extra="forbid")

    agency_number: str | None = None
    agency_name: str | None = None
    type_of_service_requested_code: str | None = None
    standby_purpose_code: str | None = None
    unit_transport_capability_code: str | None = None
    unit_vehicle_number: str | None = None
    unit_call_sign: str | None = None
    vehicle_dispatch_address: str | None = None
    vehicle_dispatch_lat: float | None = None
    vehicle_dispatch_long: float | None = None
    vehicle_dispatch_usng: str | None = None
    beginning_odometer: float | None = None
    on_scene_odometer: float | None = None
    destination_odometer: float | None = None
    ending_odometer: float | None = None
    response_mode_to_scene_code: str | None = None
    additional_response_descriptors_json: list[str] | None = None


class ChartResponseDelayRequest(BaseModel):
    """Caller request body for POST /response/delays."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    code: str
    sequence_index: int = 0


class ChartResponseEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")


def _payload_from_request(req: ChartResponseRequest) -> ChartResponsePayload:
    return ChartResponsePayload(**req.model_dump(exclude_unset=False))


def _group_delays_by_kind(delays: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {k: [] for k in RESPONSE_DELAY_KINDS}
    for delay in delays:
        kind = delay.get("delay_kind")
        if kind in grouped:
            grouped[kind].append(delay)
    return grouped


@router.get("", response_model=ChartResponseEnvelope)
async def get_chart_response(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Return the response metadata + delays grouped by kind.

    Returns 404 only when both the metadata row is absent AND no
    delays have been recorded; otherwise returns whatever exists with
    ``meta=None`` if the 1:1 row is not yet written.
    """
    try:
        meta = await ChartResponseService.get(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
        )
        delays = await ChartResponseService.list_delays(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
        )
    except ChartResponseError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    if meta is None and not delays:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "chart_response not recorded", "chart_id": chart_id},
        )

    return {
        "chart_id": chart_id,
        "meta": meta,
        "delays_by_kind": _group_delays_by_kind(delays),
    }


@router.put("", response_model=ChartResponseEnvelope, status_code=status.HTTP_200_OK)
async def upsert_chart_response(
    chart_id: str,
    body: ChartResponseRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Upsert chart response metadata. Returns the persisted record
    plus current delays grouped by kind.

    Side effect: after writing the domain rows, projects the response
    into the registry-driven NEMSIS field-values ledger so the dataset
    XML builder can emit it on export.
    """
    try:
        meta = await ChartResponseService.upsert(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            payload=_payload_from_request(body),
            user_id=str(user.user_id),
        )
        await project_chart_response(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        delays = await ChartResponseService.list_delays(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
        )
        await session.commit()
    except ChartResponseError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return {
        "chart_id": chart_id,
        "meta": meta,
        "delays_by_kind": _group_delays_by_kind(delays),
    }


@router.post(
    "/delays",
    response_model=ChartResponseEnvelope,
    status_code=status.HTTP_201_CREATED,
)
async def add_chart_response_delay(
    chart_id: str,
    body: ChartResponseDelayRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Add one typed delay row to the chart.

    Body: ``{"kind": "<dispatch|response|scene|transport|turn_around>",
    "code": "<NEMSIS coded value>"}``. Returns the persisted delay row.
    """
    if body.kind not in RESPONSE_DELAY_KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "unknown delay kind",
                "kind": body.kind,
                "allowed": list(RESPONSE_DELAY_KINDS),
            },
        )
    try:
        row = await ChartResponseService.add_delay(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            payload=ChartResponseDelayPayload(
                delay_kind=body.kind,
                delay_code=body.code,
                sequence_index=body.sequence_index,
            ),
            user_id=str(user.user_id),
        )
        await project_chart_response(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartResponseError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return row


@router.delete("/delays/{delay_id}", response_model=ChartResponseEnvelope)
async def delete_chart_response_delay(
    chart_id: str,
    delay_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Soft-delete one typed delay row.

    The corresponding ledger row stays in place; a future projection
    pass will not reproduce it because the soft-deleted row is filtered
    out of :meth:`ChartResponseService.list_delays`.
    """
    try:
        row = await ChartResponseService.delete_delay(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            delay_id=delay_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartResponseError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return row


__all__ = ["router"]
