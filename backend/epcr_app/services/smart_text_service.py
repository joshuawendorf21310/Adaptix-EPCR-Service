"""SmartTextService — resolves clinical phrase suggestions for chart fields.

This pillar offers ranked, structured ``EpcrSmartTextSuggestion`` rows
for a chart-field slot. Suggestions are sourced from existing libraries
(agency phrase library, provider favorites, protocol library) or from
AI ingestion that other services (e.g. :mod:`ai_clinical_engine`) write
into the ``epcr_smart_text_suggestion`` table.

Design constraints enforced here:

- **No AI calls.** This service never reaches out to an LLM. The AI
  ingestion path lives in :mod:`epcr_app.ai_clinical_engine` and writes
  rows of source ``ai`` directly. Read-only consumption only.
- **Honest empty responses.** If no upstream phrase library table is
  present in this deployment, :func:`resolve_for_field` returns an empty
  list instead of a fabricated/stubbed dataset.
- **Every suggestion carries provenance.** ``source`` +
  ``confidence`` + ``compliance_state`` are always populated.
- **Caller owns the transaction.** This module never calls
  ``session.commit()``; the route/handler is responsible for boundaries.

Audit:
- :func:`accept` writes ``smart_text.accepted`` to :class:`EpcrAuditLog`.
- :func:`reject` writes ``smart_text.rejected`` to :class:`EpcrAuditLog`.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models import EpcrAuditLog, EpcrSmartTextSuggestion

logger = logging.getLogger(__name__)


# Canonical value sets — also enforced at DB layer via CheckConstraint.
ALLOWED_SOURCES: frozenset[str] = frozenset(
    {"agency_library", "provider_favorite", "protocol", "ai"}
)
ALLOWED_COMPLIANCE_STATES: frozenset[str] = frozenset(
    {"approved", "pending", "risk"}
)


def _serialize(row: EpcrSmartTextSuggestion) -> dict[str, Any]:
    """Return the camelCase contract shape for a single suggestion."""
    return {
        "id": row.id,
        "chartId": row.chart_id,
        "tenantId": row.tenant_id,
        "section": row.section,
        "fieldKey": row.field_key,
        "phrase": row.phrase,
        "source": row.source,
        "confidence": (
            float(row.confidence)
            if isinstance(row.confidence, Decimal)
            else row.confidence
        ),
        "complianceState": row.compliance_state,
        "evidenceLinkId": row.evidence_link_id,
        "accepted": row.accepted,
        "acceptedAt": (
            row.accepted_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
            if isinstance(row.accepted_at, datetime)
            else None
        ),
        "performedBy": row.performed_by,
    }


async def _table_exists(session: AsyncSession, table_name: str) -> bool:
    """Return True iff ``table_name`` is present in the live schema.

    Used by :func:`resolve_for_field` to honestly skip phrase-library
    lookups when the upstream table is not deployed in this environment.
    """

    def _check(sync_conn) -> bool:
        return inspect(sync_conn).has_table(table_name)

    bind = session.get_bind() if hasattr(session, "get_bind") else None
    try:
        conn = await session.connection()
        return await conn.run_sync(_check)
    except Exception:  # pragma: no cover — defensive
        logger.debug("table existence check failed for %s", table_name, exc_info=True)
        return False


async def resolve_for_field(
    session: AsyncSession,
    tenant_id: str,
    chart_id: str,
    section: str,
    field_key: str,
) -> list[dict[str, Any]]:
    """Return ranked suggestions for ``(tenant_id, chart_id, section, field_key)``.

    Strategy:

    1. Always return any persisted ``EpcrSmartTextSuggestion`` rows that
       match the slot and are still pending (``accepted IS NULL``).
       These include AI-ingested rows written by other services.
    2. Honestly return an empty list when no phrase-library or
       provider-favorite tables are present in the schema. We do not
       fabricate suggestions.

    Order: by ``confidence`` DESC, then ``created_at`` ASC for stable
    presentation.
    """
    rows = (
        await session.execute(
            select(EpcrSmartTextSuggestion)
            .where(
                and_(
                    EpcrSmartTextSuggestion.tenant_id == tenant_id,
                    EpcrSmartTextSuggestion.chart_id == chart_id,
                    EpcrSmartTextSuggestion.section == section,
                    EpcrSmartTextSuggestion.field_key == field_key,
                    EpcrSmartTextSuggestion.accepted.is_(None),
                )
            )
            .order_by(
                EpcrSmartTextSuggestion.confidence.desc(),
                EpcrSmartTextSuggestion.created_at.asc(),
                EpcrSmartTextSuggestion.id.asc(),
            )
        )
    ).scalars().all()

    suggestions: list[dict[str, Any]] = [_serialize(r) for r in rows]

    # Optional: in the future, also project from agency_phrase_library /
    # provider_favorite_phrase / protocol_phrase tables. Today we honor
    # the contract by emitting an empty contribution when those tables
    # are absent — never a fake row.
    for optional_table in (
        "epcr_agency_phrase_library",
        "epcr_provider_phrase_favorite",
        "epcr_protocol_phrase",
    ):
        if await _table_exists(session, optional_table):
            # Real projection is reserved for the slice that introduces
            # these tables. Until then we deliberately decline to invent
            # rows.
            logger.debug(
                "smart_text: %s present but projection not yet wired",
                optional_table,
            )

    return suggestions


def _validate_suggestion_fields(
    *,
    source: str,
    confidence: float | Decimal,
    compliance_state: str,
) -> None:
    if source not in ALLOWED_SOURCES:
        raise ValueError(
            f"smart_text: invalid source {source!r}; "
            f"allowed={sorted(ALLOWED_SOURCES)}"
        )
    if compliance_state not in ALLOWED_COMPLIANCE_STATES:
        raise ValueError(
            f"smart_text: invalid compliance_state {compliance_state!r}; "
            f"allowed={sorted(ALLOWED_COMPLIANCE_STATES)}"
        )
    conf_f = float(confidence)
    if conf_f < 0.0 or conf_f > 1.0:
        raise ValueError(
            f"smart_text: confidence {conf_f} out of range [0, 1]"
        )


async def create_suggestion(
    session: AsyncSession,
    *,
    tenant_id: str,
    chart_id: str,
    section: str,
    field_key: str,
    phrase: str,
    source: str,
    confidence: float | Decimal,
    compliance_state: str,
    evidence_link_id: str | None = None,
) -> EpcrSmartTextSuggestion:
    """Persist a new suggestion row. Caller owns commit.

    Used by upstream ingestors (AI engine, agency library importers).
    Enforces the provenance triple (source + confidence + compliance_state).
    """
    _validate_suggestion_fields(
        source=source,
        confidence=confidence,
        compliance_state=compliance_state,
    )
    now = datetime.now(UTC)
    row = EpcrSmartTextSuggestion(
        id=str(uuid4()),
        chart_id=chart_id,
        tenant_id=tenant_id,
        section=section,
        field_key=field_key,
        phrase=phrase,
        source=source,
        confidence=Decimal(str(round(float(confidence), 2))),
        compliance_state=compliance_state,
        evidence_link_id=evidence_link_id,
        accepted=None,
        accepted_at=None,
        performed_by=None,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.flush()
    return row


async def _load_suggestion(
    session: AsyncSession,
    tenant_id: str,
    chart_id: str,
    suggestion_id: str,
) -> EpcrSmartTextSuggestion | None:
    return (
        await session.execute(
            select(EpcrSmartTextSuggestion).where(
                and_(
                    EpcrSmartTextSuggestion.id == suggestion_id,
                    EpcrSmartTextSuggestion.tenant_id == tenant_id,
                    EpcrSmartTextSuggestion.chart_id == chart_id,
                )
            )
        )
    ).scalar_one_or_none()


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


async def accept(
    session: AsyncSession,
    tenant_id: str,
    chart_id: str,
    user_id: str,
    suggestion_id: str,
) -> dict[str, Any]:
    """Mark a suggestion accepted and write a ``smart_text.accepted`` audit row.

    Returns the serialized suggestion. Raises ``LookupError`` if the
    suggestion is not visible to the (tenant, chart) pair.
    """
    row = await _load_suggestion(session, tenant_id, chart_id, suggestion_id)
    if row is None:
        raise LookupError(
            f"smart_text: suggestion {suggestion_id!r} not found "
            f"for tenant={tenant_id!r} chart={chart_id!r}"
        )
    now = datetime.now(UTC)
    row.accepted = True
    row.accepted_at = now
    row.performed_by = user_id
    row.updated_at = now

    _audit(
        session,
        tenant_id=tenant_id,
        chart_id=chart_id,
        user_id=user_id,
        action="smart_text.accepted",
        detail={
            "suggestion_id": row.id,
            "section": row.section,
            "field_key": row.field_key,
            "source": row.source,
            "confidence": float(row.confidence)
            if isinstance(row.confidence, Decimal)
            else row.confidence,
            "compliance_state": row.compliance_state,
            "evidence_link_id": row.evidence_link_id,
        },
        performed_at=now,
    )
    await session.flush()
    return _serialize(row)


async def reject(
    session: AsyncSession,
    tenant_id: str,
    chart_id: str,
    user_id: str,
    suggestion_id: str,
) -> dict[str, Any]:
    """Mark a suggestion rejected and write a ``smart_text.rejected`` audit row.

    Returns the serialized suggestion. Raises ``LookupError`` if the
    suggestion is not visible to the (tenant, chart) pair.
    """
    row = await _load_suggestion(session, tenant_id, chart_id, suggestion_id)
    if row is None:
        raise LookupError(
            f"smart_text: suggestion {suggestion_id!r} not found "
            f"for tenant={tenant_id!r} chart={chart_id!r}"
        )
    now = datetime.now(UTC)
    row.accepted = False
    row.accepted_at = now
    row.performed_by = user_id
    row.updated_at = now

    _audit(
        session,
        tenant_id=tenant_id,
        chart_id=chart_id,
        user_id=user_id,
        action="smart_text.rejected",
        detail={
            "suggestion_id": row.id,
            "section": row.section,
            "field_key": row.field_key,
            "source": row.source,
            "confidence": float(row.confidence)
            if isinstance(row.confidence, Decimal)
            else row.confidence,
            "compliance_state": row.compliance_state,
            "evidence_link_id": row.evidence_link_id,
        },
        performed_at=now,
    )
    await session.flush()
    return _serialize(row)


__all__ = [
    "ALLOWED_SOURCES",
    "ALLOWED_COMPLIANCE_STATES",
    "accept",
    "create_suggestion",
    "reject",
    "resolve_for_field",
]
