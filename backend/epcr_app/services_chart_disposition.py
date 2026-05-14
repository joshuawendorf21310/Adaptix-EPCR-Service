"""NEMSIS eDisposition service: tenant-scoped upsert and read for chart disposition.

Every read and write is filtered by ``tenant_id`` at the SQL layer so no
cross-tenant escape is possible. The service is intentionally thin: it
persists raw scalar codes and JSON arrays; conversion to NEMSIS XML is
the projection layer's job (:mod:`projection_chart_disposition`).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models_chart_disposition import ChartDisposition


# Scalar columns: simple string codes / address strings.
_SCALAR_FIELDS: tuple[str, ...] = (
    "destination_name",
    "destination_code",
    "destination_address",
    "destination_city",
    "destination_county",
    "destination_state",
    "destination_zip",
    "destination_country",
    "type_of_destination_code",
    "incident_patient_disposition_code",
    "transport_mode_from_scene_code",
    "transport_disposition_code",
    "reason_not_transported_code",
    "level_of_care_provided_code",
    "position_during_transport_code",
    "condition_at_destination_code",
    "transferred_care_to_code",
    "destination_type_when_reason_code",
    "unit_disposition_code",
    "transport_method_code",
)

# JSON list (1:M repeating-group) columns: arrays of NEMSIS code values.
_LIST_FIELDS: tuple[str, ...] = (
    "hospital_capability_codes_json",
    "reason_for_choosing_destination_codes_json",
    "additional_transport_descriptors_codes_json",
    "hospital_incapability_codes_json",
    "prearrival_activation_codes_json",
    "type_of_destination_reason_codes_json",
    "destination_team_activations_codes_json",
    "crew_disposition_codes_json",
    "transport_method_additional_codes_json",
)

# All updatable domain columns.
_DISPOSITION_FIELDS: tuple[str, ...] = _SCALAR_FIELDS + _LIST_FIELDS


class ChartDispositionError(Exception):
    """Raised on caller errors that are safe to surface to the API layer."""

    def __init__(self, status_code: int, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = {"message": message, **extra}


@dataclass
class ChartDispositionPayload:
    """Caller-side payload for upsert.

    All fields are optional. Any field omitted retains its current
    persisted value. The service treats ``None`` as "no change" by
    default; explicit clearing is exposed via :py:meth:`clear_field`.
    """

    # Scalars
    destination_name: str | None = None
    destination_code: str | None = None
    destination_address: str | None = None
    destination_city: str | None = None
    destination_county: str | None = None
    destination_state: str | None = None
    destination_zip: str | None = None
    destination_country: str | None = None
    type_of_destination_code: str | None = None
    incident_patient_disposition_code: str | None = None
    transport_mode_from_scene_code: str | None = None
    transport_disposition_code: str | None = None
    reason_not_transported_code: str | None = None
    level_of_care_provided_code: str | None = None
    position_during_transport_code: str | None = None
    condition_at_destination_code: str | None = None
    transferred_care_to_code: str | None = None
    destination_type_when_reason_code: str | None = None
    unit_disposition_code: str | None = None
    transport_method_code: str | None = None

    # JSON list columns (1:M)
    hospital_capability_codes_json: list[str] | None = None
    reason_for_choosing_destination_codes_json: list[str] | None = None
    additional_transport_descriptors_codes_json: list[str] | None = None
    hospital_incapability_codes_json: list[str] | None = None
    prearrival_activation_codes_json: list[str] | None = None
    type_of_destination_reason_codes_json: list[str] | None = None
    destination_team_activations_codes_json: list[str] | None = None
    crew_disposition_codes_json: list[str] | None = None
    transport_method_additional_codes_json: list[str] | None = None


def _serialize(row: ChartDisposition) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "chart_id": row.chart_id,
        **{field_name: getattr(row, field_name) for field_name in _DISPOSITION_FIELDS},
        "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
    }


class ChartDispositionService:
    """Tenant-scoped persistence for chart disposition."""

    @staticmethod
    async def get(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
    ) -> dict[str, Any] | None:
        if not tenant_id:
            raise ChartDispositionError(400, "tenant_id is required")
        if not chart_id:
            raise ChartDispositionError(400, "chart_id is required")

        stmt = select(ChartDisposition).where(
            ChartDisposition.tenant_id == tenant_id,
            ChartDisposition.chart_id == chart_id,
            ChartDisposition.deleted_at.is_(None),
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        return _serialize(row) if row else None

    @staticmethod
    async def upsert(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        payload: ChartDispositionPayload,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if not tenant_id:
            raise ChartDispositionError(400, "tenant_id is required")
        if not chart_id:
            raise ChartDispositionError(400, "chart_id is required")

        now = datetime.now(UTC)

        stmt = select(ChartDisposition).where(
            ChartDisposition.tenant_id == tenant_id,
            ChartDisposition.chart_id == chart_id,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()

        if row is None:
            row = ChartDisposition(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                chart_id=chart_id,
                created_by_user_id=user_id,
                updated_by_user_id=user_id,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            for field_name in _DISPOSITION_FIELDS:
                value = getattr(payload, field_name)
                setattr(row, field_name, value)
            session.add(row)
        else:
            for field_name in _DISPOSITION_FIELDS:
                value = getattr(payload, field_name)
                # ``None`` retains existing value; explicit clearing
                # is a separate endpoint.
                if value is not None:
                    setattr(row, field_name, value)
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
        recorded value was wrong and must be erased rather than
        overwritten. Audit trail lives in :class:`Chart` versioning.
        """
        if field not in _DISPOSITION_FIELDS:
            raise ChartDispositionError(
                400,
                "unknown field",
                field=field,
                allowed=list(_DISPOSITION_FIELDS),
            )
        stmt = select(ChartDisposition).where(
            ChartDisposition.tenant_id == tenant_id,
            ChartDisposition.chart_id == chart_id,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise ChartDispositionError(
                404, "chart_disposition not found", chart_id=chart_id
            )
        setattr(row, field, None)
        row.updated_at = datetime.now(UTC)
        row.updated_by_user_id = user_id
        row.version = (row.version or 1) + 1
        await session.flush()
        return _serialize(row)


__all__ = [
    "ChartDispositionService",
    "ChartDispositionPayload",
    "ChartDispositionError",
    "_DISPOSITION_FIELDS",
    "_SCALAR_FIELDS",
    "_LIST_FIELDS",
]
