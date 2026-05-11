"""NEMSIS eMedications-additions service.

Tenant-scoped upsert/read for the 1:1 ``MedicationAdminExt`` row and
the 1:M ``MedicationComplication`` repeating-group rows that extend
each ``MedicationAdministration``. Every read and write is filtered by
``tenant_id`` at the SQL layer so no cross-tenant escape is possible.

This service is intentionally thin: it persists raw NEMSIS-additive
scalars and complication codes; conversion to the NEMSIS field-value
ledger is the projection layer's job
(:mod:`projection_medication_admin_ext`).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete as sa_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models_medication_admin_ext import (
    MedicationAdminExt,
    MedicationComplication,
)


# Per-medication-row NEMSIS-additive scalar columns.
_EXT_FIELDS: tuple[str, ...] = (
    "prior_to_ems_indicator_code",
    "ems_professional_type_code",
    "authorization_code",
    "authorizing_physician_last_name",
    "authorizing_physician_first_name",
    "by_another_unit_indicator_code",
)


class MedicationAdminExtError(Exception):
    """Raised on caller errors that are safe to surface to the API layer."""

    def __init__(self, status_code: int, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = {"message": message, **extra}


@dataclass
class MedicationAdminExtPayload:
    """Caller-side payload for upsert.

    All fields are optional. Any field omitted (``None``) retains its
    current persisted value to support partial PATCH-style updates.
    """

    prior_to_ems_indicator_code: str | None = None
    ems_professional_type_code: str | None = None
    authorization_code: str | None = None
    authorizing_physician_last_name: str | None = None
    authorizing_physician_first_name: str | None = None
    by_another_unit_indicator_code: str | None = None


@dataclass
class MedicationComplicationPayload:
    """Caller-side payload for adding one complication row."""

    complication_code: str
    sequence_index: int = 0


def _serialize_ext(row: MedicationAdminExt) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "chart_id": row.chart_id,
        "medication_admin_id": row.medication_admin_id,
        **{field: getattr(row, field) for field in _EXT_FIELDS},
        "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
    }


def _serialize_complication(row: MedicationComplication) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "chart_id": row.chart_id,
        "medication_admin_id": row.medication_admin_id,
        "complication_code": row.complication_code,
        "sequence_index": row.sequence_index,
        "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
    }


class MedicationAdminExtService:
    """Tenant-scoped persistence for eMedications additions."""

    @staticmethod
    async def get(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        medication_admin_id: str,
    ) -> dict[str, Any] | None:
        if not tenant_id:
            raise MedicationAdminExtError(400, "tenant_id is required")
        if not chart_id:
            raise MedicationAdminExtError(400, "chart_id is required")
        if not medication_admin_id:
            raise MedicationAdminExtError(400, "medication_admin_id is required")

        ext_stmt = select(MedicationAdminExt).where(
            MedicationAdminExt.tenant_id == tenant_id,
            MedicationAdminExt.chart_id == chart_id,
            MedicationAdminExt.medication_admin_id == medication_admin_id,
            MedicationAdminExt.deleted_at.is_(None),
        )
        ext = (await session.execute(ext_stmt)).scalar_one_or_none()

        comp_stmt = (
            select(MedicationComplication)
            .where(
                MedicationComplication.tenant_id == tenant_id,
                MedicationComplication.chart_id == chart_id,
                MedicationComplication.medication_admin_id == medication_admin_id,
                MedicationComplication.deleted_at.is_(None),
            )
            .order_by(
                MedicationComplication.sequence_index,
                MedicationComplication.created_at,
            )
        )
        comps = (await session.execute(comp_stmt)).scalars().all()

        if ext is None and not comps:
            return None

        return {
            "ext": _serialize_ext(ext) if ext else None,
            "complications": [_serialize_complication(c) for c in comps],
        }

    @staticmethod
    async def upsert(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        medication_admin_id: str,
        payload: MedicationAdminExtPayload,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if not tenant_id:
            raise MedicationAdminExtError(400, "tenant_id is required")
        if not chart_id:
            raise MedicationAdminExtError(400, "chart_id is required")
        if not medication_admin_id:
            raise MedicationAdminExtError(400, "medication_admin_id is required")

        now = datetime.now(UTC)

        stmt = select(MedicationAdminExt).where(
            MedicationAdminExt.tenant_id == tenant_id,
            MedicationAdminExt.medication_admin_id == medication_admin_id,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()

        if row is None:
            row = MedicationAdminExt(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                chart_id=chart_id,
                medication_admin_id=medication_admin_id,
                created_by_user_id=user_id,
                updated_by_user_id=user_id,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            for field in _EXT_FIELDS:
                setattr(row, field, getattr(payload, field))
            session.add(row)
        else:
            for field in _EXT_FIELDS:
                value = getattr(payload, field)
                # Only overwrite when the caller actually supplied a
                # value. ``None`` retains the existing value so partial
                # updates work; explicit clearing is a separate path.
                if value is not None:
                    setattr(row, field, value)
            row.updated_by_user_id = user_id
            row.updated_at = now
            row.deleted_at = None
            row.version = (row.version or 1) + 1

        await session.flush()
        return _serialize_ext(row)

    @staticmethod
    async def add_complication(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        medication_admin_id: str,
        payload: MedicationComplicationPayload,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if not tenant_id:
            raise MedicationAdminExtError(400, "tenant_id is required")
        if not chart_id:
            raise MedicationAdminExtError(400, "chart_id is required")
        if not medication_admin_id:
            raise MedicationAdminExtError(400, "medication_admin_id is required")
        if not payload.complication_code:
            raise MedicationAdminExtError(400, "complication_code is required")
        if payload.sequence_index < 0:
            raise MedicationAdminExtError(400, "sequence_index must be >= 0")

        existing_stmt = select(MedicationComplication).where(
            MedicationComplication.tenant_id == tenant_id,
            MedicationComplication.medication_admin_id == medication_admin_id,
            MedicationComplication.complication_code == payload.complication_code,
        )
        existing = (await session.execute(existing_stmt)).scalar_one_or_none()
        now = datetime.now(UTC)

        if existing is not None:
            # Idempotent: update sequence_index and clear soft-delete.
            existing.sequence_index = payload.sequence_index
            existing.updated_by_user_id = user_id
            existing.updated_at = now
            existing.deleted_at = None
            existing.version = (existing.version or 1) + 1
            row = existing
        else:
            row = MedicationComplication(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                chart_id=chart_id,
                medication_admin_id=medication_admin_id,
                complication_code=payload.complication_code,
                sequence_index=payload.sequence_index,
                created_by_user_id=user_id,
                updated_by_user_id=user_id,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            session.add(row)

        await session.flush()
        return _serialize_complication(row)

    @staticmethod
    async def delete_complication(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        medication_admin_id: str,
        complication_id: str,
        user_id: str | None = None,
    ) -> bool:
        if not tenant_id:
            raise MedicationAdminExtError(400, "tenant_id is required")
        if not complication_id:
            raise MedicationAdminExtError(400, "complication_id is required")

        stmt = sa_delete(MedicationComplication).where(
            MedicationComplication.tenant_id == tenant_id,
            MedicationComplication.chart_id == chart_id,
            MedicationComplication.medication_admin_id == medication_admin_id,
            MedicationComplication.id == complication_id,
        )
        result = await session.execute(stmt)
        await session.flush()
        return (result.rowcount or 0) > 0


__all__ = [
    "MedicationAdminExtService",
    "MedicationAdminExtPayload",
    "MedicationComplicationPayload",
    "MedicationAdminExtError",
    "_EXT_FIELDS",
]
