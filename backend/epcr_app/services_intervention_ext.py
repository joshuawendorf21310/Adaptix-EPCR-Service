"""NEMSIS eProcedures extension service.

Tenant-scoped upsert/read for :class:`InterventionNemsisExt` and CRUD for
the 1:M :class:`InterventionComplication` child. Every read and write is
filtered by ``tenant_id`` at the SQL layer so no cross-tenant escape is
possible. The service is intentionally thin: persistence only. NEMSIS
ledger projection is the projector's job
(:mod:`projection_intervention_ext`).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models_intervention_ext import (
    InterventionComplication,
    InterventionNemsisExt,
)


_EXT_SCALAR_FIELDS: tuple[str, ...] = (
    "prior_to_ems_indicator_code",
    "number_of_attempts",
    "procedure_successful_code",
    "ems_professional_type_code",
    "authorization_code",
    "authorizing_physician_last_name",
    "authorizing_physician_first_name",
    "by_another_unit_indicator_code",
    "pre_existing_indicator_code",
)


class InterventionExtError(Exception):
    """Raised on caller errors that are safe to surface to the API layer."""

    def __init__(self, status_code: int, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = {"message": message, **extra}


@dataclass
class InterventionExtPayload:
    """Caller-side payload for ext upsert.

    All fields are optional. Any field omitted retains its current
    persisted value; partial updates work field-by-field. Explicit
    clearing is a separate endpoint to avoid ambiguity between "no
    change" and "clear".
    """

    prior_to_ems_indicator_code: str | None = None
    number_of_attempts: int | None = None
    procedure_successful_code: str | None = None
    ems_professional_type_code: str | None = None
    authorization_code: str | None = None
    authorizing_physician_last_name: str | None = None
    authorizing_physician_first_name: str | None = None
    by_another_unit_indicator_code: str | None = None
    pre_existing_indicator_code: str | None = None


def _serialize_ext(row: InterventionNemsisExt) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "chart_id": row.chart_id,
        "intervention_id": row.intervention_id,
        **{field: getattr(row, field) for field in _EXT_SCALAR_FIELDS},
        "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
    }


def _serialize_complication(row: InterventionComplication) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "chart_id": row.chart_id,
        "intervention_id": row.intervention_id,
        "complication_code": row.complication_code,
        "sequence_index": row.sequence_index,
        "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
    }


class InterventionExtService:
    """Tenant-scoped persistence for intervention NEMSIS extension."""

    @staticmethod
    async def get(
        session: AsyncSession,
        *,
        tenant_id: str,
        intervention_id: str,
    ) -> dict[str, Any] | None:
        if not tenant_id:
            raise InterventionExtError(400, "tenant_id is required")
        if not intervention_id:
            raise InterventionExtError(400, "intervention_id is required")

        stmt = select(InterventionNemsisExt).where(
            InterventionNemsisExt.tenant_id == tenant_id,
            InterventionNemsisExt.intervention_id == intervention_id,
            InterventionNemsisExt.deleted_at.is_(None),
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        return _serialize_ext(row) if row else None

    @staticmethod
    async def list_complications(
        session: AsyncSession,
        *,
        tenant_id: str,
        intervention_id: str,
    ) -> list[dict[str, Any]]:
        if not tenant_id:
            raise InterventionExtError(400, "tenant_id is required")
        if not intervention_id:
            raise InterventionExtError(400, "intervention_id is required")

        stmt = (
            select(InterventionComplication)
            .where(
                InterventionComplication.tenant_id == tenant_id,
                InterventionComplication.intervention_id == intervention_id,
                InterventionComplication.deleted_at.is_(None),
            )
            .order_by(
                InterventionComplication.sequence_index,
                InterventionComplication.created_at,
            )
        )
        rows = (await session.execute(stmt)).scalars().all()
        return [_serialize_complication(r) for r in rows]

    @staticmethod
    async def upsert(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        intervention_id: str,
        payload: InterventionExtPayload,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if not tenant_id:
            raise InterventionExtError(400, "tenant_id is required")
        if not chart_id:
            raise InterventionExtError(400, "chart_id is required")
        if not intervention_id:
            raise InterventionExtError(400, "intervention_id is required")

        now = datetime.now(UTC)

        stmt = select(InterventionNemsisExt).where(
            InterventionNemsisExt.tenant_id == tenant_id,
            InterventionNemsisExt.intervention_id == intervention_id,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()

        if row is None:
            row = InterventionNemsisExt(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                chart_id=chart_id,
                intervention_id=intervention_id,
                created_by_user_id=user_id,
                updated_by_user_id=user_id,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            for field in _EXT_SCALAR_FIELDS:
                value = getattr(payload, field)
                setattr(row, field, value)
            session.add(row)
        else:
            for field in _EXT_SCALAR_FIELDS:
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
        return _serialize_ext(row)

    @staticmethod
    async def add_complication(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        intervention_id: str,
        complication_code: str,
        sequence_index: int | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if not tenant_id:
            raise InterventionExtError(400, "tenant_id is required")
        if not chart_id:
            raise InterventionExtError(400, "chart_id is required")
        if not intervention_id:
            raise InterventionExtError(400, "intervention_id is required")
        if not complication_code:
            raise InterventionExtError(400, "complication_code is required")

        # If unique (tenant, intervention, code) already exists, return it
        existing_stmt = select(InterventionComplication).where(
            InterventionComplication.tenant_id == tenant_id,
            InterventionComplication.intervention_id == intervention_id,
            InterventionComplication.complication_code == complication_code,
            InterventionComplication.deleted_at.is_(None),
        )
        existing = (await session.execute(existing_stmt)).scalar_one_or_none()
        if existing is not None:
            return _serialize_complication(existing)

        # Derive sequence_index from current max if not provided.
        if sequence_index is None:
            siblings_stmt = select(InterventionComplication).where(
                InterventionComplication.tenant_id == tenant_id,
                InterventionComplication.intervention_id == intervention_id,
                InterventionComplication.deleted_at.is_(None),
            )
            siblings = (await session.execute(siblings_stmt)).scalars().all()
            sequence_index = (
                max((s.sequence_index for s in siblings), default=-1) + 1
            )

        now = datetime.now(UTC)
        row = InterventionComplication(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            chart_id=chart_id,
            intervention_id=intervention_id,
            complication_code=complication_code,
            sequence_index=sequence_index,
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
    async def remove_complication(
        session: AsyncSession,
        *,
        tenant_id: str,
        intervention_id: str,
        complication_id: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if not tenant_id:
            raise InterventionExtError(400, "tenant_id is required")
        if not intervention_id:
            raise InterventionExtError(400, "intervention_id is required")
        if not complication_id:
            raise InterventionExtError(400, "complication_id is required")

        stmt = select(InterventionComplication).where(
            InterventionComplication.tenant_id == tenant_id,
            InterventionComplication.intervention_id == intervention_id,
            InterventionComplication.id == complication_id,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None or row.deleted_at is not None:
            raise InterventionExtError(
                404,
                "complication not found",
                complication_id=complication_id,
            )
        now = datetime.now(UTC)
        row.deleted_at = now
        row.updated_at = now
        row.updated_by_user_id = user_id
        row.version = (row.version or 1) + 1
        await session.flush()
        return _serialize_complication(row)


__all__ = [
    "InterventionExtService",
    "InterventionExtPayload",
    "InterventionExtError",
    "_EXT_SCALAR_FIELDS",
]
