"""Service for 3D Physical Assessment anatomical findings.

Owns the canonical replace-for-chart workflow:

- Validate each payload via :mod:`anatomical_finding_validation`.
- Diff inbound list against persisted non-deleted rows by ``id``.
- Insert new rows, update changed rows, soft-delete missing rows.
- Emit an :class:`EpcrAuditLog` row per change with structured
  ``before``/``after`` JSON.

This module never calls ``session.commit()``; the caller (typically
:class:`ChartWorkspaceService.update_workspace_section`) is responsible
for transaction boundaries so multiple section writes can be staged
atomically.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models import EpcrAnatomicalFinding, EpcrAuditLog
from epcr_app.services.anatomical_finding_validation import (
    AnatomicalFindingValidationError,
    validate_finding,
)

logger = logging.getLogger(__name__)


_SERIALIZE_FIELDS = (
    "region_id",
    "region_label",
    "body_view",
    "finding_type",
    "severity",
    "laterality",
    "pain_scale",
    "burn_tbsa_percent",
    "cms_pulse",
    "cms_motor",
    "cms_sensation",
    "cms_capillary_refill",
    "pertinent_negative",
    "notes",
    "assessed_at",
    "assessed_by",
)


def _iso(dt: Any) -> str | None:
    if dt is None:
        return None
    if isinstance(dt, str):
        # Accept ISO strings round-tripped from payload.
        try:
            parsed = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return dt
        return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return None


def _num(val: Any) -> Any:
    if isinstance(val, Decimal):
        return float(val)
    return val


class AnatomicalFindingService:
    """Static service over :class:`EpcrAnatomicalFinding`."""

    # --------------------------- serialization --------------------------- #

    @staticmethod
    def serialize(row: EpcrAnatomicalFinding) -> dict[str, Any]:
        """Serialize a row to the camelCase contract shared with the frontend."""
        return {
            "id": row.id,
            "regionId": row.region_id,
            "regionLabel": row.region_label,
            "bodyView": row.body_view,
            "findingType": row.finding_type,
            "severity": row.severity,
            "laterality": row.laterality,
            "painScale": row.pain_scale,
            "burnTbsaPercent": _num(row.burn_tbsa_percent),
            "cms": {
                "pulse": row.cms_pulse,
                "motor": row.cms_motor,
                "sensation": row.cms_sensation,
                "capillaryRefill": row.cms_capillary_refill,
            },
            "pertinentNegative": bool(row.pertinent_negative),
            "notes": row.notes,
            "assessedAt": _iso(row.assessed_at),
            "assessedBy": row.assessed_by,
        }

    @staticmethod
    def _snapshot(row: EpcrAnatomicalFinding) -> dict[str, Any]:
        snap: dict[str, Any] = {}
        for field in _SERIALIZE_FIELDS:
            val = getattr(row, field)
            if isinstance(val, datetime):
                val = _iso(val)
            elif isinstance(val, Decimal):
                val = float(val)
            snap[field] = val
        snap["id"] = row.id
        return snap

    # --------------------------- read --------------------------- #

    @staticmethod
    async def list_for_chart(
        session: AsyncSession, tenant_id: str, chart_id: str
    ) -> list[dict[str, Any]]:
        """Return all non-deleted findings for a chart in deterministic order."""
        rows = (
            await session.execute(
                select(EpcrAnatomicalFinding)
                .where(
                    and_(
                        EpcrAnatomicalFinding.chart_id == chart_id,
                        EpcrAnatomicalFinding.tenant_id == tenant_id,
                        EpcrAnatomicalFinding.deleted_at.is_(None),
                    )
                )
                .order_by(
                    EpcrAnatomicalFinding.assessed_at,
                    EpcrAnatomicalFinding.id,
                )
            )
        ).scalars().all()
        return [AnatomicalFindingService.serialize(r) for r in rows]

    # --------------------------- write --------------------------- #

    @staticmethod
    async def replace_for_chart(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        user_id: str,
        findings: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        """Reconcile the persisted finding list with the inbound payload.

        Validates first. All-or-nothing: a single invalid finding raises
        :class:`AnatomicalFindingValidationError` and no rows are mutated.
        """
        findings = findings or []
        if not isinstance(findings, list):
            raise AnatomicalFindingValidationError(
                [
                    {
                        "field": "anatomical_findings",
                        "message": "must be a list",
                    }
                ]
            )

        # Validate all up-front
        normalized: list[dict[str, Any]] = []
        all_errors: list[dict[str, str]] = []
        for idx, payload in enumerate(findings):
            try:
                normalized.append(validate_finding(payload))
            except AnatomicalFindingValidationError as exc:
                for err in exc.errors:
                    all_errors.append(
                        {
                            "field": f"anatomical_findings[{idx}].{err['field']}",
                            "message": err["message"],
                        }
                    )
        if all_errors:
            raise AnatomicalFindingValidationError(all_errors)

        existing_rows = (
            await session.execute(
                select(EpcrAnatomicalFinding).where(
                    and_(
                        EpcrAnatomicalFinding.chart_id == chart_id,
                        EpcrAnatomicalFinding.tenant_id == tenant_id,
                        EpcrAnatomicalFinding.deleted_at.is_(None),
                    )
                )
            )
        ).scalars().all()
        existing_by_id: dict[str, EpcrAnatomicalFinding] = {
            r.id: r for r in existing_rows
        }

        now = datetime.now(UTC)
        seen_ids: set[str] = set()

        for item in normalized:
            item_id = item.get("id")
            if item_id and item_id in existing_by_id:
                row = existing_by_id[item_id]
                before = AnatomicalFindingService._snapshot(row)
                changed = False
                for field in _SERIALIZE_FIELDS:
                    new_val = item.get(field)
                    cur_val = getattr(row, field)
                    if isinstance(cur_val, Decimal) and new_val is not None:
                        if float(cur_val) == float(new_val):
                            continue
                    if isinstance(cur_val, datetime):
                        if _iso(cur_val) == _iso(new_val):
                            continue
                    if cur_val == new_val:
                        continue
                    setattr(row, field, new_val)
                    changed = True
                if changed:
                    row.updated_at = now
                    after = AnatomicalFindingService._snapshot(row)
                    AnatomicalFindingService._audit(
                        session,
                        tenant_id=tenant_id,
                        chart_id=chart_id,
                        user_id=user_id,
                        action="anatomical_finding.updated",
                        detail={"before": before, "after": after},
                        performed_at=now,
                    )
                seen_ids.add(row.id)
            else:
                new_id = item_id or str(uuid4())
                row = EpcrAnatomicalFinding(
                    id=new_id,
                    chart_id=chart_id,
                    tenant_id=tenant_id,
                    region_id=item["region_id"],
                    region_label=item["region_label"],
                    body_view=item["body_view"],
                    finding_type=item["finding_type"],
                    severity=item.get("severity"),
                    laterality=item.get("laterality"),
                    pain_scale=item.get("pain_scale"),
                    burn_tbsa_percent=item.get("burn_tbsa_percent"),
                    cms_pulse=item.get("cms_pulse"),
                    cms_motor=item.get("cms_motor"),
                    cms_sensation=item.get("cms_sensation"),
                    cms_capillary_refill=item.get("cms_capillary_refill"),
                    pertinent_negative=bool(item.get("pertinent_negative", False)),
                    notes=item.get("notes"),
                    assessed_at=_coerce_dt(item["assessed_at"]),
                    assessed_by=item["assessed_by"],
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
                seen_ids.add(new_id)
                AnatomicalFindingService._audit(
                    session,
                    tenant_id=tenant_id,
                    chart_id=chart_id,
                    user_id=user_id,
                    action="anatomical_finding.created",
                    detail={
                        "before": None,
                        "after": AnatomicalFindingService._snapshot(row),
                    },
                    performed_at=now,
                )

        # Soft-delete any existing row not in the inbound list
        for existing_id, row in existing_by_id.items():
            if existing_id in seen_ids:
                continue
            before = AnatomicalFindingService._snapshot(row)
            row.deleted_at = now
            row.updated_at = now
            AnatomicalFindingService._audit(
                session,
                tenant_id=tenant_id,
                chart_id=chart_id,
                user_id=user_id,
                action="anatomical_finding.deleted",
                detail={"before": before, "after": None},
                performed_at=now,
            )

        await session.flush()
        return await AnatomicalFindingService.list_for_chart(
            session, tenant_id, chart_id
        )

    # --------------------------- audit --------------------------- #

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


def _coerce_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed
    raise ValueError("assessed_at must be datetime or ISO string")


__all__ = ["AnatomicalFindingService"]
