"""Chart audit trail API.

Router prefix: /api/v1/epcr/audit
Tag:           audit

Endpoints
---------
GET  /charts/{chart_id}/field-history               — full field audit trail
GET  /charts/{chart_id}/field-history/{field_key}   — audit trail for one field
GET  /charts/{chart_id}/repeat-events               — all repeat button events
POST /charts/{chart_id}/field-audit                 — record a field change (internal)
GET  /charts/{chart_id}/late-entries                — list all late entries

Access control
--------------
Roles allowed to see any audit data:
    supervisor | qa_reviewer | medical_director | billing_reviewer | admin

Providers (all other roles) may only see their own entries
(actor_id == user.user_id).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, UTC

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.models_audit import ChartFieldAuditEvent, ChartRepeatEvent

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/epcr/audit",
    tags=["audit"],
)

# Roles that can see any audit data for a chart.
_PRIVILEGED_ROLES: frozenset[str] = frozenset(
    {"supervisor", "qa_reviewer", "medical_director", "billing_reviewer", "admin"}
)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class FieldAuditEventRequest(BaseModel):
    """Body for POST /charts/{chart_id}/field-audit (internal use)."""

    model_config = ConfigDict(extra="forbid")

    section: str
    nemsis_element: str | None = None
    field_key: str
    prior_value: str | None = None
    new_value: str | None = None
    source_type: str
    source_artifact_id: str | None = None
    source_artifact_type: str | None = None
    actor_role: str
    reason_for_change: str | None = None
    is_late_entry: bool = False
    validation_state: str | None = None
    export_state: str | None = None
    review_state: str | None = None
    chart_clock_ms: int | None = None


# ---------------------------------------------------------------------------
# Access-control helper
# ---------------------------------------------------------------------------

def _assert_audit_access(user: CurrentUser, row_actor_id: str | None = None) -> None:
    """Raise 403 if the user is not authorised to see this audit row.

    Privileged roles can see everything.  All other roles (providers, crew)
    can only see rows where actor_id matches their own user_id.
    """
    user_has_privilege = any(r in _PRIVILEGED_ROLES for r in user.roles)
    if user_has_privilege:
        return
    if row_actor_id is not None and str(user.user_id) == row_actor_id:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Insufficient role to access audit records for other users.",
    )


def _user_is_privileged(user: CurrentUser) -> bool:
    return any(r in _PRIVILEGED_ROLES for r in user.roles)


def _audit_row_to_dict(row: ChartFieldAuditEvent) -> dict:
    return {
        "id": row.id,
        "chart_id": row.chart_id,
        "tenant_id": row.tenant_id,
        "section": row.section,
        "nemsis_element": row.nemsis_element,
        "field_key": row.field_key,
        "prior_value": row.prior_value,
        "new_value": row.new_value,
        "source_type": row.source_type,
        "source_artifact_id": row.source_artifact_id,
        "source_artifact_type": row.source_artifact_type,
        "actor_id": row.actor_id,
        "actor_role": row.actor_role,
        "reason_for_change": row.reason_for_change,
        "is_late_entry": row.is_late_entry,
        "validation_state": row.validation_state,
        "export_state": row.export_state,
        "review_state": row.review_state,
        "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
        "chart_clock_ms": row.chart_clock_ms,
    }


def _repeat_row_to_dict(row: ChartRepeatEvent) -> dict:
    return {
        "id": row.id,
        "chart_id": row.chart_id,
        "tenant_id": row.tenant_id,
        "repeat_type": row.repeat_type,
        "prior_entry_id": row.prior_entry_id,
        "new_entry_id": row.new_entry_id,
        "repeated_fields_json": row.repeated_fields_json,
        "modified_fields_json": row.modified_fields_json,
        "actor_id": row.actor_id,
        "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
        "nemsis_section": row.nemsis_section,
        "validation_state": row.validation_state,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/charts/{chart_id}/field-history")
async def get_field_history(
    chart_id: str,
    section: str | None = Query(default=None, description="Filter by NEMSIS section"),
    source_type: str | None = Query(default=None, description="Filter by source_type"),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Return the full field audit trail for a chart.

    Privileged roles see all events.  Providers see only their own events.
    """
    stmt = (
        select(ChartFieldAuditEvent)
        .where(
            ChartFieldAuditEvent.chart_id == chart_id,
            ChartFieldAuditEvent.tenant_id == str(user.tenant_id),
        )
        .order_by(ChartFieldAuditEvent.occurred_at.desc())
        .limit(limit)
        .offset(offset)
    )

    if not _user_is_privileged(user):
        stmt = stmt.where(ChartFieldAuditEvent.actor_id == str(user.user_id))

    if section:
        stmt = stmt.where(ChartFieldAuditEvent.section == section)
    if source_type:
        stmt = stmt.where(ChartFieldAuditEvent.source_type == source_type)

    result = await session.execute(stmt)
    rows = result.scalars().all()
    return {
        "chart_id": chart_id,
        "count": len(rows),
        "limit": limit,
        "offset": offset,
        "items": [_audit_row_to_dict(r) for r in rows],
    }


@router.get("/charts/{chart_id}/field-history/{field_key}")
async def get_field_history_for_key(
    chart_id: str,
    field_key: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Return the audit trail for a specific field in a chart."""
    stmt = (
        select(ChartFieldAuditEvent)
        .where(
            ChartFieldAuditEvent.chart_id == chart_id,
            ChartFieldAuditEvent.tenant_id == str(user.tenant_id),
            ChartFieldAuditEvent.field_key == field_key,
        )
        .order_by(ChartFieldAuditEvent.occurred_at.desc())
    )

    if not _user_is_privileged(user):
        stmt = stmt.where(ChartFieldAuditEvent.actor_id == str(user.user_id))

    result = await session.execute(stmt)
    rows = result.scalars().all()
    return {
        "chart_id": chart_id,
        "field_key": field_key,
        "count": len(rows),
        "items": [_audit_row_to_dict(r) for r in rows],
    }


@router.get("/charts/{chart_id}/repeat-events")
async def get_repeat_events(
    chart_id: str,
    repeat_type: str | None = Query(default=None, description="Filter by repeat_type"),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Return all repeat button events for a chart."""
    stmt = (
        select(ChartRepeatEvent)
        .where(
            ChartRepeatEvent.chart_id == chart_id,
            ChartRepeatEvent.tenant_id == str(user.tenant_id),
        )
        .order_by(ChartRepeatEvent.occurred_at.desc())
    )

    if not _user_is_privileged(user):
        stmt = stmt.where(ChartRepeatEvent.actor_id == str(user.user_id))

    if repeat_type:
        stmt = stmt.where(ChartRepeatEvent.repeat_type == repeat_type)

    result = await session.execute(stmt)
    rows = result.scalars().all()
    return {
        "chart_id": chart_id,
        "count": len(rows),
        "items": [_repeat_row_to_dict(r) for r in rows],
    }


@router.post("/charts/{chart_id}/field-audit", status_code=status.HTTP_201_CREATED)
async def record_field_audit_event(
    chart_id: str,
    body: FieldAuditEventRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Record a field change event (called internally by other service modules).

    The actor is always the authenticated user — the body supplies metadata
    about the change but cannot override actor_id.
    """
    event = ChartFieldAuditEvent(
        id=str(uuid.uuid4()),
        chart_id=chart_id,
        tenant_id=str(user.tenant_id),
        section=body.section,
        nemsis_element=body.nemsis_element,
        field_key=body.field_key,
        prior_value=body.prior_value,
        new_value=body.new_value,
        source_type=body.source_type,
        source_artifact_id=body.source_artifact_id,
        source_artifact_type=body.source_artifact_type,
        actor_id=str(user.user_id),
        actor_role=body.actor_role,
        reason_for_change=body.reason_for_change,
        is_late_entry=body.is_late_entry,
        validation_state=body.validation_state,
        export_state=body.export_state,
        review_state=body.review_state,
        chart_clock_ms=body.chart_clock_ms,
        occurred_at=datetime.now(UTC),
    )

    try:
        session.add(event)
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.exception("Failed to persist field audit event for chart=%s", chart_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Failed to record field audit event", "error": str(exc)},
        ) from exc

    return _audit_row_to_dict(event)


@router.get("/charts/{chart_id}/late-entries")
async def get_late_entries(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Return all late-entry audit records for a chart.

    Only privileged roles may list all late entries.  Providers see their own.
    """
    stmt = (
        select(ChartFieldAuditEvent)
        .where(
            ChartFieldAuditEvent.chart_id == chart_id,
            ChartFieldAuditEvent.tenant_id == str(user.tenant_id),
            ChartFieldAuditEvent.is_late_entry == True,  # noqa: E712
        )
        .order_by(ChartFieldAuditEvent.occurred_at.desc())
    )

    if not _user_is_privileged(user):
        stmt = stmt.where(ChartFieldAuditEvent.actor_id == str(user.user_id))

    result = await session.execute(stmt)
    rows = result.scalars().all()
    return {
        "chart_id": chart_id,
        "count": len(rows),
        "items": [_audit_row_to_dict(r) for r in rows],
    }


__all__ = ["router"]
