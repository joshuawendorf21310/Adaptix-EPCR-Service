"""Lock readiness aggregation service.

Pillar service that aggregates the chart's readiness signals into a single
honest payload consumable by the EPCR workspace UI:

* NEMSIS mandatory-field compliance (via the canonical
  ``ChartService.check_nemsis_compliance``) — produces ``blockers`` for any
  missing mandatory field and a ``required_present / required_total``
  readiness row.
* Workspace ``unmapped_fields`` — sections with no canonical backend owner
  today; surfaced as ``advisories`` rather than blockers so the UI does
  not block lock on infrastructure gaps the user cannot resolve.
* Active audit anomalies — any audit log row whose ``action`` carries the
  ``anomaly`` token; surfaced as ``warnings`` so the user can review
  before locking.

This service is AGGREGATION-only. It does not create or own any model,
migration, or new persistence. It calls existing canonical surfaces and
returns a transport-shaped dict:

    {
        "score": float in [0.0, 1.0],
        "blockers": list[dict],
        "warnings": list[dict],
        "advisories": list[dict],
        "generated_at": ISO 8601 UTC timestamp,
    }

No fake success. If the compliance check raises, the failure is reflected
as a single advisory entry and ``score`` collapses to ``0.0`` — never a
fabricated passing score.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models import EpcrAuditLog
from epcr_app.services import ChartService


logger = logging.getLogger(__name__)


# Sections with no canonical backend owner today. Kept in sync with
# ``chart_workspace_service.UNMAPPED_SECTIONS`` but not imported from it to
# avoid a circular dependency at module import time (the workspace service
# imports this service, not the reverse).
_DEFAULT_UNMAPPED_SECTIONS: tuple[str, ...] = (
    "response",
    "crew",
    "history",
    "allergies",
    "home_medications",
    "disposition",
    "destination",
    "attachments",
    "export",
)


class LockReadinessService:
    """Aggregate per-chart readiness signals for the lock decision.

    All methods are static. Tenant isolation is enforced end-to-end by
    delegating to ``ChartService`` and by scoping every direct query on
    ``EpcrAuditLog`` by ``tenant_id``.
    """

    @staticmethod
    async def get_for_chart(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        *,
        unmapped_sections: tuple[str, ...] | list[str] | None = None,
    ) -> dict[str, Any]:
        """Return the aggregated readiness payload for ``chart_id``.

        Args:
            session: AsyncSession bound to the EPCR database.
            tenant_id: Tenant identifier (enforces tenant isolation).
            chart_id: Chart identifier the readiness applies to.
            unmapped_sections: Optional override of the unmapped section
                list. Defaults to the canonical workspace list. Tests
                inject a narrower list to make assertions stable.

        Returns:
            dict with keys ``score``, ``blockers``, ``warnings``,
            ``advisories``, ``generated_at``.
        """

        generated_at = datetime.now(UTC).isoformat()
        blockers: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        advisories: list[dict[str, Any]] = []

        # --- 1. NEMSIS compliance gate ---------------------------------- #
        required_present = 0
        required_total = 0
        compliance_available = True
        try:
            compliance = await ChartService.check_nemsis_compliance(
                session, tenant_id, chart_id
            )
        except Exception as exc:  # noqa: BLE001 — honest unavailability
            logger.warning(
                "LockReadinessService: compliance check failed for "
                "chart=%s tenant=%s: %s",
                chart_id,
                tenant_id,
                exc,
            )
            compliance_available = False
            compliance = {}
            advisories.append(
                {
                    "kind": "nemsis_compliance_unavailable",
                    "message": (
                        "NEMSIS compliance check could not be evaluated."
                    ),
                    "detail": str(exc),
                }
            )

        if compliance_available:
            required_total = int(
                compliance.get("mandatory_fields_required", 0) or 0
            )
            required_present = int(
                compliance.get("mandatory_fields_filled", 0) or 0
            )
            missing = compliance.get("missing_mandatory_fields") or []
            for field_id in missing:
                blockers.append(
                    {
                        "kind": "missing_mandatory_field",
                        "field": field_id,
                        "message": (
                            f"NEMSIS mandatory field {field_id} is not "
                            f"populated."
                        ),
                        "source": "nemsis_finalization_gate",
                    }
                )

            # Readiness row: required_present < required_total → warning.
            # When fully present, no warning is emitted.
            if required_total > 0 and required_present < required_total:
                warnings.append(
                    {
                        "kind": "readiness_partial",
                        "message": (
                            f"NEMSIS readiness: "
                            f"{required_present}/{required_total} mandatory "
                            f"fields populated."
                        ),
                        "required_present": required_present,
                        "required_total": required_total,
                    }
                )

        # --- 2. Workspace unmapped fields ------------------------------- #
        sections = tuple(
            unmapped_sections
            if unmapped_sections is not None
            else _DEFAULT_UNMAPPED_SECTIONS
        )
        for section in sorted(sections):
            advisories.append(
                {
                    "kind": "unmapped_field",
                    "section": section,
                    "reason": "field_not_mapped",
                    "message": (
                        f"Section '{section}' has no canonical backend "
                        f"owner; lock proceeds without it."
                    ),
                }
            )

        # --- 3. Active audit anomalies ---------------------------------- #
        audit_rows = (
            await session.execute(
                select(EpcrAuditLog)
                .where(
                    and_(
                        EpcrAuditLog.chart_id == chart_id,
                        EpcrAuditLog.tenant_id == tenant_id,
                        EpcrAuditLog.deleted_at.is_(None),
                    )
                )
                .order_by(EpcrAuditLog.performed_at.desc())
            )
        ).scalars().all()
        for row in audit_rows:
            action = (row.action or "").lower()
            if "anomaly" not in action:
                continue
            warnings.append(
                {
                    "kind": "audit_anomaly",
                    "audit_id": row.id,
                    "action": row.action,
                    "user_id": row.user_id,
                    "detail": row.detail_json,
                    "performed_at": (
                        row.performed_at.isoformat()
                        if row.performed_at
                        else None
                    ),
                    "message": (
                        f"Audit anomaly recorded: {row.action}."
                    ),
                }
            )

        # --- 4. Score math ---------------------------------------------- #
        # Score is the fraction of mandatory fields present, minus a small
        # penalty for each active warning. Score is clamped to [0, 1].
        # Blockers force the score floor to 0.0 — a chart with any missing
        # mandatory field is never reported as "ready" even if every other
        # signal is clean.
        if not compliance_available:
            score = 0.0
        elif required_total <= 0:
            # No mandatory fields to evaluate. Treat as fully ready iff
            # there are no blockers and no warnings, otherwise neutral 0.5.
            score = 1.0 if not (blockers or warnings) else 0.5
        else:
            base = required_present / required_total
            # Each warning shaves 5% off, capped so warnings alone cannot
            # drop a fully-compliant chart below 0.5.
            penalty = min(0.5, 0.05 * len(warnings))
            score = max(0.0, base - penalty)

        if blockers:
            score = min(score, 0.0)

        # Clamp defensively.
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
        }


__all__ = ["LockReadinessService"]
