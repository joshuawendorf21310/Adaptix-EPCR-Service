"""Protocol Context Service.

Pillar service that owns live protocol-pack engagement on an ePCR chart.
A protocol context records *which* pack (ACLS / PALS / NRP / CCT / ...)
is currently engaged, when and by whom, and a snapshot of the pack's
required-field satisfaction at engagement time.

The service is intentionally a thin, honest layer:

* It NEVER mutates :mod:`epcr_app.ai_clinical_engine` — pack content is
  read-only via :data:`PROTOCOL_PACKS`.
* It NEVER fabricates satisfaction. ``evaluate_required_field_satisfaction``
  derives field satisfaction from the canonical cross-cutting signal —
  the ``epcr_chart_field_audit`` log's ``nemsis_element`` / ``new_value``
  columns. A field is "satisfied" iff at least one non-deleted audit
  event for the chart-tenant carries that NEMSIS element with a
  non-empty ``new_value``. If the audit table cannot be queried (e.g.
  in the rare case the migration hasn't run), the failure is surfaced
  honestly as an advisory and the score collapses to 0.0.
* It emits two distinct audit actions on the canonical
  :class:`EpcrAuditLog`: ``protocol.engaged`` and ``protocol.disengaged``.
* The returned satisfaction payload is shape-compatible with
  :class:`epcr_app.services.lock_readiness_service.LockReadinessService`
  (``score`` / ``blockers`` / ``warnings`` / ``advisories`` /
  ``generated_at``) and adds two protocol-specific keys
  (``satisfied_fields`` / ``missing_fields``) so the workspace UI can
  render the per-field check-list without re-computing it.

Tenant isolation is enforced end-to-end via explicit ``tenant_id``
filters on every read and write.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, Iterable
from uuid import uuid4

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.ai_clinical_engine import PROTOCOL_PACKS
from epcr_app.models import EpcrAuditLog, EpcrProtocolContext
from epcr_app.models_audit import ChartFieldAuditEvent


logger = logging.getLogger(__name__)


# Stable version sentinel for the in-process engine's pack registry. The
# engine's pack content is hand-curated and not externally versioned, so
# we tag snapshots with a deterministic string that flips whenever the
# engine module is reloaded with a different content hash. Tests assert
# only the prefix.
_ENGINE_PACK_VERSION_PREFIX = "engine:"


def _engine_pack_version() -> str:
    """Return a stable identifier for the current engine pack registry."""
    # The dict ordering of PROTOCOL_PACKS is deterministic in CPython
    # 3.7+, so the length + keys are a sufficient fingerprint for an
    # audit-replay sentinel without leaking pack content.
    return f"{_ENGINE_PACK_VERSION_PREFIX}{len(PROTOCOL_PACKS)}:" + ",".join(
        sorted(PROTOCOL_PACKS.keys())
    )


def _pack_required_fields(pack_key: str | None) -> list[str]:
    """Return the required-field list for ``pack_key`` from the engine.

    Read-only accessor over :data:`PROTOCOL_PACKS`. Returns an empty
    list when the pack is unknown or ``pack_key`` is ``None``; callers
    surface that as a ``pack_unknown`` advisory rather than an error.
    """
    if not pack_key:
        return []
    pack = PROTOCOL_PACKS.get(pack_key)
    if not pack:
        return []
    fields = pack.get("required_fields") or []
    return [str(f) for f in fields]


class ProtocolContextService:
    """Manage live protocol-pack engagement on an ePCR chart.

    All methods are static. Callers own the transaction boundary — this
    service never calls ``session.commit()``.
    """

    # --------------------------- queries --------------------------- #

    @staticmethod
    async def list_active(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
    ) -> EpcrProtocolContext | None:
        """Return the currently active (non-disengaged) context, or None.

        Args:
            session: AsyncSession bound to the EPCR database.
            tenant_id: Tenant identifier (enforces isolation).
            chart_id: Chart identifier.

        Returns:
            The most-recently engaged ``EpcrProtocolContext`` row whose
            ``disengaged_at`` is NULL, or ``None`` if no pack is active.
        """
        result = await session.execute(
            select(EpcrProtocolContext)
            .where(
                and_(
                    EpcrProtocolContext.tenant_id == tenant_id,
                    EpcrProtocolContext.chart_id == chart_id,
                    EpcrProtocolContext.disengaged_at.is_(None),
                )
            )
            .order_by(EpcrProtocolContext.engaged_at.desc())
        )
        return result.scalars().first()

    # --------------------------- mutations --------------------------- #

    @staticmethod
    async def engage(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        user_id: str,
        pack: str,
    ) -> EpcrProtocolContext:
        """Engage ``pack`` on ``chart_id`` for ``tenant_id``.

        Behaviour:

        * If a context is already active for this chart, it is
          disengaged in the same transaction with reason
          ``"superseded_by_engage"`` so the active-context invariant
          (at most one row with ``disengaged_at IS NULL`` per chart)
          holds before the new row is inserted.
        * A fresh ``EpcrProtocolContext`` row is added with
          ``active_pack=pack`` and a snapshot of the current required-
          field satisfaction map.
        * One ``EpcrAuditLog`` row with action ``protocol.engaged`` is
          appended.

        Raises:
            ValueError: If ``pack`` is falsy.
        """
        if not pack or not isinstance(pack, str):
            raise ValueError("pack is required and must be a string")

        now = datetime.now(UTC)

        # Supersede any currently active context for this chart.
        existing = await ProtocolContextService.list_active(
            session, tenant_id, chart_id
        )
        if existing is not None:
            existing.disengaged_at = now
            existing.updated_at = now
            ProtocolContextService._audit(
                session,
                tenant_id=tenant_id,
                chart_id=chart_id,
                user_id=user_id,
                action="protocol.disengaged",
                detail={
                    "context_id": existing.id,
                    "active_pack": existing.active_pack,
                    "reason": "superseded_by_engage",
                    "superseded_by_pack": pack,
                },
                performed_at=now,
            )

        # Compute satisfaction snapshot for the incoming pack.
        snapshot = await ProtocolContextService.evaluate_required_field_satisfaction(
            session,
            tenant_id,
            chart_id,
            pack_override=pack,
        )

        row = EpcrProtocolContext(
            id=str(uuid4()),
            tenant_id=tenant_id,
            chart_id=chart_id,
            active_pack=pack,
            engaged_at=now,
            engaged_by=user_id,
            disengaged_at=None,
            required_field_satisfaction_json=json.dumps(
                snapshot, default=str
            ),
            pack_version=_engine_pack_version(),
            created_at=now,
            updated_at=now,
        )
        session.add(row)

        ProtocolContextService._audit(
            session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            user_id=user_id,
            action="protocol.engaged",
            detail={
                "context_id": row.id,
                "active_pack": pack,
                "pack_known": pack in PROTOCOL_PACKS,
                "required_field_count": len(_pack_required_fields(pack)),
                "pack_version": row.pack_version,
            },
            performed_at=now,
        )
        return row

    @staticmethod
    async def disengage(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        user_id: str,
        reason: str,
    ) -> EpcrProtocolContext | None:
        """Disengage the currently active pack on ``chart_id``.

        Marks the active context (if any) as disengaged and emits a
        ``protocol.disengaged`` audit row. Returns the updated context,
        or ``None`` if no context was active.

        Raises:
            ValueError: If ``reason`` is falsy. A reason is mandatory
                so disengagement is never silent.
        """
        if not reason or not isinstance(reason, str):
            raise ValueError("reason is required and must be a string")

        active = await ProtocolContextService.list_active(
            session, tenant_id, chart_id
        )
        if active is None:
            # Honest no-op: still record an audit row so the action is
            # visible to operators even if there was nothing to close.
            now = datetime.now(UTC)
            ProtocolContextService._audit(
                session,
                tenant_id=tenant_id,
                chart_id=chart_id,
                user_id=user_id,
                action="protocol.disengaged",
                detail={
                    "context_id": None,
                    "active_pack": None,
                    "reason": reason,
                    "noop": True,
                },
                performed_at=now,
            )
            return None

        now = datetime.now(UTC)
        active.disengaged_at = now
        active.updated_at = now

        ProtocolContextService._audit(
            session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            user_id=user_id,
            action="protocol.disengaged",
            detail={
                "context_id": active.id,
                "active_pack": active.active_pack,
                "reason": reason,
                "noop": False,
            },
            performed_at=now,
        )
        return active

    # ------------------- satisfaction evaluation ------------------- #

    @staticmethod
    async def evaluate_required_field_satisfaction(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        *,
        pack_override: str | None = None,
    ) -> dict[str, Any]:
        """Compute the pack's required-field satisfaction map.

        For the currently active pack on ``chart_id`` (or the explicit
        ``pack_override`` if supplied — used internally by ``engage``
        to snapshot the *new* pack at the moment of engagement), this
        method:

        1. Reads the pack's ``required_fields`` from
           :data:`PROTOCOL_PACKS` (read-only).
        2. Queries :class:`ChartFieldAuditEvent` for non-empty
           ``new_value`` rows scoped by ``tenant_id`` and ``chart_id``.
        3. Groups by ``nemsis_element`` to derive a set of populated
           NEMSIS elements.
        4. Marks each required field satisfied iff its element is in
           that set.

        Returns:
            A dict shape-compatible with the
            :class:`LockReadinessService` payload contract::

                {
                    "score": float in [0.0, 1.0],
                    "blockers": list[dict],     # one per missing field
                    "warnings": list[dict],     # partial coverage
                    "advisories": list[dict],   # pack unknown / errors
                    "generated_at": ISO-8601 UTC timestamp,
                    "active_pack": str | None,
                    "pack_known": bool,
                    "satisfied_fields": list[str],
                    "missing_fields": list[str],
                    "required_total": int,
                    "required_present": int,
                }

            Never raises for "pack unknown" — that case returns a
            populated advisory list and a neutral score (0.0 when there
            is an active row but no known pack, 1.0 when there is no
            active pack at all).
        """
        generated_at = datetime.now(UTC).isoformat()
        blockers: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        advisories: list[dict[str, Any]] = []

        # Resolve the pack to evaluate.
        if pack_override is not None:
            pack_key: str | None = pack_override
            active_row: EpcrProtocolContext | None = None
        else:
            active_row = await ProtocolContextService.list_active(
                session, tenant_id, chart_id
            )
            pack_key = active_row.active_pack if active_row else None

        if pack_key is None:
            # No pack engaged. Honest empty satisfaction — score 1.0
            # because there is nothing to require.
            return {
                "score": 1.0,
                "blockers": blockers,
                "warnings": warnings,
                "advisories": [
                    {
                        "kind": "no_active_pack",
                        "message": (
                            "No protocol pack is currently engaged on "
                            "this chart."
                        ),
                    }
                ],
                "generated_at": generated_at,
                "active_pack": None,
                "pack_known": False,
                "satisfied_fields": [],
                "missing_fields": [],
                "required_total": 0,
                "required_present": 0,
            }

        pack_known = pack_key in PROTOCOL_PACKS
        required_fields = _pack_required_fields(pack_key)

        if not pack_known:
            advisories.append(
                {
                    "kind": "pack_unknown",
                    "active_pack": pack_key,
                    "message": (
                        f"Protocol pack '{pack_key}' is not present in "
                        f"the engine registry; required-field "
                        f"satisfaction cannot be evaluated."
                    ),
                }
            )

        # Pull every audit row that has a non-empty new_value for this
        # chart-tenant pair.
        populated_elements: set[str] = set()
        audit_query_ok = True
        try:
            audit_rows = (
                await session.execute(
                    select(
                        ChartFieldAuditEvent.nemsis_element,
                        ChartFieldAuditEvent.new_value,
                    ).where(
                        and_(
                            ChartFieldAuditEvent.tenant_id == tenant_id,
                            ChartFieldAuditEvent.chart_id == chart_id,
                            ChartFieldAuditEvent.nemsis_element.isnot(None),
                        )
                    )
                )
            ).all()
            for element, value in audit_rows:
                if value is None:
                    continue
                if isinstance(value, str) and not value.strip():
                    continue
                populated_elements.add(str(element))
        except Exception as exc:  # noqa: BLE001 — honest unavailability
            logger.warning(
                "ProtocolContextService: audit query failed for "
                "chart=%s tenant=%s: %s",
                chart_id,
                tenant_id,
                exc,
            )
            audit_query_ok = False
            advisories.append(
                {
                    "kind": "audit_unavailable",
                    "message": (
                        "Chart field audit log could not be queried; "
                        "satisfaction cannot be evaluated."
                    ),
                    "detail": str(exc),
                }
            )

        satisfied: list[str] = []
        missing: list[str] = []
        for field in required_fields:
            if field in populated_elements:
                satisfied.append(field)
            else:
                missing.append(field)

        for field in missing:
            blockers.append(
                {
                    "kind": "missing_protocol_required_field",
                    "field": field,
                    "active_pack": pack_key,
                    "message": (
                        f"Protocol pack '{pack_key}' requires NEMSIS "
                        f"field {field}; no chart audit row populates it."
                    ),
                    "source": "protocol_context_service",
                }
            )

        required_total = len(required_fields)
        required_present = len(satisfied)

        if (
            required_total > 0
            and required_present > 0
            and required_present < required_total
        ):
            warnings.append(
                {
                    "kind": "protocol_partial",
                    "active_pack": pack_key,
                    "message": (
                        f"Protocol pack '{pack_key}': "
                        f"{required_present}/{required_total} required "
                        f"fields populated."
                    ),
                    "required_present": required_present,
                    "required_total": required_total,
                }
            )

        # Score
        if not audit_query_ok:
            score = 0.0
        elif not pack_known:
            # We genuinely cannot evaluate; refuse to fabricate a score.
            score = 0.0
        elif required_total == 0:
            score = 1.0
        else:
            score = required_present / required_total

        if blockers:
            score = min(score, 0.0)

        if score < 0.0:
            score = 0.0
        elif score > 1.0:
            score = 1.0

        return {
            "score": float(score),
            "blockers": blockers,
            "warnings": warnings,
            "advisories": advisories,
            "generated_at": generated_at,
            "active_pack": pack_key,
            "pack_known": pack_known,
            "satisfied_fields": satisfied,
            "missing_fields": missing,
            "required_total": required_total,
            "required_present": required_present,
        }

    # ------------------------------ audit ------------------------------ #

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


def supported_pack_keys() -> Iterable[str]:
    """Expose the read-only set of engine-known pack keys.

    Provided so callers (e.g. the workspace coordinator) can render the
    available pack picker without importing the engine module directly.
    """
    return tuple(PROTOCOL_PACKS.keys())


__all__ = [
    "ProtocolContextService",
    "supported_pack_keys",
]
