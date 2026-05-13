"""Provider override / supervisor-confirmation service.

Owns the canonical lifecycle for an
:class:`epcr_app.models.EpcrProviderOverride` row:

- :meth:`record` — persist a new override with mandatory reason text
  (minimum 8 characters); writes an :class:`EpcrAuditLog` row with
  action ``provider_override.recorded``.
- :meth:`request_supervisor` — flag the override as awaiting a named
  supervisor's confirmation; writes
  ``provider_override.supervisor_requested``.
- :meth:`supervisor_confirm` — record the supervisor confirmation
  timestamp; writes ``provider_override.supervisor_confirmed``.
- :meth:`list_for_chart` — return all overrides for a chart in
  chronological order.

The service never calls ``session.commit()``; the caller controls
transaction boundaries.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models import EpcrAuditLog, EpcrProviderOverride

logger = logging.getLogger(__name__)


REASON_MIN_LENGTH = 8

ALLOWED_KINDS = frozenset(
    {
        "validation_warning",
        "lock_blocker",
        "state_required",
        "agency_required",
        "ai_suggestion_rejected",
    }
)


class ProviderOverrideValidationError(ValueError):
    """Raised when override input fails service-level validation."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(f"{field}: {message}")
        self.field = field
        self.message = message


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


class ProviderOverrideService:
    """Static service over :class:`EpcrProviderOverride`."""

    # --------------------------- serialization --------------------------- #

    @staticmethod
    def serialize(row: EpcrProviderOverride) -> dict[str, Any]:
        """Serialize a row to the camelCase contract shared with the frontend."""
        return {
            "id": row.id,
            "tenantId": row.tenant_id,
            "chartId": row.chart_id,
            "section": row.section,
            "fieldKey": row.field_key,
            "kind": row.kind,
            "reasonText": row.reason_text,
            "overrodeAt": _iso(row.overrode_at),
            "overrodeBy": row.overrode_by,
            "supervisorId": row.supervisor_id,
            "supervisorConfirmedAt": _iso(row.supervisor_confirmed_at),
            "createdAt": _iso(row.created_at),
        }

    # --------------------------- read --------------------------- #

    @staticmethod
    async def list_for_chart(
        session: AsyncSession, tenant_id: str, chart_id: str
    ) -> list[dict[str, Any]]:
        """Return all overrides for a chart in chronological order."""
        rows = (
            await session.execute(
                select(EpcrProviderOverride)
                .where(
                    and_(
                        EpcrProviderOverride.chart_id == chart_id,
                        EpcrProviderOverride.tenant_id == tenant_id,
                    )
                )
                .order_by(
                    EpcrProviderOverride.overrode_at,
                    EpcrProviderOverride.id,
                )
            )
        ).scalars().all()
        return [ProviderOverrideService.serialize(r) for r in rows]

    # --------------------------- write --------------------------- #

    @staticmethod
    async def record(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        user_id: str,
        section: str,
        field_key: str,
        kind: str,
        reason_text: str,
    ) -> dict[str, Any]:
        """Persist a new override and an audit row.

        Validates that ``kind`` is one of the canonical values and that
        ``reason_text`` is at least :data:`REASON_MIN_LENGTH` characters
        after stripping whitespace.
        """
        if kind not in ALLOWED_KINDS:
            raise ProviderOverrideValidationError(
                "kind",
                f"must be one of {sorted(ALLOWED_KINDS)!r}",
            )
        if not section or not isinstance(section, str):
            raise ProviderOverrideValidationError(
                "section", "must be a non-empty string"
            )
        if not field_key or not isinstance(field_key, str):
            raise ProviderOverrideValidationError(
                "field_key", "must be a non-empty string"
            )
        if reason_text is None or not isinstance(reason_text, str):
            raise ProviderOverrideValidationError(
                "reason_text", "is required"
            )
        if len(reason_text.strip()) < REASON_MIN_LENGTH:
            raise ProviderOverrideValidationError(
                "reason_text",
                f"must be at least {REASON_MIN_LENGTH} characters",
            )

        now = datetime.now(UTC)
        row = EpcrProviderOverride(
            id=str(uuid4()),
            tenant_id=tenant_id,
            chart_id=chart_id,
            section=section,
            field_key=field_key,
            kind=kind,
            reason_text=reason_text,
            overrode_at=now,
            overrode_by=user_id,
            supervisor_id=None,
            supervisor_confirmed_at=None,
            created_at=now,
        )
        session.add(row)

        ProviderOverrideService._audit(
            session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            user_id=user_id,
            action="provider_override.recorded",
            detail={
                "override_id": row.id,
                "section": section,
                "field_key": field_key,
                "kind": kind,
            },
            performed_at=now,
        )

        await session.flush()
        return ProviderOverrideService.serialize(row)

    @staticmethod
    async def request_supervisor(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        user_id: str,
        override_id: str,
        supervisor_id: str,
    ) -> dict[str, Any]:
        """Flag an override as awaiting confirmation by ``supervisor_id``.

        Sets the pending supervisor without confirming. An audit row
        with action ``provider_override.supervisor_requested`` is
        written.
        """
        if not supervisor_id or not isinstance(supervisor_id, str):
            raise ProviderOverrideValidationError(
                "supervisor_id", "must be a non-empty string"
            )

        row = await ProviderOverrideService._load(
            session, tenant_id, chart_id, override_id
        )
        row.supervisor_id = supervisor_id
        # Supervisor confirmation is explicitly cleared on (re-)request
        row.supervisor_confirmed_at = None

        now = datetime.now(UTC)
        ProviderOverrideService._audit(
            session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            user_id=user_id,
            action="provider_override.supervisor_requested",
            detail={
                "override_id": row.id,
                "supervisor_id": supervisor_id,
            },
            performed_at=now,
        )

        await session.flush()
        return ProviderOverrideService.serialize(row)

    @staticmethod
    async def supervisor_confirm(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        user_id: str,
        override_id: str,
        supervisor_id: str,
    ) -> dict[str, Any]:
        """Record the supervisor confirmation timestamp.

        If a supervisor was previously requested, ``supervisor_id`` must
        match. Otherwise the supervisor is recorded directly. Writes an
        audit row with action ``provider_override.supervisor_confirmed``.
        """
        if not supervisor_id or not isinstance(supervisor_id, str):
            raise ProviderOverrideValidationError(
                "supervisor_id", "must be a non-empty string"
            )

        row = await ProviderOverrideService._load(
            session, tenant_id, chart_id, override_id
        )
        if row.supervisor_id and row.supervisor_id != supervisor_id:
            raise ProviderOverrideValidationError(
                "supervisor_id",
                "does not match the previously requested supervisor",
            )
        now = datetime.now(UTC)
        row.supervisor_id = supervisor_id
        row.supervisor_confirmed_at = now

        ProviderOverrideService._audit(
            session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            user_id=user_id,
            action="provider_override.supervisor_confirmed",
            detail={
                "override_id": row.id,
                "supervisor_id": supervisor_id,
                "confirmed_at": _iso(now),
            },
            performed_at=now,
        )

        await session.flush()
        return ProviderOverrideService.serialize(row)

    # --------------------------- helpers --------------------------- #

    @staticmethod
    async def _load(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        override_id: str,
    ) -> EpcrProviderOverride:
        row = (
            await session.execute(
                select(EpcrProviderOverride).where(
                    and_(
                        EpcrProviderOverride.id == override_id,
                        EpcrProviderOverride.tenant_id == tenant_id,
                        EpcrProviderOverride.chart_id == chart_id,
                    )
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise ProviderOverrideValidationError(
                "override_id", "not found for tenant/chart"
            )
        return row

    @staticmethod
    def _audit(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        user_id: str,
        action: str,
        detail: dict[str, Any],
        performed_at: datetime,
    ) -> None:
        entry = EpcrAuditLog(
            id=str(uuid4()),
            chart_id=chart_id,
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            detail_json=json.dumps(detail, default=str),
            performed_at=performed_at,
        )
        session.add(entry)


__all__ = [
    "ProviderOverrideService",
    "ProviderOverrideValidationError",
    "ALLOWED_KINDS",
    "REASON_MIN_LENGTH",
]
