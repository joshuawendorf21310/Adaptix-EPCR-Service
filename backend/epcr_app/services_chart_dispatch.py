"""NEMSIS eDispatch service: tenant-scoped upsert and read for chart dispatch.

Every read and write is filtered by ``tenant_id`` at the SQL layer so no
cross-tenant escape is possible. The service is intentionally thin: it
persists raw coded values; conversion to NEMSIS XML is the projection
layer's job (:mod:`projection_chart_dispatch`).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models_chart_dispatch import ChartDispatch


_DISPATCH_FIELDS: tuple[str, ...] = (
    "dispatch_reason_code",
    "emd_performed_code",
    "emd_determinant_code",
    "dispatch_center_id",
    "dispatch_priority_code",
    "cad_record_id",
)


class ChartDispatchError(Exception):
    """Raised on caller errors that are safe to surface to the API layer."""

    def __init__(self, status_code: int, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = {"message": message, **extra}


@dataclass
class ChartDispatchPayload:
    """Caller-side payload for upsert.

    All fields are optional. Any field omitted (left as ``None``)
    retains its current persisted value. To explicitly clear a field,
    use :meth:`ChartDispatchService.clear_field`.
    """

    dispatch_reason_code: str | None = None
    emd_performed_code: str | None = None
    emd_determinant_code: str | None = None
    dispatch_center_id: str | None = None
    dispatch_priority_code: str | None = None
    cad_record_id: str | None = None


def _serialize(row: ChartDispatch) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "chart_id": row.chart_id,
        **{field: getattr(row, field) for field in _DISPATCH_FIELDS},
        "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
    }


class ChartDispatchService:
    """Tenant-scoped persistence for chart dispatch."""

    @staticmethod
    async def get(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
    ) -> dict[str, Any] | None:
        if not tenant_id:
            raise ChartDispatchError(400, "tenant_id is required")
        if not chart_id:
            raise ChartDispatchError(400, "chart_id is required")

        stmt = select(ChartDispatch).where(
            ChartDispatch.tenant_id == tenant_id,
            ChartDispatch.chart_id == chart_id,
            ChartDispatch.deleted_at.is_(None),
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        return _serialize(row) if row else None

    @staticmethod
    async def upsert(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        payload: ChartDispatchPayload,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if not tenant_id:
            raise ChartDispatchError(400, "tenant_id is required")
        if not chart_id:
            raise ChartDispatchError(400, "chart_id is required")

        now = datetime.now(UTC)

        stmt = select(ChartDispatch).where(
            ChartDispatch.tenant_id == tenant_id,
            ChartDispatch.chart_id == chart_id,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()

        if row is None:
            row = ChartDispatch(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                chart_id=chart_id,
                created_by_user_id=user_id,
                updated_by_user_id=user_id,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            for field in _DISPATCH_FIELDS:
                value = getattr(payload, field)
                setattr(row, field, value)
            session.add(row)
        else:
            for field in _DISPATCH_FIELDS:
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
        recorded dispatch value was wrong and must be erased rather
        than overwritten. Audit trail lives in :class:`Chart` versioning.
        """
        if field not in _DISPATCH_FIELDS:
            raise ChartDispatchError(
                400, "unknown field", field=field, allowed=list(_DISPATCH_FIELDS)
            )
        stmt = select(ChartDispatch).where(
            ChartDispatch.tenant_id == tenant_id,
            ChartDispatch.chart_id == chart_id,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise ChartDispatchError(404, "chart_dispatch not found", chart_id=chart_id)
        setattr(row, field, None)
        row.updated_at = datetime.now(UTC)
        row.updated_by_user_id = user_id
        row.version = (row.version or 1) + 1
        await session.flush()
        return _serialize(row)


__all__ = [
    "ChartDispatchService",
    "ChartDispatchPayload",
    "ChartDispatchError",
    "_DISPATCH_FIELDS",
]
