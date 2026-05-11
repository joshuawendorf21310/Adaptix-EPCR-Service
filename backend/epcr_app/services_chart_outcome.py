"""NEMSIS eOutcome service: tenant-scoped upsert and read for chart outcome.

Every read and write is filtered by ``tenant_id`` at the SQL layer so no
cross-tenant escape is possible. The service is intentionally thin: it
persists raw NEMSIS coded values, JSON code lists, timestamps and free
text identifiers; conversion to NEMSIS XML is the projection layer's
job (:mod:`projection_chart_outcome`).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models_chart_outcome import ChartOutcome


# All persisted eOutcome columns in NEMSIS-canonical order. Used by
# upsert/clear/serialize so a new column only needs to be added once.
_OUTCOME_FIELDS: tuple[str, ...] = (
    "emergency_department_disposition_code",
    "hospital_disposition_code",
    "emergency_department_diagnosis_codes_json",
    "hospital_admission_diagnosis_codes_json",
    "hospital_procedures_performed_codes_json",
    "trauma_registry_incident_id",
    "hospital_outcome_at_discharge_code",
    "patient_disposition_from_emergency_department_at",
    "emergency_department_arrival_at",
    "emergency_department_admit_at",
    "emergency_department_discharge_at",
    "hospital_admit_at",
    "hospital_discharge_at",
    "icu_admit_at",
    "icu_discharge_at",
    "hospital_length_of_stay_days",
    "icu_length_of_stay_days",
    "final_patient_acuity_code",
    "cause_of_death_codes_json",
    "date_of_death",
    "medical_record_number",
    "receiving_facility_record_number",
    "referred_to_facility_code",
    "referred_to_facility_name",
)

# Columns whose persisted value is a list of NEMSIS codes (1:M).
_OUTCOME_LIST_FIELDS: frozenset[str] = frozenset(
    {
        "emergency_department_diagnosis_codes_json",
        "hospital_admission_diagnosis_codes_json",
        "hospital_procedures_performed_codes_json",
        "cause_of_death_codes_json",
    }
)

# Columns whose persisted value is a timezone-aware datetime.
_OUTCOME_DATETIME_FIELDS: frozenset[str] = frozenset(
    {
        "emergency_department_arrival_at",
        "emergency_department_admit_at",
        "emergency_department_discharge_at",
        "hospital_admit_at",
        "hospital_discharge_at",
        "icu_admit_at",
        "icu_discharge_at",
        "date_of_death",
    }
)


class ChartOutcomeError(Exception):
    """Raised on caller errors that are safe to surface to the API layer."""

    def __init__(self, status_code: int, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = {"message": message, **extra}


@dataclass
class ChartOutcomePayload:
    """Caller-side payload for upsert.

    Every field is optional. Any field omitted (left as ``None``)
    retains its current persisted value on update. To explicitly clear
    a field, use :meth:`ChartOutcomeService.clear_field`.
    """

    emergency_department_disposition_code: str | None = None
    hospital_disposition_code: str | None = None
    emergency_department_diagnosis_codes_json: list[str] | None = None
    hospital_admission_diagnosis_codes_json: list[str] | None = None
    hospital_procedures_performed_codes_json: list[str] | None = None
    trauma_registry_incident_id: str | None = None
    hospital_outcome_at_discharge_code: str | None = None
    patient_disposition_from_emergency_department_at: str | None = None
    emergency_department_arrival_at: datetime | None = None
    emergency_department_admit_at: datetime | None = None
    emergency_department_discharge_at: datetime | None = None
    hospital_admit_at: datetime | None = None
    hospital_discharge_at: datetime | None = None
    icu_admit_at: datetime | None = None
    icu_discharge_at: datetime | None = None
    hospital_length_of_stay_days: int | None = None
    icu_length_of_stay_days: int | None = None
    final_patient_acuity_code: str | None = None
    cause_of_death_codes_json: list[str] | None = None
    date_of_death: datetime | None = None
    medical_record_number: str | None = None
    receiving_facility_record_number: str | None = None
    referred_to_facility_code: str | None = None
    referred_to_facility_name: str | None = None


def _serialize_value(field: str, raw: Any) -> Any:
    if raw is None:
        return None
    if field in _OUTCOME_DATETIME_FIELDS:
        if isinstance(raw, datetime):
            return raw.isoformat()
        return raw
    return raw


def _serialize(row: ChartOutcome) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "chart_id": row.chart_id,
        **{
            field: _serialize_value(field, getattr(row, field))
            for field in _OUTCOME_FIELDS
        },
        "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
    }


class ChartOutcomeService:
    """Tenant-scoped persistence for chart hospital outcome linkage."""

    @staticmethod
    async def get(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
    ) -> dict[str, Any] | None:
        if not tenant_id:
            raise ChartOutcomeError(400, "tenant_id is required")
        if not chart_id:
            raise ChartOutcomeError(400, "chart_id is required")

        stmt = select(ChartOutcome).where(
            ChartOutcome.tenant_id == tenant_id,
            ChartOutcome.chart_id == chart_id,
            ChartOutcome.deleted_at.is_(None),
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        return _serialize(row) if row else None

    @staticmethod
    async def upsert(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        payload: ChartOutcomePayload,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if not tenant_id:
            raise ChartOutcomeError(400, "tenant_id is required")
        if not chart_id:
            raise ChartOutcomeError(400, "chart_id is required")

        now = datetime.now(UTC)

        stmt = select(ChartOutcome).where(
            ChartOutcome.tenant_id == tenant_id,
            ChartOutcome.chart_id == chart_id,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()

        if row is None:
            row = ChartOutcome(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                chart_id=chart_id,
                created_by_user_id=user_id,
                updated_by_user_id=user_id,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            for field in _OUTCOME_FIELDS:
                value = getattr(payload, field)
                setattr(row, field, value)
            session.add(row)
        else:
            for field in _OUTCOME_FIELDS:
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
        recorded outcome value was wrong and must be erased rather than
        overwritten. Audit trail lives in :class:`Chart` versioning.
        """
        if field not in _OUTCOME_FIELDS:
            raise ChartOutcomeError(
                400, "unknown field", field=field, allowed=list(_OUTCOME_FIELDS)
            )
        stmt = select(ChartOutcome).where(
            ChartOutcome.tenant_id == tenant_id,
            ChartOutcome.chart_id == chart_id,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise ChartOutcomeError(404, "chart_outcome not found", chart_id=chart_id)
        setattr(row, field, None)
        row.updated_at = datetime.now(UTC)
        row.updated_by_user_id = user_id
        row.version = (row.version or 1) + 1
        await session.flush()
        return _serialize(row)


__all__ = [
    "ChartOutcomeService",
    "ChartOutcomePayload",
    "ChartOutcomeError",
    "_OUTCOME_FIELDS",
    "_OUTCOME_LIST_FIELDS",
    "_OUTCOME_DATETIME_FIELDS",
]
