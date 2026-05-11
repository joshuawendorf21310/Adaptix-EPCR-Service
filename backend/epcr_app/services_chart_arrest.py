"""NEMSIS eArrest service: tenant-scoped upsert and read for chart arrest.

Every read and write is filtered by ``tenant_id`` at the SQL layer so no
cross-tenant escape is possible. The service is intentionally thin: it
persists raw NEMSIS coded values, JSON code lists and timestamps;
conversion to NEMSIS XML is the projection layer's job
(:mod:`projection_chart_arrest`).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models_chart_arrest import ChartArrest


# All persisted eArrest columns in NEMSIS-canonical order. Used by
# upsert/clear/serialize so a new column only needs to be added once.
_ARREST_FIELDS: tuple[str, ...] = (
    "cardiac_arrest_code",
    "etiology_code",
    "resuscitation_attempted_codes_json",
    "witnessed_by_codes_json",
    "aed_use_prior_code",
    "cpr_type_codes_json",
    "hypothermia_indicator_code",
    "first_monitored_rhythm_code",
    "rosc_codes_json",
    "neurological_outcome_code",
    "arrest_at",
    "resuscitation_discontinued_at",
    "reason_discontinued_code",
    "rhythm_on_arrival_code",
    "end_of_event_code",
    "initial_cpr_at",
    "who_first_cpr_code",
    "who_first_aed_code",
    "who_first_defib_code",
)

# Columns whose persisted value is a list of NEMSIS codes (1:M).
_ARREST_LIST_FIELDS: frozenset[str] = frozenset(
    {
        "resuscitation_attempted_codes_json",
        "witnessed_by_codes_json",
        "cpr_type_codes_json",
        "rosc_codes_json",
    }
)

# Columns whose persisted value is a timezone-aware datetime.
_ARREST_DATETIME_FIELDS: frozenset[str] = frozenset(
    {
        "arrest_at",
        "resuscitation_discontinued_at",
        "initial_cpr_at",
    }
)


class ChartArrestError(Exception):
    """Raised on caller errors that are safe to surface to the API layer."""

    def __init__(self, status_code: int, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = {"message": message, **extra}


@dataclass
class ChartArrestPayload:
    """Caller-side payload for upsert.

    Every field is optional. Any field omitted (left as ``None``)
    retains its current persisted value on update. To explicitly clear
    a field, use :meth:`ChartArrestService.clear_field`.

    Note that ``cardiac_arrest_code`` (eArrest.01) is NOT NULL in the
    schema. The initial insert must therefore supply it; the service
    raises ``ChartArrestError`` otherwise.
    """

    cardiac_arrest_code: str | None = None
    etiology_code: str | None = None
    resuscitation_attempted_codes_json: list[str] | None = None
    witnessed_by_codes_json: list[str] | None = None
    aed_use_prior_code: str | None = None
    cpr_type_codes_json: list[str] | None = None
    hypothermia_indicator_code: str | None = None
    first_monitored_rhythm_code: str | None = None
    rosc_codes_json: list[str] | None = None
    neurological_outcome_code: str | None = None
    arrest_at: datetime | None = None
    resuscitation_discontinued_at: datetime | None = None
    reason_discontinued_code: str | None = None
    rhythm_on_arrival_code: str | None = None
    end_of_event_code: str | None = None
    initial_cpr_at: datetime | None = None
    who_first_cpr_code: str | None = None
    who_first_aed_code: str | None = None
    who_first_defib_code: str | None = None


def _serialize_value(field: str, raw: Any) -> Any:
    if raw is None:
        return None
    if field in _ARREST_DATETIME_FIELDS:
        if isinstance(raw, datetime):
            return raw.isoformat()
        return raw
    return raw


def _serialize(row: ChartArrest) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "chart_id": row.chart_id,
        **{
            field: _serialize_value(field, getattr(row, field))
            for field in _ARREST_FIELDS
        },
        "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
    }


class ChartArrestService:
    """Tenant-scoped persistence for chart cardiac arrest."""

    @staticmethod
    async def get(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
    ) -> dict[str, Any] | None:
        if not tenant_id:
            raise ChartArrestError(400, "tenant_id is required")
        if not chart_id:
            raise ChartArrestError(400, "chart_id is required")

        stmt = select(ChartArrest).where(
            ChartArrest.tenant_id == tenant_id,
            ChartArrest.chart_id == chart_id,
            ChartArrest.deleted_at.is_(None),
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        return _serialize(row) if row else None

    @staticmethod
    async def upsert(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        payload: ChartArrestPayload,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if not tenant_id:
            raise ChartArrestError(400, "tenant_id is required")
        if not chart_id:
            raise ChartArrestError(400, "chart_id is required")

        now = datetime.now(UTC)

        stmt = select(ChartArrest).where(
            ChartArrest.tenant_id == tenant_id,
            ChartArrest.chart_id == chart_id,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()

        if row is None:
            # eArrest.01 (cardiac_arrest_code) is NOT NULL — must be
            # provided on the initial insert.
            if not payload.cardiac_arrest_code:
                raise ChartArrestError(
                    400,
                    "cardiac_arrest_code is required for the initial arrest record",
                )
            row = ChartArrest(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                chart_id=chart_id,
                created_by_user_id=user_id,
                updated_by_user_id=user_id,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            for field in _ARREST_FIELDS:
                value = getattr(payload, field)
                setattr(row, field, value)
            session.add(row)
        else:
            for field in _ARREST_FIELDS:
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
        recorded arrest value was wrong and must be erased rather than
        overwritten. ``cardiac_arrest_code`` cannot be cleared because
        it is NOT NULL in the schema. Audit trail lives in
        :class:`Chart` versioning.
        """
        if field not in _ARREST_FIELDS:
            raise ChartArrestError(
                400, "unknown field", field=field, allowed=list(_ARREST_FIELDS)
            )
        if field == "cardiac_arrest_code":
            raise ChartArrestError(
                400,
                "cardiac_arrest_code is NOT NULL and cannot be cleared",
                field=field,
            )
        stmt = select(ChartArrest).where(
            ChartArrest.tenant_id == tenant_id,
            ChartArrest.chart_id == chart_id,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise ChartArrestError(404, "chart_arrest not found", chart_id=chart_id)
        setattr(row, field, None)
        row.updated_at = datetime.now(UTC)
        row.updated_by_user_id = user_id
        row.version = (row.version or 1) + 1
        await session.flush()
        return _serialize(row)


__all__ = [
    "ChartArrestService",
    "ChartArrestPayload",
    "ChartArrestError",
    "_ARREST_FIELDS",
    "_ARREST_LIST_FIELDS",
    "_ARREST_DATETIME_FIELDS",
]
