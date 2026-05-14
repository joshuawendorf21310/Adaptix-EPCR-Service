"""NEMSIS eVitals extension service: tenant-scoped CRUD.

Persists the 1:1 extension scalars and the two 1:M child collections
(GCS qualifiers, reperfusion checklist) for a single :class:`Vitals`
row. Every read and write is filtered by ``tenant_id`` at the SQL
layer so no cross-tenant escape is possible.

The service is intentionally thin: it persists raw codes and integers;
conversion to NEMSIS XML is the projection layer's job
(:mod:`projection_vitals_ext`).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete as sa_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models_vitals_ext import (
    VitalsGcsQualifier,
    VitalsNemsisExt,
    VitalsReperfusionChecklist,
)


# Scalar (non-list, non-child) fields persisted on VitalsNemsisExt.
_EXT_SCALAR_FIELDS: tuple[str, ...] = (
    "obtained_prior_to_ems_code",
    "ecg_type_code",
    "blood_pressure_method_code",
    "mean_arterial_pressure",
    "heart_rate_method_code",
    "pulse_rhythm_code",
    "respiratory_effort_code",
    "etco2",
    "carbon_monoxide_ppm",
    "gcs_eye_code",
    "gcs_verbal_code",
    "gcs_motor_code",
    "gcs_total",
    "temperature_method_code",
    "avpu_code",
    "pain_score",
    "pain_scale_type_code",
    "stroke_scale_result_code",
    "stroke_scale_type_code",
    "stroke_scale_score",
    "apgar_score",
    "revised_trauma_score",
)

# JSON list fields (1:M code lists held inline on the extension row).
_EXT_LIST_FIELDS: tuple[str, ...] = (
    "cardiac_rhythm_codes_json",
    "ecg_interpretation_method_codes_json",
)

# Convenience set of all column-bound fields the upsert accepts.
_EXT_FIELDS: tuple[str, ...] = _EXT_SCALAR_FIELDS + _EXT_LIST_FIELDS


class VitalsExtError(Exception):
    """Raised on caller errors that are safe to surface to the API layer."""

    def __init__(self, status_code: int, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = {"message": message, **extra}


@dataclass
class VitalsExtPayload:
    """Caller-side payload for upserting the extension scalars + lists.

    Every field is optional. Any field omitted (left as ``None``)
    retains its current persisted value on update.
    """

    obtained_prior_to_ems_code: str | None = None
    cardiac_rhythm_codes_json: list[str] | None = None
    ecg_type_code: str | None = None
    ecg_interpretation_method_codes_json: list[str] | None = None
    blood_pressure_method_code: str | None = None
    mean_arterial_pressure: int | None = None
    heart_rate_method_code: str | None = None
    pulse_rhythm_code: str | None = None
    respiratory_effort_code: str | None = None
    etco2: int | None = None
    carbon_monoxide_ppm: float | None = None
    gcs_eye_code: str | None = None
    gcs_verbal_code: str | None = None
    gcs_motor_code: str | None = None
    gcs_total: int | None = None
    temperature_method_code: str | None = None
    avpu_code: str | None = None
    pain_score: int | None = None
    pain_scale_type_code: str | None = None
    stroke_scale_result_code: str | None = None
    stroke_scale_type_code: str | None = None
    stroke_scale_score: int | None = None
    apgar_score: int | None = None
    revised_trauma_score: int | None = None


def _serialize_ext(row: VitalsNemsisExt) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "chart_id": row.chart_id,
        "vitals_id": row.vitals_id,
        "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
    }
    for field in _EXT_FIELDS:
        out[field] = getattr(row, field)
    return out


def _serialize_gcs(row: VitalsGcsQualifier) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "chart_id": row.chart_id,
        "vitals_id": row.vitals_id,
        "qualifier_code": row.qualifier_code,
        "sequence_index": row.sequence_index,
        "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
    }


def _serialize_rc(row: VitalsReperfusionChecklist) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "chart_id": row.chart_id,
        "vitals_id": row.vitals_id,
        "item_code": row.item_code,
        "sequence_index": row.sequence_index,
        "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
    }


def _require(tenant_id: str, chart_id: str, vitals_id: str) -> None:
    if not tenant_id:
        raise VitalsExtError(400, "tenant_id is required")
    if not chart_id:
        raise VitalsExtError(400, "chart_id is required")
    if not vitals_id:
        raise VitalsExtError(400, "vitals_id is required")


class VitalsExtService:
    """Tenant-scoped persistence for the eVitals extension aggregate."""

    # ----- ext (1:1) -----

    @staticmethod
    async def get(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        vitals_id: str,
    ) -> dict[str, Any] | None:
        _require(tenant_id, chart_id, vitals_id)

        ext_stmt = select(VitalsNemsisExt).where(
            VitalsNemsisExt.tenant_id == tenant_id,
            VitalsNemsisExt.chart_id == chart_id,
            VitalsNemsisExt.vitals_id == vitals_id,
            VitalsNemsisExt.deleted_at.is_(None),
        )
        ext_row = (await session.execute(ext_stmt)).scalar_one_or_none()

        gcs_stmt = (
            select(VitalsGcsQualifier)
            .where(
                VitalsGcsQualifier.tenant_id == tenant_id,
                VitalsGcsQualifier.chart_id == chart_id,
                VitalsGcsQualifier.vitals_id == vitals_id,
                VitalsGcsQualifier.deleted_at.is_(None),
            )
            .order_by(
                VitalsGcsQualifier.sequence_index,
                VitalsGcsQualifier.qualifier_code,
            )
        )
        gcs_rows = (await session.execute(gcs_stmt)).scalars().all()

        rc_stmt = (
            select(VitalsReperfusionChecklist)
            .where(
                VitalsReperfusionChecklist.tenant_id == tenant_id,
                VitalsReperfusionChecklist.chart_id == chart_id,
                VitalsReperfusionChecklist.vitals_id == vitals_id,
                VitalsReperfusionChecklist.deleted_at.is_(None),
            )
            .order_by(
                VitalsReperfusionChecklist.sequence_index,
                VitalsReperfusionChecklist.item_code,
            )
        )
        rc_rows = (await session.execute(rc_stmt)).scalars().all()

        if ext_row is None and not gcs_rows and not rc_rows:
            return None

        return {
            "ext": _serialize_ext(ext_row) if ext_row else None,
            "gcs_qualifiers": [_serialize_gcs(r) for r in gcs_rows],
            "reperfusion_checklist": [_serialize_rc(r) for r in rc_rows],
        }

    @staticmethod
    async def upsert_ext(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        vitals_id: str,
        payload: VitalsExtPayload,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        _require(tenant_id, chart_id, vitals_id)
        now = datetime.now(UTC)

        stmt = select(VitalsNemsisExt).where(
            VitalsNemsisExt.tenant_id == tenant_id,
            VitalsNemsisExt.chart_id == chart_id,
            VitalsNemsisExt.vitals_id == vitals_id,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()

        if row is None:
            row = VitalsNemsisExt(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                chart_id=chart_id,
                vitals_id=vitals_id,
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
                if value is not None:
                    setattr(row, field, value)
            row.updated_by_user_id = user_id
            row.updated_at = now
            row.deleted_at = None
            row.version = (row.version or 1) + 1

        await session.flush()
        return _serialize_ext(row)

    # ----- gcs_qualifiers (1:M) -----

    @staticmethod
    async def add_gcs_qualifier(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        vitals_id: str,
        qualifier_code: str,
        sequence_index: int = 0,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        _require(tenant_id, chart_id, vitals_id)
        if not qualifier_code:
            raise VitalsExtError(400, "qualifier_code is required")
        if sequence_index < 0:
            raise VitalsExtError(400, "sequence_index must be >= 0")
        now = datetime.now(UTC)

        # Upsert on (tenant_id, vitals_id, qualifier_code).
        stmt = select(VitalsGcsQualifier).where(
            VitalsGcsQualifier.tenant_id == tenant_id,
            VitalsGcsQualifier.vitals_id == vitals_id,
            VitalsGcsQualifier.qualifier_code == qualifier_code,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            existing.sequence_index = sequence_index
            existing.updated_by_user_id = user_id
            existing.updated_at = now
            existing.deleted_at = None
            existing.version = (existing.version or 1) + 1
            row = existing
        else:
            row = VitalsGcsQualifier(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                chart_id=chart_id,
                vitals_id=vitals_id,
                qualifier_code=qualifier_code,
                sequence_index=sequence_index,
                created_by_user_id=user_id,
                updated_by_user_id=user_id,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            session.add(row)
        await session.flush()
        return _serialize_gcs(row)

    @staticmethod
    async def delete_gcs_qualifier(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        vitals_id: str,
        row_id: str,
    ) -> bool:
        _require(tenant_id, chart_id, vitals_id)
        if not row_id:
            raise VitalsExtError(400, "id is required")
        stmt = sa_delete(VitalsGcsQualifier).where(
            VitalsGcsQualifier.tenant_id == tenant_id,
            VitalsGcsQualifier.chart_id == chart_id,
            VitalsGcsQualifier.vitals_id == vitals_id,
            VitalsGcsQualifier.id == row_id,
        )
        result = await session.execute(stmt)
        await session.flush()
        return (result.rowcount or 0) > 0

    @staticmethod
    async def list_gcs_qualifiers(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        vitals_id: str,
    ) -> list[dict[str, Any]]:
        _require(tenant_id, chart_id, vitals_id)
        stmt = (
            select(VitalsGcsQualifier)
            .where(
                VitalsGcsQualifier.tenant_id == tenant_id,
                VitalsGcsQualifier.chart_id == chart_id,
                VitalsGcsQualifier.vitals_id == vitals_id,
                VitalsGcsQualifier.deleted_at.is_(None),
            )
            .order_by(
                VitalsGcsQualifier.sequence_index,
                VitalsGcsQualifier.qualifier_code,
            )
        )
        rows = (await session.execute(stmt)).scalars().all()
        return [_serialize_gcs(r) for r in rows]

    # ----- reperfusion_checklist (1:M) -----

    @staticmethod
    async def add_reperfusion_item(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        vitals_id: str,
        item_code: str,
        sequence_index: int = 0,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        _require(tenant_id, chart_id, vitals_id)
        if not item_code:
            raise VitalsExtError(400, "item_code is required")
        if sequence_index < 0:
            raise VitalsExtError(400, "sequence_index must be >= 0")
        now = datetime.now(UTC)

        stmt = select(VitalsReperfusionChecklist).where(
            VitalsReperfusionChecklist.tenant_id == tenant_id,
            VitalsReperfusionChecklist.vitals_id == vitals_id,
            VitalsReperfusionChecklist.item_code == item_code,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            existing.sequence_index = sequence_index
            existing.updated_by_user_id = user_id
            existing.updated_at = now
            existing.deleted_at = None
            existing.version = (existing.version or 1) + 1
            row = existing
        else:
            row = VitalsReperfusionChecklist(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                chart_id=chart_id,
                vitals_id=vitals_id,
                item_code=item_code,
                sequence_index=sequence_index,
                created_by_user_id=user_id,
                updated_by_user_id=user_id,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            session.add(row)
        await session.flush()
        return _serialize_rc(row)

    @staticmethod
    async def delete_reperfusion_item(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        vitals_id: str,
        row_id: str,
    ) -> bool:
        _require(tenant_id, chart_id, vitals_id)
        if not row_id:
            raise VitalsExtError(400, "id is required")
        stmt = sa_delete(VitalsReperfusionChecklist).where(
            VitalsReperfusionChecklist.tenant_id == tenant_id,
            VitalsReperfusionChecklist.chart_id == chart_id,
            VitalsReperfusionChecklist.vitals_id == vitals_id,
            VitalsReperfusionChecklist.id == row_id,
        )
        result = await session.execute(stmt)
        await session.flush()
        return (result.rowcount or 0) > 0

    @staticmethod
    async def list_reperfusion_items(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        vitals_id: str,
    ) -> list[dict[str, Any]]:
        _require(tenant_id, chart_id, vitals_id)
        stmt = (
            select(VitalsReperfusionChecklist)
            .where(
                VitalsReperfusionChecklist.tenant_id == tenant_id,
                VitalsReperfusionChecklist.chart_id == chart_id,
                VitalsReperfusionChecklist.vitals_id == vitals_id,
                VitalsReperfusionChecklist.deleted_at.is_(None),
            )
            .order_by(
                VitalsReperfusionChecklist.sequence_index,
                VitalsReperfusionChecklist.item_code,
            )
        )
        rows = (await session.execute(stmt)).scalars().all()
        return [_serialize_rc(r) for r in rows]


__all__ = [
    "VitalsExtService",
    "VitalsExtPayload",
    "VitalsExtError",
    "_EXT_FIELDS",
    "_EXT_SCALAR_FIELDS",
    "_EXT_LIST_FIELDS",
]
