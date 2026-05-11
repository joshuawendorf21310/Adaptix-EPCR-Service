"""NEMSIS eCrew service: tenant-scoped CRUD for chart crew members.

Every read and write is filtered by ``tenant_id`` at the SQL layer so no
cross-tenant escape is possible. The service is intentionally thin: it
persists raw crew member rows; conversion to NEMSIS XML is the
projection layer's job (:mod:`projection_chart_crew`).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models_chart_crew import ChartCrewMember


_CREW_FIELDS: tuple[str, ...] = (
    "crew_member_id",
    "crew_member_level_code",
    "crew_member_response_role_code",
    "sequence_index",
)


class ChartCrewError(Exception):
    """Raised on caller errors that are safe to surface to the API layer."""

    def __init__(self, status_code: int, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = {"message": message, **extra}


@dataclass
class ChartCrewPayload:
    """Caller-side payload for creating one crew row.

    All three NEMSIS-bound fields are required because eCrew.01/02 are
    Mandatory and eCrew.03 is Required-at-National. ``sequence_index``
    preserves crew ordering on export.
    """

    crew_member_id: str
    crew_member_level_code: str
    crew_member_response_role_code: str
    sequence_index: int = 0


@dataclass
class ChartCrewUpdate:
    """Caller-side payload for partial-updating one crew row.

    None means "no change". To swap a member's level or role on the
    same chart, PATCH the row; to replace the underlying person, soft
    delete and add a new row.
    """

    crew_member_level_code: str | None = None
    crew_member_response_role_code: str | None = None
    sequence_index: int | None = None


def _serialize(row: ChartCrewMember) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "chart_id": row.chart_id,
        "crew_member_id": row.crew_member_id,
        "crew_member_level_code": row.crew_member_level_code,
        "crew_member_response_role_code": row.crew_member_response_role_code,
        "sequence_index": row.sequence_index,
        "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
    }


class ChartCrewService:
    """Tenant-scoped persistence for chart crew members."""

    @staticmethod
    async def list_for_chart(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        if not tenant_id:
            raise ChartCrewError(400, "tenant_id is required")
        if not chart_id:
            raise ChartCrewError(400, "chart_id is required")

        stmt = select(ChartCrewMember).where(
            ChartCrewMember.tenant_id == tenant_id,
            ChartCrewMember.chart_id == chart_id,
        )
        if not include_deleted:
            stmt = stmt.where(ChartCrewMember.deleted_at.is_(None))
        stmt = stmt.order_by(
            ChartCrewMember.sequence_index,
            ChartCrewMember.crew_member_id,
        )
        rows = (await session.execute(stmt)).scalars().all()
        return [_serialize(r) for r in rows]

    @staticmethod
    async def get(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        row_id: str,
    ) -> dict[str, Any] | None:
        if not tenant_id:
            raise ChartCrewError(400, "tenant_id is required")
        if not chart_id:
            raise ChartCrewError(400, "chart_id is required")
        if not row_id:
            raise ChartCrewError(400, "row_id is required")

        stmt = select(ChartCrewMember).where(
            ChartCrewMember.tenant_id == tenant_id,
            ChartCrewMember.chart_id == chart_id,
            ChartCrewMember.id == row_id,
            ChartCrewMember.deleted_at.is_(None),
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        return _serialize(row) if row else None

    @staticmethod
    async def add(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        payload: ChartCrewPayload,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if not tenant_id:
            raise ChartCrewError(400, "tenant_id is required")
        if not chart_id:
            raise ChartCrewError(400, "chart_id is required")
        if not payload.crew_member_id:
            raise ChartCrewError(400, "crew_member_id is required")
        if not payload.crew_member_level_code:
            raise ChartCrewError(400, "crew_member_level_code is required")
        if not payload.crew_member_response_role_code:
            raise ChartCrewError(400, "crew_member_response_role_code is required")
        if payload.sequence_index is None or payload.sequence_index < 0:
            raise ChartCrewError(400, "sequence_index must be >= 0")

        now = datetime.now(UTC)

        # Reject duplicates (same person twice on same chart). Reuse the
        # row if it was previously soft-deleted, otherwise reject.
        stmt = select(ChartCrewMember).where(
            ChartCrewMember.tenant_id == tenant_id,
            ChartCrewMember.chart_id == chart_id,
            ChartCrewMember.crew_member_id == payload.crew_member_id,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is not None and existing.deleted_at is None:
            raise ChartCrewError(
                409,
                "crew member already on chart",
                crew_member_id=payload.crew_member_id,
            )
        if existing is not None and existing.deleted_at is not None:
            existing.crew_member_level_code = payload.crew_member_level_code
            existing.crew_member_response_role_code = (
                payload.crew_member_response_role_code
            )
            existing.sequence_index = payload.sequence_index
            existing.updated_by_user_id = user_id
            existing.updated_at = now
            existing.deleted_at = None
            existing.version = (existing.version or 1) + 1
            row = existing
        else:
            row = ChartCrewMember(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                chart_id=chart_id,
                crew_member_id=payload.crew_member_id,
                crew_member_level_code=payload.crew_member_level_code,
                crew_member_response_role_code=payload.crew_member_response_role_code,
                sequence_index=payload.sequence_index,
                created_by_user_id=user_id,
                updated_by_user_id=user_id,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            session.add(row)

        await session.flush()
        return _serialize(row)

    @staticmethod
    async def update(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        row_id: str,
        payload: ChartCrewUpdate,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if not tenant_id:
            raise ChartCrewError(400, "tenant_id is required")
        if not chart_id:
            raise ChartCrewError(400, "chart_id is required")
        if not row_id:
            raise ChartCrewError(400, "row_id is required")

        stmt = select(ChartCrewMember).where(
            ChartCrewMember.tenant_id == tenant_id,
            ChartCrewMember.chart_id == chart_id,
            ChartCrewMember.id == row_id,
            ChartCrewMember.deleted_at.is_(None),
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise ChartCrewError(404, "chart_crew_member not found", row_id=row_id)

        if payload.crew_member_level_code is not None:
            if not payload.crew_member_level_code:
                raise ChartCrewError(400, "crew_member_level_code cannot be blank")
            row.crew_member_level_code = payload.crew_member_level_code
        if payload.crew_member_response_role_code is not None:
            if not payload.crew_member_response_role_code:
                raise ChartCrewError(
                    400, "crew_member_response_role_code cannot be blank"
                )
            row.crew_member_response_role_code = payload.crew_member_response_role_code
        if payload.sequence_index is not None:
            if payload.sequence_index < 0:
                raise ChartCrewError(400, "sequence_index must be >= 0")
            row.sequence_index = payload.sequence_index

        row.updated_by_user_id = user_id
        row.updated_at = datetime.now(UTC)
        row.version = (row.version or 1) + 1
        await session.flush()
        return _serialize(row)

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
            raise ChartCrewError(400, "tenant_id is required")
        if not chart_id:
            raise ChartCrewError(400, "chart_id is required")
        if not row_id:
            raise ChartCrewError(400, "row_id is required")

        stmt = select(ChartCrewMember).where(
            ChartCrewMember.tenant_id == tenant_id,
            ChartCrewMember.chart_id == chart_id,
            ChartCrewMember.id == row_id,
            ChartCrewMember.deleted_at.is_(None),
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise ChartCrewError(404, "chart_crew_member not found", row_id=row_id)

        now = datetime.now(UTC)
        row.deleted_at = now
        row.updated_at = now
        row.updated_by_user_id = user_id
        row.version = (row.version or 1) + 1
        await session.flush()
        return _serialize(row)


__all__ = [
    "ChartCrewService",
    "ChartCrewPayload",
    "ChartCrewUpdate",
    "ChartCrewError",
    "_CREW_FIELDS",
]
