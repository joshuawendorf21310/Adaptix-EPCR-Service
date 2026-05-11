"""NEMSIS field-value persistence service.

Row-per-occurrence persistence for NEMSIS chart fields. Preserves
repeating-group truth, tenant isolation, NV/PN/xsi:nil sidecars, and
validation issue trail. All reads and writes are tenant-scoped at the
SQL layer; no cross-tenant escape is possible through this service.

This module is the canonical write path for the granular, queryable
field ledger described in the directive's Phase 2. It coexists with the
dict-aggregating ``nemsis_chart_finalization_gate`` path; nothing here
displaces or weakens that gate.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Iterable

from sqlalchemy import delete as sa_delete, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models_nemsis_field_values import NemsisFieldValue


VALID_SOURCES = {"manual", "import", "scenario", "ai_assist", "device"}
VALID_STATUSES = {"unvalidated", "valid", "warning", "error"}


@dataclass
class FieldValuePayload:
    """Caller-side payload for upserting a single occurrence."""

    section: str
    element_number: str
    element_name: str
    value: Any = None
    group_path: str = ""
    occurrence_id: str = ""
    sequence_index: int = 0
    attributes: dict[str, Any] = field(default_factory=dict)
    source: str = "manual"
    validation_status: str = "unvalidated"
    validation_issues: list[dict[str, Any]] = field(default_factory=list)
    user_id: str | None = None


class NemsisFieldValueError(Exception):
    """Raised on caller errors that are safe to surface to the API layer."""

    def __init__(self, status_code: int, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = {"message": message, **extra}


def _validate(payload: FieldValuePayload) -> None:
    if not payload.section:
        raise NemsisFieldValueError(400, "section is required")
    if not payload.element_number:
        raise NemsisFieldValueError(400, "element_number is required")
    if not payload.element_name:
        raise NemsisFieldValueError(400, "element_name is required")
    if payload.source not in VALID_SOURCES:
        raise NemsisFieldValueError(
            400,
            "invalid source",
            allowed=sorted(VALID_SOURCES),
            received=payload.source,
        )
    if payload.validation_status not in VALID_STATUSES:
        raise NemsisFieldValueError(
            400,
            "invalid validation_status",
            allowed=sorted(VALID_STATUSES),
            received=payload.validation_status,
        )
    if payload.sequence_index < 0:
        raise NemsisFieldValueError(400, "sequence_index must be >= 0")


def _serialize(row: NemsisFieldValue) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "chart_id": row.chart_id,
        "section": row.section,
        "element_number": row.element_number,
        "element_name": row.element_name,
        "group_path": row.group_path or "",
        "occurrence_id": row.occurrence_id or "",
        "sequence_index": row.sequence_index,
        "value": row.value_json,
        "attributes": row.attributes_json or {},
        "source": row.source,
        "validation_status": row.validation_status,
        "validation_issues": row.validation_issues_json or [],
        "created_by_user_id": row.created_by_user_id,
        "updated_by_user_id": row.updated_by_user_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
    }


class NemsisFieldValueService:
    """Tenant-scoped persistence for NEMSIS field occurrences."""

    @staticmethod
    async def upsert(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        payload: FieldValuePayload,
    ) -> dict[str, Any]:
        _validate(payload)
        if not tenant_id:
            raise NemsisFieldValueError(400, "tenant_id is required")
        if not chart_id:
            raise NemsisFieldValueError(400, "chart_id is required")

        now = datetime.now(UTC)

        stmt = select(NemsisFieldValue).where(
            NemsisFieldValue.tenant_id == tenant_id,
            NemsisFieldValue.chart_id == chart_id,
            NemsisFieldValue.element_number == payload.element_number,
            NemsisFieldValue.group_path == (payload.group_path or ""),
            NemsisFieldValue.occurrence_id == (payload.occurrence_id or ""),
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()

        if existing is None:
            row = NemsisFieldValue(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                chart_id=chart_id,
                section=payload.section,
                element_number=payload.element_number,
                element_name=payload.element_name,
                group_path=payload.group_path or "",
                occurrence_id=payload.occurrence_id or "",
                sequence_index=payload.sequence_index,
                value_json=payload.value,
                attributes_json=payload.attributes or {},
                source=payload.source,
                validation_status=payload.validation_status,
                validation_issues_json=payload.validation_issues or [],
                created_by_user_id=payload.user_id,
                updated_by_user_id=payload.user_id,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            session.add(row)
        else:
            existing.section = payload.section
            existing.element_name = payload.element_name
            existing.sequence_index = payload.sequence_index
            existing.value_json = payload.value
            existing.attributes_json = payload.attributes or {}
            existing.source = payload.source
            existing.validation_status = payload.validation_status
            existing.validation_issues_json = payload.validation_issues or []
            existing.updated_by_user_id = payload.user_id
            existing.updated_at = now
            existing.deleted_at = None
            row = existing

        await session.flush()
        return _serialize(row)

    @staticmethod
    async def bulk_save(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        payloads: Iterable[FieldValuePayload],
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for p in payloads:
            results.append(
                await NemsisFieldValueService.upsert(
                    session, tenant_id=tenant_id, chart_id=chart_id, payload=p
                )
            )
        return results

    @staticmethod
    async def list_for_chart(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        section: str | None = None,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        if not tenant_id:
            raise NemsisFieldValueError(400, "tenant_id is required")
        if not chart_id:
            raise NemsisFieldValueError(400, "chart_id is required")

        stmt = select(NemsisFieldValue).where(
            NemsisFieldValue.tenant_id == tenant_id,
            NemsisFieldValue.chart_id == chart_id,
        )
        if section is not None:
            stmt = stmt.where(NemsisFieldValue.section == section)
        if not include_deleted:
            stmt = stmt.where(NemsisFieldValue.deleted_at.is_(None))
        stmt = stmt.order_by(
            NemsisFieldValue.section,
            NemsisFieldValue.element_number,
            NemsisFieldValue.group_path,
            NemsisFieldValue.sequence_index,
            NemsisFieldValue.occurrence_id,
        )

        rows = (await session.execute(stmt)).scalars().all()
        return [_serialize(r) for r in rows]

    @staticmethod
    async def soft_delete(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        row_id: str,
        user_id: str | None = None,
    ) -> bool:
        if not tenant_id:
            raise NemsisFieldValueError(400, "tenant_id is required")
        if not chart_id:
            raise NemsisFieldValueError(400, "chart_id is required")
        if not row_id:
            raise NemsisFieldValueError(400, "id is required")

        now = datetime.now(UTC)
        stmt = (
            sa_update(NemsisFieldValue)
            .where(
                NemsisFieldValue.tenant_id == tenant_id,
                NemsisFieldValue.chart_id == chart_id,
                NemsisFieldValue.id == row_id,
                NemsisFieldValue.deleted_at.is_(None),
            )
            .values(deleted_at=now, updated_at=now, updated_by_user_id=user_id)
        )
        result = await session.execute(stmt)
        await session.flush()
        return (result.rowcount or 0) > 0

    @staticmethod
    async def hard_delete_for_chart(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
    ) -> int:
        """Test/admin helper. Tenant-scoped destructive purge."""
        if not tenant_id or not chart_id:
            raise NemsisFieldValueError(400, "tenant_id and chart_id required")
        stmt = sa_delete(NemsisFieldValue).where(
            NemsisFieldValue.tenant_id == tenant_id,
            NemsisFieldValue.chart_id == chart_id,
        )
        result = await session.execute(stmt)
        await session.flush()
        return result.rowcount or 0
