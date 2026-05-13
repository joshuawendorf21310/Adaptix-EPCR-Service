"""Prior-ECG service: attach, list, and record provider-attested comparison.

CRITICAL CONTRACT
=================
This module performs NO clinical inference. It must never produce a
diagnostic label, rhythm reading, or any automated finding. The
``comparison_state`` field is a pre-enumerated value chosen by the
provider; the row is only consumable by exports when
``provider_confirmed`` is true (the provider has personally compared
the two ECGs).

The frontend EcgSnapshotCard enforces an analogous rule: no rendering
of diagnostic verbiage. The capability flip surface here exists only
to indicate that comparison plumbing is wired up.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models import (
    EpcrAuditLog,
    EpcrEcgComparisonResult,
    EpcrPriorEcgReference,
)

logger = logging.getLogger(__name__)


ALLOWED_QUALITY = frozenset(
    {"good", "acceptable", "poor", "unable_to_compare"}
)
ALLOWED_COMPARISON_STATES = frozenset(
    {"similar", "different", "unable_to_compare", "not_relevant"}
)


class PriorEcgValidationError(ValueError):
    """Raised when an attach or comparison payload fails validation."""


def _coerce_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed
    raise PriorEcgValidationError("captured_at must be datetime or ISO string")


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


async def list_prior_for_chart(
    session: AsyncSession, tenant_id: str, chart_id: str
) -> list[EpcrPriorEcgReference]:
    """Return all prior-ECG references for a chart in deterministic order."""
    rows = (
        await session.execute(
            select(EpcrPriorEcgReference)
            .where(
                and_(
                    EpcrPriorEcgReference.chart_id == chart_id,
                    EpcrPriorEcgReference.tenant_id == tenant_id,
                )
            )
            .order_by(
                EpcrPriorEcgReference.captured_at,
                EpcrPriorEcgReference.id,
            )
        )
    ).scalars().all()
    return list(rows)


async def attach_prior(
    session: AsyncSession,
    tenant_id: str,
    chart_id: str,
    user_id: str,
    prior_chart_id: str | None,
    image_storage_uri: str | None,
    encounter_context: str,
    monitor_imported: bool,
    quality: str,
    captured_at: Any | None = None,
    notes: str | None = None,
) -> EpcrPriorEcgReference:
    """Persist a prior-ECG reference and emit an audit row.

    No clinical inference is performed. ``quality`` must be one of the
    pre-enumerated values.
    """
    if quality not in ALLOWED_QUALITY:
        raise PriorEcgValidationError(
            f"quality must be one of {sorted(ALLOWED_QUALITY)}; got {quality!r}"
        )
    if not encounter_context or not str(encounter_context).strip():
        raise PriorEcgValidationError("encounter_context is required")

    now = datetime.now(UTC)
    captured = _coerce_dt(captured_at) if captured_at is not None else now

    row = EpcrPriorEcgReference(
        id=str(uuid4()),
        tenant_id=tenant_id,
        chart_id=chart_id,
        prior_chart_id=prior_chart_id,
        captured_at=captured,
        encounter_context=str(encounter_context),
        image_storage_uri=image_storage_uri,
        monitor_imported=bool(monitor_imported),
        quality=quality,
        notes=notes,
        created_at=now,
    )
    session.add(row)
    await session.flush()

    _audit(
        session,
        tenant_id=tenant_id,
        chart_id=chart_id,
        user_id=user_id,
        action="ecg.prior_attached",
        detail={
            "prior_ecg_id": row.id,
            "prior_chart_id": prior_chart_id,
            "encounter_context": encounter_context,
            "monitor_imported": bool(monitor_imported),
            "quality": quality,
        },
        performed_at=now,
    )
    await session.flush()
    return row


async def record_comparison(
    session: AsyncSession,
    tenant_id: str,
    chart_id: str,
    user_id: str,
    prior_ecg_id: str,
    comparison_state: str,
    notes: str | None = None,
) -> EpcrEcgComparisonResult:
    """Persist a provider-attested comparison result.

    Invoking this action is itself the provider's attestation that they
    personally compared the current ECG with the referenced prior. We
    therefore set ``provider_confirmed=True``, ``provider_id=user_id``,
    and ``confirmed_at=now``. No clinical reading is generated.
    """
    if comparison_state not in ALLOWED_COMPARISON_STATES:
        raise PriorEcgValidationError(
            "comparison_state must be one of "
            f"{sorted(ALLOWED_COMPARISON_STATES)}; got {comparison_state!r}"
        )

    prior = (
        await session.execute(
            select(EpcrPriorEcgReference).where(
                and_(
                    EpcrPriorEcgReference.id == prior_ecg_id,
                    EpcrPriorEcgReference.tenant_id == tenant_id,
                    EpcrPriorEcgReference.chart_id == chart_id,
                )
            )
        )
    ).scalar_one_or_none()
    if prior is None:
        raise PriorEcgValidationError(
            f"prior_ecg_id {prior_ecg_id!r} not found for chart {chart_id!r}"
        )

    now = datetime.now(UTC)
    row = EpcrEcgComparisonResult(
        id=str(uuid4()),
        tenant_id=tenant_id,
        chart_id=chart_id,
        prior_ecg_id=prior_ecg_id,
        comparison_state=comparison_state,
        provider_confirmed=True,
        provider_id=user_id,
        confirmed_at=now,
        confidence=None,
        notes=notes,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.flush()

    _audit(
        session,
        tenant_id=tenant_id,
        chart_id=chart_id,
        user_id=user_id,
        action="ecg.comparison_recorded",
        detail={
            "comparison_id": row.id,
            "prior_ecg_id": prior_ecg_id,
            "comparison_state": comparison_state,
            "provider_confirmed": True,
        },
        performed_at=now,
    )
    await session.flush()
    return row


def is_comparison_ready_for_export(
    comparison: EpcrEcgComparisonResult | None,
) -> bool:
    """Gate function used by the NEMSIS exporter.

    Returns False unless the comparison row exists AND has
    ``provider_confirmed=True``. No other field is sufficient.
    """
    if comparison is None:
        return False
    return bool(getattr(comparison, "provider_confirmed", False))


__all__ = [
    "ALLOWED_COMPARISON_STATES",
    "ALLOWED_QUALITY",
    "PriorEcgValidationError",
    "attach_prior",
    "is_comparison_ready_for_export",
    "list_prior_for_chart",
    "record_comparison",
]
