"""NEMSIS eSituation service: tenant-scoped CRUD for chart situation.

Every read and write is filtered by ``tenant_id`` at the SQL layer so no
cross-tenant escape is possible. The service is intentionally thin: it
persists raw coded values; conversion to NEMSIS XML is the projection
layer's job (:mod:`projection_chart_situation`).

Three persistence units:

- :class:`ChartSituationService` -- 1:1 scalar aggregate (eSituation.01..09,
  .11, .13..20).
- :class:`ChartSituationOtherSymptomService` -- 1:M repeating group for
  eSituation.10 Other Associated Symptoms.
- :class:`ChartSituationSecondaryImpressionService` -- 1:M repeating
  group for eSituation.12 Provider's Secondary Impressions.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models_chart_situation import (
    ChartSituation,
    ChartSituationOtherSymptom,
    ChartSituationSecondaryImpression,
)


# Scalar columns persisted on the 1:1 row. Order matches NEMSIS canonical
# eSituation element numbering for projection determinism.
_SITUATION_FIELDS: tuple[str, ...] = (
    "symptom_onset_at",
    "possible_injury_indicator_code",
    "complaint_type_code",
    "complaint_text",
    "complaint_duration_value",
    "complaint_duration_units_code",
    "chief_complaint_anatomic_code",
    "chief_complaint_organ_system_code",
    "primary_symptom_code",
    "provider_primary_impression_code",
    "initial_patient_acuity_code",
    "work_related_indicator_code",
    "patient_industry_code",
    "patient_occupation_code",
    "patient_activity_code",
    "last_known_well_at",
    "transfer_justification_code",
    "interfacility_transfer_reason_code",
)


class ChartSituationError(Exception):
    """Raised on caller errors that are safe to surface to the API layer."""

    def __init__(self, status_code: int, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = {"message": message, **extra}


@dataclass
class ChartSituationPayload:
    """Caller-side payload for 1:1 upsert.

    All fields are optional. Any field omitted (left as ``None``)
    retains its current persisted value. To explicitly clear a field,
    use :meth:`ChartSituationService.clear_field`.
    """

    symptom_onset_at: datetime | None = None
    possible_injury_indicator_code: str | None = None
    complaint_type_code: str | None = None
    complaint_text: str | None = None
    complaint_duration_value: int | None = None
    complaint_duration_units_code: str | None = None
    chief_complaint_anatomic_code: str | None = None
    chief_complaint_organ_system_code: str | None = None
    primary_symptom_code: str | None = None
    provider_primary_impression_code: str | None = None
    initial_patient_acuity_code: str | None = None
    work_related_indicator_code: str | None = None
    patient_industry_code: str | None = None
    patient_occupation_code: str | None = None
    patient_activity_code: str | None = None
    last_known_well_at: datetime | None = None
    transfer_justification_code: str | None = None
    interfacility_transfer_reason_code: str | None = None


def _serialize_dt(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _serialize(row: ChartSituation) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "chart_id": row.chart_id,
        **{field: _serialize_dt(getattr(row, field)) for field in _SITUATION_FIELDS},
        "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
    }


class ChartSituationService:
    """Tenant-scoped persistence for the eSituation 1:1 scalar row."""

    @staticmethod
    async def get(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
    ) -> dict[str, Any] | None:
        if not tenant_id:
            raise ChartSituationError(400, "tenant_id is required")
        if not chart_id:
            raise ChartSituationError(400, "chart_id is required")

        stmt = select(ChartSituation).where(
            ChartSituation.tenant_id == tenant_id,
            ChartSituation.chart_id == chart_id,
            ChartSituation.deleted_at.is_(None),
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        return _serialize(row) if row else None

    @staticmethod
    async def upsert(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        payload: ChartSituationPayload,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if not tenant_id:
            raise ChartSituationError(400, "tenant_id is required")
        if not chart_id:
            raise ChartSituationError(400, "chart_id is required")

        now = datetime.now(UTC)

        stmt = select(ChartSituation).where(
            ChartSituation.tenant_id == tenant_id,
            ChartSituation.chart_id == chart_id,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()

        if row is None:
            row = ChartSituation(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                chart_id=chart_id,
                created_by_user_id=user_id,
                updated_by_user_id=user_id,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            for field in _SITUATION_FIELDS:
                value = getattr(payload, field)
                setattr(row, field, value)
            session.add(row)
        else:
            for field in _SITUATION_FIELDS:
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
        recorded situation value was wrong and must be erased rather
        than overwritten. Audit trail lives in :class:`Chart` versioning.
        """
        if field not in _SITUATION_FIELDS:
            raise ChartSituationError(
                400, "unknown field", field=field, allowed=list(_SITUATION_FIELDS)
            )
        stmt = select(ChartSituation).where(
            ChartSituation.tenant_id == tenant_id,
            ChartSituation.chart_id == chart_id,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise ChartSituationError(404, "chart_situation not found", chart_id=chart_id)
        setattr(row, field, None)
        row.updated_at = datetime.now(UTC)
        row.updated_by_user_id = user_id
        row.version = (row.version or 1) + 1
        await session.flush()
        return _serialize(row)


# ---------- eSituation.10 Other Associated Symptoms ----------


@dataclass
class ChartSituationOtherSymptomPayload:
    """Caller-side payload for adding one Other Associated Symptom row."""

    symptom_code: str
    sequence_index: int = 0


def _serialize_symptom(row: ChartSituationOtherSymptom) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "chart_id": row.chart_id,
        "symptom_code": row.symptom_code,
        "sequence_index": row.sequence_index,
        "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
    }


class ChartSituationOtherSymptomService:
    """Tenant-scoped persistence for eSituation.10 repeating group."""

    @staticmethod
    async def list_for_chart(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        if not tenant_id:
            raise ChartSituationError(400, "tenant_id is required")
        if not chart_id:
            raise ChartSituationError(400, "chart_id is required")

        stmt = select(ChartSituationOtherSymptom).where(
            ChartSituationOtherSymptom.tenant_id == tenant_id,
            ChartSituationOtherSymptom.chart_id == chart_id,
        )
        if not include_deleted:
            stmt = stmt.where(ChartSituationOtherSymptom.deleted_at.is_(None))
        stmt = stmt.order_by(
            ChartSituationOtherSymptom.sequence_index,
            ChartSituationOtherSymptom.symptom_code,
        )
        rows = (await session.execute(stmt)).scalars().all()
        return [_serialize_symptom(r) for r in rows]

    @staticmethod
    async def add(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        payload: ChartSituationOtherSymptomPayload,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if not tenant_id:
            raise ChartSituationError(400, "tenant_id is required")
        if not chart_id:
            raise ChartSituationError(400, "chart_id is required")
        if not payload.symptom_code:
            raise ChartSituationError(400, "symptom_code is required")
        if payload.sequence_index is None or payload.sequence_index < 0:
            raise ChartSituationError(400, "sequence_index must be >= 0")

        now = datetime.now(UTC)

        # Reject duplicates; reuse soft-deleted row if present.
        stmt = select(ChartSituationOtherSymptom).where(
            ChartSituationOtherSymptom.tenant_id == tenant_id,
            ChartSituationOtherSymptom.chart_id == chart_id,
            ChartSituationOtherSymptom.symptom_code == payload.symptom_code,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is not None and existing.deleted_at is None:
            raise ChartSituationError(
                409,
                "symptom already recorded for chart",
                symptom_code=payload.symptom_code,
            )
        if existing is not None and existing.deleted_at is not None:
            existing.sequence_index = payload.sequence_index
            existing.updated_by_user_id = user_id
            existing.updated_at = now
            existing.deleted_at = None
            existing.version = (existing.version or 1) + 1
            row = existing
        else:
            row = ChartSituationOtherSymptom(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                chart_id=chart_id,
                symptom_code=payload.symptom_code,
                sequence_index=payload.sequence_index,
                created_by_user_id=user_id,
                updated_by_user_id=user_id,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            session.add(row)

        await session.flush()
        return _serialize_symptom(row)

    @staticmethod
    async def soft_delete(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        row_id: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if not tenant_id:
            raise ChartSituationError(400, "tenant_id is required")
        if not chart_id:
            raise ChartSituationError(400, "chart_id is required")
        if not row_id:
            raise ChartSituationError(400, "row_id is required")

        stmt = select(ChartSituationOtherSymptom).where(
            ChartSituationOtherSymptom.tenant_id == tenant_id,
            ChartSituationOtherSymptom.chart_id == chart_id,
            ChartSituationOtherSymptom.id == row_id,
            ChartSituationOtherSymptom.deleted_at.is_(None),
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise ChartSituationError(
                404, "chart_situation_other_symptom not found", row_id=row_id
            )

        now = datetime.now(UTC)
        row.deleted_at = now
        row.updated_at = now
        row.updated_by_user_id = user_id
        row.version = (row.version or 1) + 1
        await session.flush()
        return _serialize_symptom(row)


# ---------- eSituation.12 Provider's Secondary Impressions ----------


@dataclass
class ChartSituationSecondaryImpressionPayload:
    """Caller-side payload for adding one Secondary Impression row."""

    impression_code: str
    sequence_index: int = 0


def _serialize_impression(row: ChartSituationSecondaryImpression) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "chart_id": row.chart_id,
        "impression_code": row.impression_code,
        "sequence_index": row.sequence_index,
        "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
    }


class ChartSituationSecondaryImpressionService:
    """Tenant-scoped persistence for eSituation.12 repeating group."""

    @staticmethod
    async def list_for_chart(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        if not tenant_id:
            raise ChartSituationError(400, "tenant_id is required")
        if not chart_id:
            raise ChartSituationError(400, "chart_id is required")

        stmt = select(ChartSituationSecondaryImpression).where(
            ChartSituationSecondaryImpression.tenant_id == tenant_id,
            ChartSituationSecondaryImpression.chart_id == chart_id,
        )
        if not include_deleted:
            stmt = stmt.where(ChartSituationSecondaryImpression.deleted_at.is_(None))
        stmt = stmt.order_by(
            ChartSituationSecondaryImpression.sequence_index,
            ChartSituationSecondaryImpression.impression_code,
        )
        rows = (await session.execute(stmt)).scalars().all()
        return [_serialize_impression(r) for r in rows]

    @staticmethod
    async def add(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        payload: ChartSituationSecondaryImpressionPayload,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if not tenant_id:
            raise ChartSituationError(400, "tenant_id is required")
        if not chart_id:
            raise ChartSituationError(400, "chart_id is required")
        if not payload.impression_code:
            raise ChartSituationError(400, "impression_code is required")
        if payload.sequence_index is None or payload.sequence_index < 0:
            raise ChartSituationError(400, "sequence_index must be >= 0")

        now = datetime.now(UTC)

        # Reject duplicates; reuse soft-deleted row if present.
        stmt = select(ChartSituationSecondaryImpression).where(
            ChartSituationSecondaryImpression.tenant_id == tenant_id,
            ChartSituationSecondaryImpression.chart_id == chart_id,
            ChartSituationSecondaryImpression.impression_code == payload.impression_code,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is not None and existing.deleted_at is None:
            raise ChartSituationError(
                409,
                "impression already recorded for chart",
                impression_code=payload.impression_code,
            )
        if existing is not None and existing.deleted_at is not None:
            existing.sequence_index = payload.sequence_index
            existing.updated_by_user_id = user_id
            existing.updated_at = now
            existing.deleted_at = None
            existing.version = (existing.version or 1) + 1
            row = existing
        else:
            row = ChartSituationSecondaryImpression(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                chart_id=chart_id,
                impression_code=payload.impression_code,
                sequence_index=payload.sequence_index,
                created_by_user_id=user_id,
                updated_by_user_id=user_id,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            session.add(row)

        await session.flush()
        return _serialize_impression(row)

    @staticmethod
    async def soft_delete(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        row_id: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if not tenant_id:
            raise ChartSituationError(400, "tenant_id is required")
        if not chart_id:
            raise ChartSituationError(400, "chart_id is required")
        if not row_id:
            raise ChartSituationError(400, "row_id is required")

        stmt = select(ChartSituationSecondaryImpression).where(
            ChartSituationSecondaryImpression.tenant_id == tenant_id,
            ChartSituationSecondaryImpression.chart_id == chart_id,
            ChartSituationSecondaryImpression.id == row_id,
            ChartSituationSecondaryImpression.deleted_at.is_(None),
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise ChartSituationError(
                404,
                "chart_situation_secondary_impression not found",
                row_id=row_id,
            )

        now = datetime.now(UTC)
        row.deleted_at = now
        row.updated_at = now
        row.updated_by_user_id = user_id
        row.version = (row.version or 1) + 1
        await session.flush()
        return _serialize_impression(row)


__all__ = [
    "ChartSituationService",
    "ChartSituationPayload",
    "ChartSituationError",
    "ChartSituationOtherSymptomService",
    "ChartSituationOtherSymptomPayload",
    "ChartSituationSecondaryImpressionService",
    "ChartSituationSecondaryImpressionPayload",
    "_SITUATION_FIELDS",
]
