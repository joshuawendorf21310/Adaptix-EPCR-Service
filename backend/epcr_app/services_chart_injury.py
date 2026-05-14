"""NEMSIS eInjury service: tenant-scoped upsert/read for chart injury + ACN.

Every read and write is filtered by ``tenant_id`` at the SQL layer so no
cross-tenant escape is possible. The service is intentionally thin: it
persists raw fields; conversion to NEMSIS XML is the projection layer's
job (:mod:`projection_chart_injury`).

Two persistence aggregates are handled here:

* :class:`ChartInjury` -- 1:1 with Chart, NEMSIS eInjury.01..10
* :class:`ChartInjuryAcn` -- 1:1 with ChartInjury, NEMSIS eInjury.11..29
  Automated Crash Notification Group

The two aggregates are stored in separate rows but presented as a
merged record by :meth:`ChartInjuryService.get`.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models_chart_injury import ChartInjury, ChartInjuryAcn


_INJURY_FIELDS: tuple[str, ...] = (
    "cause_of_injury_codes_json",
    "mechanism_of_injury_code",
    "trauma_triage_high_codes_json",
    "trauma_triage_moderate_codes_json",
    "vehicle_impact_area_code",
    "patient_location_in_vehicle_code",
    "occupant_safety_equipment_codes_json",
    "airbag_deployment_code",
    "height_of_fall_feet",
    "osha_ppe_used_codes_json",
)

_ACN_FIELDS: tuple[str, ...] = (
    "acn_system_company",
    "acn_incident_id",
    "acn_callback_phone",
    "acn_incident_at",
    "acn_incident_location",
    "acn_vehicle_body_type_code",
    "acn_vehicle_manufacturer",
    "acn_vehicle_make",
    "acn_vehicle_model",
    "acn_vehicle_model_year",
    "acn_multiple_impacts_code",
    "acn_delta_velocity",
    "acn_high_probability_code",
    "acn_pdof",
    "acn_rollover_code",
    "acn_seat_location_code",
    "seat_occupied_code",
    "acn_seatbelt_use_code",
    "acn_airbag_deployed_code",
)


class ChartInjuryError(Exception):
    """Raised on caller errors that are safe to surface to the API layer."""

    def __init__(self, status_code: int, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = {"message": message, **extra}


@dataclass
class ChartInjuryPayload:
    """Caller-side payload for eInjury.01..10 upsert.

    All fields are optional. Any field omitted (``None``) retains its
    current persisted value on update. To explicitly clear a column,
    use :meth:`ChartInjuryService.clear_field`.
    """

    cause_of_injury_codes_json: list[Any] | None = None
    mechanism_of_injury_code: str | None = None
    trauma_triage_high_codes_json: list[Any] | None = None
    trauma_triage_moderate_codes_json: list[Any] | None = None
    vehicle_impact_area_code: str | None = None
    patient_location_in_vehicle_code: str | None = None
    occupant_safety_equipment_codes_json: list[Any] | None = None
    airbag_deployment_code: str | None = None
    height_of_fall_feet: float | None = None
    osha_ppe_used_codes_json: list[Any] | None = None


@dataclass
class ChartInjuryAcnPayload:
    """Caller-side payload for eInjury.11..29 ACN block upsert.

    All fields are optional. Any field omitted (``None``) retains its
    current persisted value on update.
    """

    acn_system_company: str | None = None
    acn_incident_id: str | None = None
    acn_callback_phone: str | None = None
    acn_incident_at: datetime | None = None
    acn_incident_location: str | None = None
    acn_vehicle_body_type_code: str | None = None
    acn_vehicle_manufacturer: str | None = None
    acn_vehicle_make: str | None = None
    acn_vehicle_model: str | None = None
    acn_vehicle_model_year: int | None = None
    acn_multiple_impacts_code: str | None = None
    acn_delta_velocity: float | None = None
    acn_high_probability_code: str | None = None
    acn_pdof: int | None = None
    acn_rollover_code: str | None = None
    acn_seat_location_code: str | None = None
    seat_occupied_code: str | None = None
    acn_seatbelt_use_code: str | None = None
    acn_airbag_deployed_code: str | None = None


def _isofmt(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _serialize_injury(row: ChartInjury) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "chart_id": row.chart_id,
        **{f: _isofmt(getattr(row, f)) for f in _INJURY_FIELDS},
        "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
    }


def _serialize_acn(row: ChartInjuryAcn) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "chart_id": row.chart_id,
        "injury_id": row.injury_id,
        **{f: _isofmt(getattr(row, f)) for f in _ACN_FIELDS},
        "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
    }


class ChartInjuryService:
    """Tenant-scoped persistence for the eInjury aggregate + ACN block."""

    @staticmethod
    async def get(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
    ) -> dict[str, Any] | None:
        """Return the merged injury + acn record, or ``None`` if no injury row.

        Returns a dict with ``injury`` and ``acn`` sub-dicts; ``acn`` is
        ``None`` when no ACN block has been recorded.
        """
        if not tenant_id:
            raise ChartInjuryError(400, "tenant_id is required")
        if not chart_id:
            raise ChartInjuryError(400, "chart_id is required")

        injury_row = (
            await session.execute(
                select(ChartInjury).where(
                    ChartInjury.tenant_id == tenant_id,
                    ChartInjury.chart_id == chart_id,
                    ChartInjury.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()

        if injury_row is None:
            return None

        acn_row = (
            await session.execute(
                select(ChartInjuryAcn).where(
                    ChartInjuryAcn.tenant_id == tenant_id,
                    ChartInjuryAcn.chart_id == chart_id,
                    ChartInjuryAcn.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()

        return {
            "injury": _serialize_injury(injury_row),
            "acn": _serialize_acn(acn_row) if acn_row is not None else None,
        }

    @staticmethod
    async def get_injury(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
    ) -> dict[str, Any] | None:
        row = (
            await session.execute(
                select(ChartInjury).where(
                    ChartInjury.tenant_id == tenant_id,
                    ChartInjury.chart_id == chart_id,
                    ChartInjury.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        return _serialize_injury(row) if row else None

    @staticmethod
    async def get_acn(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
    ) -> dict[str, Any] | None:
        row = (
            await session.execute(
                select(ChartInjuryAcn).where(
                    ChartInjuryAcn.tenant_id == tenant_id,
                    ChartInjuryAcn.chart_id == chart_id,
                    ChartInjuryAcn.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        return _serialize_acn(row) if row else None

    @staticmethod
    async def upsert_injury(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        payload: ChartInjuryPayload,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if not tenant_id:
            raise ChartInjuryError(400, "tenant_id is required")
        if not chart_id:
            raise ChartInjuryError(400, "chart_id is required")

        now = datetime.now(UTC)

        row = (
            await session.execute(
                select(ChartInjury).where(
                    ChartInjury.tenant_id == tenant_id,
                    ChartInjury.chart_id == chart_id,
                )
            )
        ).scalar_one_or_none()

        if row is None:
            row = ChartInjury(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                chart_id=chart_id,
                created_by_user_id=user_id,
                updated_by_user_id=user_id,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            for f in _INJURY_FIELDS:
                setattr(row, f, getattr(payload, f))
            session.add(row)
        else:
            for f in _INJURY_FIELDS:
                value = getattr(payload, f)
                # ``None`` retains existing value; explicit clearing
                # uses :meth:`clear_field`.
                if value is not None:
                    setattr(row, f, value)
            row.updated_by_user_id = user_id
            row.updated_at = now
            row.deleted_at = None
            row.version = (row.version or 1) + 1

        await session.flush()
        return _serialize_injury(row)

    @staticmethod
    async def upsert_acn(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        payload: ChartInjuryAcnPayload,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if not tenant_id:
            raise ChartInjuryError(400, "tenant_id is required")
        if not chart_id:
            raise ChartInjuryError(400, "chart_id is required")

        # ACN block requires the parent injury row.
        injury_row = (
            await session.execute(
                select(ChartInjury).where(
                    ChartInjury.tenant_id == tenant_id,
                    ChartInjury.chart_id == chart_id,
                )
            )
        ).scalar_one_or_none()
        if injury_row is None:
            raise ChartInjuryError(
                409,
                "chart_injury must exist before acn block can be recorded",
                chart_id=chart_id,
            )

        now = datetime.now(UTC)

        row = (
            await session.execute(
                select(ChartInjuryAcn).where(
                    ChartInjuryAcn.tenant_id == tenant_id,
                    ChartInjuryAcn.chart_id == chart_id,
                )
            )
        ).scalar_one_or_none()

        if row is None:
            row = ChartInjuryAcn(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                chart_id=chart_id,
                injury_id=injury_row.id,
                created_by_user_id=user_id,
                updated_by_user_id=user_id,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            for f in _ACN_FIELDS:
                setattr(row, f, getattr(payload, f))
            session.add(row)
        else:
            for f in _ACN_FIELDS:
                value = getattr(payload, f)
                if value is not None:
                    setattr(row, f, value)
            row.updated_by_user_id = user_id
            row.updated_at = now
            row.deleted_at = None
            row.version = (row.version or 1) + 1

        await session.flush()
        return _serialize_acn(row)

    @staticmethod
    async def clear_field(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        field: str,
        block: str = "injury",
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Set one column to NULL on either the injury or acn block.

        ``block`` must be ``"injury"`` or ``"acn"``. The audit trail
        lives in :class:`Chart` versioning.
        """
        if block == "injury":
            if field not in _INJURY_FIELDS:
                raise ChartInjuryError(
                    400,
                    "unknown field",
                    field=field,
                    block=block,
                    allowed=list(_INJURY_FIELDS),
                )
            row = (
                await session.execute(
                    select(ChartInjury).where(
                        ChartInjury.tenant_id == tenant_id,
                        ChartInjury.chart_id == chart_id,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                raise ChartInjuryError(404, "chart_injury not found", chart_id=chart_id)
            setattr(row, field, None)
            row.updated_at = datetime.now(UTC)
            row.updated_by_user_id = user_id
            row.version = (row.version or 1) + 1
            await session.flush()
            return _serialize_injury(row)

        if block == "acn":
            if field not in _ACN_FIELDS:
                raise ChartInjuryError(
                    400,
                    "unknown field",
                    field=field,
                    block=block,
                    allowed=list(_ACN_FIELDS),
                )
            row = (
                await session.execute(
                    select(ChartInjuryAcn).where(
                        ChartInjuryAcn.tenant_id == tenant_id,
                        ChartInjuryAcn.chart_id == chart_id,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                raise ChartInjuryError(404, "chart_injury_acn not found", chart_id=chart_id)
            setattr(row, field, None)
            row.updated_at = datetime.now(UTC)
            row.updated_by_user_id = user_id
            row.version = (row.version or 1) + 1
            await session.flush()
            return _serialize_acn(row)

        raise ChartInjuryError(
            400, "unknown block", block=block, allowed=["injury", "acn"]
        )


__all__ = [
    "ChartInjuryService",
    "ChartInjuryPayload",
    "ChartInjuryAcnPayload",
    "ChartInjuryError",
    "_INJURY_FIELDS",
    "_ACN_FIELDS",
]
