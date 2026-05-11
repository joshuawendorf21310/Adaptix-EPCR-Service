"""NEMSIS field-value API router.

Tenant-scoped HTTP surface for the row-per-occurrence NEMSIS field
ledger. Every route enforces real authentication via
``get_current_user`` and uses a real database session via
``get_session``. Tenant isolation is delegated to the service layer
and verified at the SQL level.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.services_nemsis_field_values import (
    FieldValuePayload,
    NemsisFieldValueError,
    NemsisFieldValueService,
)

logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/epcr/charts/{chart_id}/nemsis/field-values",
    tags=["nemsis-field-values"],
)


class FieldValueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: str = Field(..., min_length=1)
    element_number: str = Field(..., min_length=1)
    element_name: str = Field(..., min_length=1)
    value: Any = None
    group_path: str = ""
    occurrence_id: str = ""
    sequence_index: int = 0
    attributes: dict[str, Any] = Field(default_factory=dict)
    source: str = "manual"
    validation_status: str = "unvalidated"
    validation_issues: list[dict[str, Any]] = Field(default_factory=list)


class BulkFieldValuesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[FieldValueRequest] = Field(default_factory=list)


def _to_payload(req: FieldValueRequest, user_id: str | None) -> FieldValuePayload:
    return FieldValuePayload(
        section=req.section,
        element_number=req.element_number,
        element_name=req.element_name,
        value=req.value,
        group_path=req.group_path or "",
        occurrence_id=req.occurrence_id or "",
        sequence_index=req.sequence_index,
        attributes=dict(req.attributes or {}),
        source=req.source,
        validation_status=req.validation_status,
        validation_issues=list(req.validation_issues or []),
        user_id=user_id,
    )


def _raise(exc: NemsisFieldValueError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.post("", status_code=status.HTTP_201_CREATED)
async def upsert_field_value(
    chart_id: str,
    payload: FieldValueRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    tenant_id = str(current_user.tenant_id)
    user_id = str(getattr(current_user, "user_id", "") or "")
    try:
        result = await NemsisFieldValueService.upsert(
            session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            payload=_to_payload(payload, user_id or None),
        )
        await session.commit()
        return result
    except NemsisFieldValueError as exc:
        await session.rollback()
        _raise(exc)
    except Exception as exc:  # pragma: no cover - defensive
        await session.rollback()
        logger.exception("Unexpected error upserting NEMSIS field value")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "message": "Failed to upsert NEMSIS field value",
                "error": str(exc),
            },
        ) from exc


@router.post("/bulk", status_code=status.HTTP_200_OK)
async def bulk_upsert_field_values(
    chart_id: str,
    payload: BulkFieldValuesRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    tenant_id = str(current_user.tenant_id)
    user_id = str(getattr(current_user, "user_id", "") or "")
    try:
        results = await NemsisFieldValueService.bulk_save(
            session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            payloads=[_to_payload(p, user_id or None) for p in payload.items],
        )
        await session.commit()
        return {"items": results, "count": len(results)}
    except NemsisFieldValueError as exc:
        await session.rollback()
        _raise(exc)


@router.get("")
async def list_field_values(
    chart_id: str,
    section: str | None = Query(default=None),
    include_deleted: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    tenant_id = str(current_user.tenant_id)
    try:
        items = await NemsisFieldValueService.list_for_chart(
            session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            section=section,
            include_deleted=include_deleted,
        )
        return {"items": items, "count": len(items)}
    except NemsisFieldValueError as exc:
        _raise(exc)


@router.delete("/{row_id}", status_code=status.HTTP_200_OK)
async def soft_delete_field_value(
    chart_id: str,
    row_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    tenant_id = str(current_user.tenant_id)
    user_id = str(getattr(current_user, "user_id", "") or "")
    try:
        deleted = await NemsisFieldValueService.soft_delete(
            session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            row_id=row_id,
            user_id=user_id or None,
        )
        if not deleted:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "NEMSIS field value not found", "id": row_id},
            )
        await session.commit()
        return {"id": row_id, "deleted": True}
    except NemsisFieldValueError as exc:
        await session.rollback()
        _raise(exc)
