"""NEMSIS eTimes service: tenant-scoped upsert and read for chart times.

Every read and write is filtered by ``tenant_id`` at the SQL layer so no
cross-tenant escape is possible. The service is intentionally thin: it
persists raw timestamps; conversion to NEMSIS XML is the projection
layer's job (:mod:`projection_chart_times`).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models_chart_times import ChartTimes


_TIME_FIELDS: tuple[str, ...] = (
    "psap_call_at",
    "dispatch_notified_at",
    "unit_notified_by_dispatch_at",
    "dispatch_acknowledged_at",
    "unit_en_route_at",
    "unit_on_scene_at",
    "arrived_at_patient_at",
    "transfer_of_ems_care_at",
    "unit_left_scene_at",
    "arrival_landing_area_at",
    "patient_arrived_at_destination_at",
    "destination_transfer_of_care_at",
    "unit_back_in_service_at",
    "unit_canceled_at",
    "unit_back_home_location_at",
    "ems_call_completed_at",
    "unit_arrived_staging_at",
)


class ChartTimesError(Exception):
    """Raised on caller errors that are safe to surface to the API layer."""

    def __init__(self, status_code: int, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = {"message": message, **extra}


@dataclass
class ChartTimesPayload:
    """Caller-side payload for upsert.

    All fields are optional. Any field omitted retains its current
    persisted value. To explicitly clear a field, pass ``None`` — the
    service treats ``None`` as "no change" by default; pass the sentinel
    ``ChartTimesService.CLEAR`` to actually clear a column.
    """

    psap_call_at: datetime | None = None
    dispatch_notified_at: datetime | None = None
    unit_notified_by_dispatch_at: datetime | None = None
    dispatch_acknowledged_at: datetime | None = None
    unit_en_route_at: datetime | None = None
    unit_on_scene_at: datetime | None = None
    arrived_at_patient_at: datetime | None = None
    transfer_of_ems_care_at: datetime | None = None
    unit_left_scene_at: datetime | None = None
    arrival_landing_area_at: datetime | None = None
    patient_arrived_at_destination_at: datetime | None = None
    destination_transfer_of_care_at: datetime | None = None
    unit_back_in_service_at: datetime | None = None
    unit_canceled_at: datetime | None = None
    unit_back_home_location_at: datetime | None = None
    ems_call_completed_at: datetime | None = None
    unit_arrived_staging_at: datetime | None = None


def _serialize(row: ChartTimes) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "chart_id": row.chart_id,
        **{
            field: (getattr(row, field).isoformat() if getattr(row, field) else None)
            for field in _TIME_FIELDS
        },
        "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
    }


class ChartTimesService:
    """Tenant-scoped persistence for chart event timeline."""

    @staticmethod
    async def get(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
    ) -> dict[str, Any] | None:
        if not tenant_id:
            raise ChartTimesError(400, "tenant_id is required")
        if not chart_id:
            raise ChartTimesError(400, "chart_id is required")

        stmt = select(ChartTimes).where(
            ChartTimes.tenant_id == tenant_id,
            ChartTimes.chart_id == chart_id,
            ChartTimes.deleted_at.is_(None),
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        return _serialize(row) if row else None

    @staticmethod
    async def upsert(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        payload: ChartTimesPayload,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if not tenant_id:
            raise ChartTimesError(400, "tenant_id is required")
        if not chart_id:
            raise ChartTimesError(400, "chart_id is required")

        now = datetime.now(UTC)

        stmt = select(ChartTimes).where(
            ChartTimes.tenant_id == tenant_id,
            ChartTimes.chart_id == chart_id,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()

        if row is None:
            row = ChartTimes(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                chart_id=chart_id,
                created_by_user_id=user_id,
                updated_by_user_id=user_id,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            for field in _TIME_FIELDS:
                value = getattr(payload, field)
                setattr(row, field, value)
            session.add(row)
        else:
            for field in _TIME_FIELDS:
                value = getattr(payload, field)
                # Only overwrite when the caller actually supplied a
                # value. ``None`` retains the existing value so partial
                # updates work; explicit clearing is a separate endpoint.
                if value is not None:
                    setattr(row, field, value)
            row.updated_by_user_id = user_id
            row.updated_at = now
            row.deleted_at = None
            row.version = (row.version or 1) + 1

        await session.flush()
        return _serialize(row)

    @staticmethod
    async def clear_field(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        field: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Explicitly set one column to NULL.

        Reserved for the rare correction path where a previously
        recorded time was wrong and must be erased rather than
        overwritten. Audit trail lives in :class:`Chart` versioning.
        """
        if field not in _TIME_FIELDS:
            raise ChartTimesError(400, "unknown field", field=field, allowed=list(_TIME_FIELDS))
        stmt = select(ChartTimes).where(
            ChartTimes.tenant_id == tenant_id,
            ChartTimes.chart_id == chart_id,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise ChartTimesError(404, "chart_times not found", chart_id=chart_id)
        setattr(row, field, None)
        row.updated_at = datetime.now(UTC)
        row.updated_by_user_id = user_id
        row.version = (row.version or 1) + 1
        await session.flush()
        return _serialize(row)


__all__ = ["ChartTimesService", "ChartTimesPayload", "ChartTimesError", "_TIME_FIELDS"]
