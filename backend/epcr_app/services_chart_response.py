"""NEMSIS eResponse service: tenant-scoped upsert/read for chart response
metadata and typed delays.

Every read and write is filtered by ``tenant_id`` at the SQL layer so no
cross-tenant escape is possible. The service is intentionally thin: it
persists raw column values; conversion to NEMSIS XML is the projection
layer's job (:mod:`projection_chart_response`).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models_chart_response import (
    RESPONSE_DELAY_KINDS,
    ChartResponse,
    ChartResponseDelay,
)


# String/coded/number columns on epcr_chart_response that follow the
# "None means no change" partial-update semantic. The JSON list column
# is handled separately because ``None`` and ``[]`` are distinct.
_RESPONSE_SCALAR_FIELDS: tuple[str, ...] = (
    "agency_number",
    "agency_name",
    "type_of_service_requested_code",
    "standby_purpose_code",
    "unit_transport_capability_code",
    "unit_vehicle_number",
    "unit_call_sign",
    "vehicle_dispatch_address",
    "vehicle_dispatch_lat",
    "vehicle_dispatch_long",
    "vehicle_dispatch_usng",
    "beginning_odometer",
    "on_scene_odometer",
    "destination_odometer",
    "ending_odometer",
    "response_mode_to_scene_code",
)


# Public field set surfaced to the API layer (includes the JSON list).
_RESPONSE_FIELDS: tuple[str, ...] = _RESPONSE_SCALAR_FIELDS + (
    "additional_response_descriptors_json",
)


class ChartResponseError(Exception):
    """Raised on caller errors that are safe to surface to the API layer."""

    def __init__(self, status_code: int, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = {"message": message, **extra}


@dataclass
class ChartResponsePayload:
    """Caller-side payload for upsert.

    All fields are optional. Any field omitted (left as ``None``)
    retains its current persisted value. ``additional_response_descriptors_json``
    is a 1:M list payload: pass ``[]`` to clear, ``None`` to leave
    unchanged.
    """

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


@dataclass
class ChartResponseDelayPayload:
    """Caller-side payload for adding one typed delay row."""

    delay_kind: str
    delay_code: str
    sequence_index: int = 0


def _serialize_response(row: ChartResponse) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "chart_id": row.chart_id,
        **{field_name: getattr(row, field_name) for field_name in _RESPONSE_FIELDS},
        "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
    }


def _serialize_delay(row: ChartResponseDelay) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "chart_id": row.chart_id,
        "delay_kind": row.delay_kind,
        "delay_code": row.delay_code,
        "sequence_index": row.sequence_index,
        "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
    }


class ChartResponseService:
    """Tenant-scoped persistence for chart response metadata + delays."""

    # ---- Metadata (1:1) ----

    @staticmethod
    async def get(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
    ) -> dict[str, Any] | None:
        if not tenant_id:
            raise ChartResponseError(400, "tenant_id is required")
        if not chart_id:
            raise ChartResponseError(400, "chart_id is required")

        stmt = select(ChartResponse).where(
            ChartResponse.tenant_id == tenant_id,
            ChartResponse.chart_id == chart_id,
            ChartResponse.deleted_at.is_(None),
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        return _serialize_response(row) if row else None

    @staticmethod
    async def upsert(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        payload: ChartResponsePayload,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if not tenant_id:
            raise ChartResponseError(400, "tenant_id is required")
        if not chart_id:
            raise ChartResponseError(400, "chart_id is required")

        now = datetime.now(UTC)
        stmt = select(ChartResponse).where(
            ChartResponse.tenant_id == tenant_id,
            ChartResponse.chart_id == chart_id,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()

        if row is None:
            row = ChartResponse(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                chart_id=chart_id,
                created_by_user_id=user_id,
                updated_by_user_id=user_id,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            for f in _RESPONSE_SCALAR_FIELDS:
                setattr(row, f, getattr(payload, f))
            # JSON list: None means "no value yet"; [] means "explicitly empty".
            row.additional_response_descriptors_json = (
                payload.additional_response_descriptors_json
            )
            session.add(row)
        else:
            for f in _RESPONSE_SCALAR_FIELDS:
                value = getattr(payload, f)
                if value is not None:
                    setattr(row, f, value)
            if payload.additional_response_descriptors_json is not None:
                row.additional_response_descriptors_json = (
                    payload.additional_response_descriptors_json
                )
            row.updated_by_user_id = user_id
            row.updated_at = now
            row.deleted_at = None
            row.version = (row.version or 1) + 1

        await session.flush()
        return _serialize_response(row)

    # ---- Delays (1:M) ----

    @staticmethod
    async def list_delays(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        if not tenant_id:
            raise ChartResponseError(400, "tenant_id is required")
        if not chart_id:
            raise ChartResponseError(400, "chart_id is required")

        stmt = select(ChartResponseDelay).where(
            ChartResponseDelay.tenant_id == tenant_id,
            ChartResponseDelay.chart_id == chart_id,
        )
        if not include_deleted:
            stmt = stmt.where(ChartResponseDelay.deleted_at.is_(None))
        stmt = stmt.order_by(
            ChartResponseDelay.delay_kind,
            ChartResponseDelay.sequence_index,
            ChartResponseDelay.delay_code,
        )
        rows = (await session.execute(stmt)).scalars().all()
        return [_serialize_delay(r) for r in rows]

    @staticmethod
    async def add_delay(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        payload: ChartResponseDelayPayload,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if not tenant_id:
            raise ChartResponseError(400, "tenant_id is required")
        if not chart_id:
            raise ChartResponseError(400, "chart_id is required")
        if not payload.delay_kind:
            raise ChartResponseError(400, "delay_kind is required")
        if payload.delay_kind not in RESPONSE_DELAY_KINDS:
            raise ChartResponseError(
                400,
                "unknown delay_kind",
                delay_kind=payload.delay_kind,
                allowed=list(RESPONSE_DELAY_KINDS),
            )
        if not payload.delay_code:
            raise ChartResponseError(400, "delay_code is required")
        if payload.sequence_index is None or payload.sequence_index < 0:
            raise ChartResponseError(400, "sequence_index must be >= 0")

        now = datetime.now(UTC)

        # Reject duplicates within (chart, kind, code). Reuse a
        # soft-deleted row if present.
        stmt = select(ChartResponseDelay).where(
            ChartResponseDelay.tenant_id == tenant_id,
            ChartResponseDelay.chart_id == chart_id,
            ChartResponseDelay.delay_kind == payload.delay_kind,
            ChartResponseDelay.delay_code == payload.delay_code,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is not None and existing.deleted_at is None:
            raise ChartResponseError(
                409,
                "delay already recorded for this chart and kind",
                delay_kind=payload.delay_kind,
                delay_code=payload.delay_code,
            )
        if existing is not None and existing.deleted_at is not None:
            existing.sequence_index = payload.sequence_index
            existing.updated_by_user_id = user_id
            existing.updated_at = now
            existing.deleted_at = None
            existing.version = (existing.version or 1) + 1
            row = existing
        else:
            row = ChartResponseDelay(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                chart_id=chart_id,
                delay_kind=payload.delay_kind,
                delay_code=payload.delay_code,
                sequence_index=payload.sequence_index,
                created_by_user_id=user_id,
                updated_by_user_id=user_id,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            session.add(row)

        await session.flush()
        return _serialize_delay(row)

    @staticmethod
    async def delete_delay(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        delay_id: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if not tenant_id:
            raise ChartResponseError(400, "tenant_id is required")
        if not chart_id:
            raise ChartResponseError(400, "chart_id is required")
        if not delay_id:
            raise ChartResponseError(400, "delay_id is required")

        stmt = select(ChartResponseDelay).where(
            ChartResponseDelay.tenant_id == tenant_id,
            ChartResponseDelay.chart_id == chart_id,
            ChartResponseDelay.id == delay_id,
            ChartResponseDelay.deleted_at.is_(None),
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise ChartResponseError(404, "delay not found", delay_id=delay_id)

        now = datetime.now(UTC)
        row.deleted_at = now
        row.updated_at = now
        row.updated_by_user_id = user_id
        row.version = (row.version or 1) + 1
        await session.flush()
        return _serialize_delay(row)


__all__ = [
    "ChartResponseService",
    "ChartResponsePayload",
    "ChartResponseDelayPayload",
    "ChartResponseError",
    "_RESPONSE_FIELDS",
    "_RESPONSE_SCALAR_FIELDS",
]
