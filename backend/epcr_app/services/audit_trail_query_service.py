"""Audit-trail query service.

Reads :class:`epcr_app.models.EpcrAuditLog`,
:class:`epcr_app.models.EpcrAiAuditEvent` (the AI-narrative /
sentence-evidence event log), and
:class:`epcr_app.models.EpcrProviderOverride` and merges them into a
single chronological timeline that downstream consumers
(chart-workspace API, compliance export, frontend Audit Trail panel)
can render directly.

The service never mutates any of the underlying tables. The
:class:`EpcrAiAuditEvent` model is treated as optional: an environment
where the AI-evidence pillar is not yet migrated may still call this
service safely; missing-table errors degrade to an empty contribution
from that source so the merged view always returns rows from the
other sources.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models import EpcrAuditLog, EpcrProviderOverride

try:  # pragma: no cover - import guard
    from epcr_app.models import EpcrAiAuditEvent  # type: ignore
except Exception:  # pragma: no cover
    EpcrAiAuditEvent = None  # type: ignore

logger = logging.getLogger(__name__)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _coerce_dt(value: datetime | None) -> datetime:
    """Return a tz-aware datetime suitable for chronological sorting."""
    if value is None:
        return datetime.min.replace(tzinfo=UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _parse_detail(raw: str | None) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


class AuditTrailQueryService:
    """Static merged-view query service over the three audit sources."""

    @staticmethod
    async def list_for_chart(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        since: datetime | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Return the merged chronological audit trail for a chart.

        Each returned dict has the keys::

            {
              "id":        str,
              "kind":      str,           # canonical event kind
              "source":    str,           # 'audit_log' | 'ai_audit_event' | 'provider_override'
              "occurredAt": str (ISO-8601 UTC),
              "userId":    str | None,
              "payload":   dict | str | None,
            }

        Rows are ordered ascending by ``occurredAt`` and capped at
        ``limit`` entries (most recent ``limit`` rows when more exist).
        """
        if limit is None or limit <= 0:
            limit = 200

        merged: list[tuple[datetime, dict[str, Any]]] = []

        merged.extend(
            await AuditTrailQueryService._load_audit_log(
                session, tenant_id, chart_id, since
            )
        )
        merged.extend(
            await AuditTrailQueryService._load_ai_audit_events(
                session, tenant_id, chart_id, since
            )
        )
        merged.extend(
            await AuditTrailQueryService._load_provider_overrides(
                session, tenant_id, chart_id, since
            )
        )

        # Stable sort ascending by timestamp, then id for determinism.
        merged.sort(key=lambda pair: (pair[0], pair[1]["id"]))

        if len(merged) > limit:
            merged = merged[-limit:]

        return [entry for _, entry in merged]

    # --------------------------- sources --------------------------- #

    @staticmethod
    async def _load_audit_log(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        since: datetime | None,
    ) -> list[tuple[datetime, dict[str, Any]]]:
        stmt = select(EpcrAuditLog).where(
            and_(
                EpcrAuditLog.tenant_id == tenant_id,
                EpcrAuditLog.chart_id == chart_id,
            )
        )
        if since is not None:
            stmt = stmt.where(EpcrAuditLog.performed_at >= since)
        rows = (await session.execute(stmt)).scalars().all()
        out: list[tuple[datetime, dict[str, Any]]] = []
        for r in rows:
            occurred = _coerce_dt(r.performed_at)
            out.append(
                (
                    occurred,
                    {
                        "id": r.id,
                        "kind": r.action,
                        "source": "audit_log",
                        "occurredAt": _iso(r.performed_at),
                        "userId": r.user_id,
                        "payload": _parse_detail(r.detail_json),
                    },
                )
            )
        return out

    @staticmethod
    async def _load_ai_audit_events(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        since: datetime | None,
    ) -> list[tuple[datetime, dict[str, Any]]]:
        if EpcrAiAuditEvent is None:
            return []
        stmt = select(EpcrAiAuditEvent).where(
            and_(
                EpcrAiAuditEvent.tenant_id == tenant_id,
                EpcrAiAuditEvent.chart_id == chart_id,
            )
        )
        if since is not None:
            stmt = stmt.where(EpcrAiAuditEvent.performed_at >= since)
        try:
            rows = (await session.execute(stmt)).scalars().all()
        except SQLAlchemyError:
            # Table may not yet exist in environments that have not
            # applied the AI-evidence migration. Degrade to empty.
            logger.debug(
                "EpcrAiAuditEvent table unavailable; returning empty AI slice"
            )
            return []
        out: list[tuple[datetime, dict[str, Any]]] = []
        for r in rows:
            occurred = _coerce_dt(r.performed_at)
            out.append(
                (
                    occurred,
                    {
                        "id": r.id,
                        "kind": r.event_kind,
                        "source": "ai_audit_event",
                        "occurredAt": _iso(r.performed_at),
                        "userId": r.user_id,
                        "payload": _parse_detail(r.payload_json),
                    },
                )
            )
        return out

    @staticmethod
    async def _load_provider_overrides(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        since: datetime | None,
    ) -> list[tuple[datetime, dict[str, Any]]]:
        stmt = select(EpcrProviderOverride).where(
            and_(
                EpcrProviderOverride.tenant_id == tenant_id,
                EpcrProviderOverride.chart_id == chart_id,
            )
        )
        if since is not None:
            stmt = stmt.where(EpcrProviderOverride.overrode_at >= since)
        rows = (await session.execute(stmt)).scalars().all()
        out: list[tuple[datetime, dict[str, Any]]] = []
        for r in rows:
            occurred = _coerce_dt(r.overrode_at)
            payload = {
                "overrideId": r.id,
                "section": r.section,
                "fieldKey": r.field_key,
                "kind": r.kind,
                "reasonText": r.reason_text,
                "supervisorId": r.supervisor_id,
                "supervisorConfirmedAt": _iso(r.supervisor_confirmed_at),
            }
            out.append(
                (
                    occurred,
                    {
                        "id": r.id,
                        "kind": f"provider_override.{r.kind}",
                        "source": "provider_override",
                        "occurredAt": _iso(r.overrode_at),
                        "userId": r.overrode_by,
                        "payload": payload,
                    },
                )
            )
        return out


__all__ = ["AuditTrailQueryService"]
