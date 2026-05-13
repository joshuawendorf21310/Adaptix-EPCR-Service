"""Service for tenant/agency-scoped eCustom NEMSIS fields.

Owns the canonical workflows for:

- Listing active ECustom field definitions for a (tenant, agency) pair.
- Validating an inbound value against its definition.
- Upserting a single value for a chart.
- Replacing the full set of ECustom values on a chart with diff-based
  insert / update / soft-equivalent delete semantics, emitting an
  :class:`EpcrAuditLog` row per change.

This module never calls ``session.commit()``; the caller (typically
:class:`ChartWorkspaceService.update_workspace_section`) is responsible
for transaction boundaries so multiple section writes stage atomically.
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
    EpcrECustomFieldDefinition,
    EpcrECustomFieldValue,
)
from epcr_app.services.ecustom_field_validation import (
    ValidationError,
    validate_field_value,
)

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def _dump_value(value: Any) -> str:
    return json.dumps(value, default=str)


def _load_value(raw: str | None) -> Any:
    if raw is None or raw == "":
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def validate_against_definition(
    value: Any,
    definition: EpcrECustomFieldDefinition,
    *,
    context: dict[str, Any] | None = None,
) -> Any:
    """Thin re-export so callers can validate without importing the validator.

    Returns the normalized value or raises
    :class:`epcr_app.services.ecustom_field_validation.ValidationError`.
    """
    return validate_field_value(definition, value, context=context)


class ECustomFieldService:
    """Static service over the ECustom field definition + value tables."""

    # --------------------------- definitions --------------------------- #

    @staticmethod
    async def list_definitions(
        session: AsyncSession,
        tenant_id: str,
        agency_id: str,
    ) -> list[EpcrECustomFieldDefinition]:
        """Return the non-retired field definitions for a (tenant, agency)."""
        rows = (
            await session.execute(
                select(EpcrECustomFieldDefinition)
                .where(
                    and_(
                        EpcrECustomFieldDefinition.tenant_id == tenant_id,
                        EpcrECustomFieldDefinition.agency_id == agency_id,
                        EpcrECustomFieldDefinition.retired.is_(False),
                    )
                )
                .order_by(
                    EpcrECustomFieldDefinition.field_key,
                    EpcrECustomFieldDefinition.version,
                )
            )
        ).scalars().all()
        return list(rows)

    @staticmethod
    def serialize_definition(
        definition: EpcrECustomFieldDefinition,
    ) -> dict[str, Any]:
        """Serialize a definition row to the camelCase frontend contract."""
        return {
            "id": definition.id,
            "tenantId": definition.tenant_id,
            "agencyId": definition.agency_id,
            "fieldKey": definition.field_key,
            "label": definition.label,
            "dataType": definition.data_type,
            "allowedValues": _load_value(definition.allowed_values_json),
            "required": bool(definition.required),
            "conditionalRule": _load_value(definition.conditional_rule_json),
            "nemsisRelationship": definition.nemsis_relationship,
            "stateProfile": definition.state_profile,
            "version": definition.version,
            "retired": bool(definition.retired),
        }

    @staticmethod
    def serialize_value(row: EpcrECustomFieldValue) -> dict[str, Any]:
        return {
            "id": row.id,
            "chartId": row.chart_id,
            "fieldDefinitionId": row.field_definition_id,
            "value": _load_value(row.value_json),
            "validationResult": _load_value(row.validation_result_json),
        }

    # --------------------------- read --------------------------- #

    @staticmethod
    async def list_values_for_chart(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
    ) -> list[EpcrECustomFieldValue]:
        rows = (
            await session.execute(
                select(EpcrECustomFieldValue)
                .where(
                    and_(
                        EpcrECustomFieldValue.tenant_id == tenant_id,
                        EpcrECustomFieldValue.chart_id == chart_id,
                    )
                )
                .order_by(EpcrECustomFieldValue.field_definition_id)
            )
        ).scalars().all()
        return list(rows)

    # --------------------------- single upsert --------------------------- #

    @staticmethod
    async def upsert_value(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        user_id: str,
        field_key: str,
        value: Any,
        *,
        agency_id: str | None = None,
    ) -> EpcrECustomFieldValue:
        """Validate + upsert a single ECustom value by ``field_key``.

        Resolves the active (non-retired) definition for the field key.
        If ``agency_id`` is supplied, the lookup is scoped further; this
        is recommended when the same key exists across agencies in the
        same tenant.
        """
        definition_query = select(EpcrECustomFieldDefinition).where(
            and_(
                EpcrECustomFieldDefinition.tenant_id == tenant_id,
                EpcrECustomFieldDefinition.field_key == field_key,
                EpcrECustomFieldDefinition.retired.is_(False),
            )
        )
        if agency_id is not None:
            definition_query = definition_query.where(
                EpcrECustomFieldDefinition.agency_id == agency_id
            )
        definition_query = definition_query.order_by(
            EpcrECustomFieldDefinition.version.desc()
        )
        definition = (
            await session.execute(definition_query)
        ).scalars().first()
        if definition is None:
            raise ValidationError(
                [
                    {
                        "field": field_key,
                        "message": (
                            "no active ECustom definition for tenant"
                            + (f"/agency {agency_id}" if agency_id else "")
                        ),
                    }
                ]
            )

        # Resolve current values as context for conditional-rule evaluation.
        current_rows = await ECustomFieldService.list_values_for_chart(
            session, tenant_id, chart_id
        )
        # Build context keyed by field_key.
        defs_by_id: dict[str, EpcrECustomFieldDefinition] = {}
        if current_rows:
            def_ids = {r.field_definition_id for r in current_rows}
            def_rows = (
                await session.execute(
                    select(EpcrECustomFieldDefinition).where(
                        EpcrECustomFieldDefinition.id.in_(def_ids)
                    )
                )
            ).scalars().all()
            defs_by_id = {d.id: d for d in def_rows}
        context: dict[str, Any] = {}
        for row in current_rows:
            d = defs_by_id.get(row.field_definition_id)
            if d is not None:
                context[d.field_key] = _load_value(row.value_json)

        normalized = validate_field_value(
            definition, value, context=context
        )
        validation_result = {"ok": True, "errors": []}

        existing = (
            await session.execute(
                select(EpcrECustomFieldValue).where(
                    and_(
                        EpcrECustomFieldValue.tenant_id == tenant_id,
                        EpcrECustomFieldValue.chart_id == chart_id,
                        EpcrECustomFieldValue.field_definition_id
                        == definition.id,
                    )
                )
            )
        ).scalars().first()

        now = _now()
        if existing is None:
            row = EpcrECustomFieldValue(
                id=str(uuid4()),
                tenant_id=tenant_id,
                chart_id=chart_id,
                field_definition_id=definition.id,
                value_json=_dump_value(normalized),
                validation_result_json=_dump_value(validation_result),
                audit_user_id=user_id,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            ECustomFieldService._audit(
                session,
                tenant_id=tenant_id,
                chart_id=chart_id,
                user_id=user_id,
                action="ecustom_value.created",
                detail={
                    "field_key": definition.field_key,
                    "field_definition_id": definition.id,
                    "before": None,
                    "after": normalized,
                },
                performed_at=now,
            )
        else:
            before = _load_value(existing.value_json)
            if before != normalized:
                existing.value_json = _dump_value(normalized)
                existing.validation_result_json = _dump_value(
                    validation_result
                )
                existing.audit_user_id = user_id
                existing.updated_at = now
                ECustomFieldService._audit(
                    session,
                    tenant_id=tenant_id,
                    chart_id=chart_id,
                    user_id=user_id,
                    action="ecustom_value.updated",
                    detail={
                        "field_key": definition.field_key,
                        "field_definition_id": definition.id,
                        "before": before,
                        "after": normalized,
                    },
                    performed_at=now,
                )
            row = existing

        await session.flush()
        return row

    # --------------------------- bulk replace --------------------------- #

    @staticmethod
    async def replace_for_chart(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        user_id: str,
        agency_id: str,
        values: dict[str, Any] | list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        """Reconcile a chart's ECustom values against an inbound payload.

        ``values`` may be:

        - a mapping of ``field_key -> raw_value``, or
        - a list of ``{"fieldKey": ..., "value": ...}`` items.

        Validates all entries up-front. Any failure raises a single
        :class:`ValidationError` aggregating all errors; no rows mutate.

        Audits each diff row via :class:`EpcrAuditLog` with action
        ``ecustom_value.created`` / ``ecustom_value.updated`` /
        ``ecustom_value.deleted``.
        """
        payload_map: dict[str, Any] = {}
        if values is None:
            payload_map = {}
        elif isinstance(values, dict):
            payload_map = dict(values)
        elif isinstance(values, list):
            for idx, item in enumerate(values):
                if not isinstance(item, dict):
                    raise ValidationError(
                        [
                            {
                                "field": f"ecustom_values[{idx}]",
                                "message": "must be an object",
                            }
                        ]
                    )
                key = item.get("fieldKey") or item.get("field_key")
                if not isinstance(key, str) or not key:
                    raise ValidationError(
                        [
                            {
                                "field": f"ecustom_values[{idx}].fieldKey",
                                "message": "is required",
                            }
                        ]
                    )
                payload_map[key] = item.get("value")
        else:
            raise ValidationError(
                [
                    {
                        "field": "ecustom_values",
                        "message": "must be a mapping or a list",
                    }
                ]
            )

        definitions = await ECustomFieldService.list_definitions(
            session, tenant_id, agency_id
        )
        latest_by_key: dict[str, EpcrECustomFieldDefinition] = {}
        for d in definitions:
            existing = latest_by_key.get(d.field_key)
            if existing is None or d.version >= existing.version:
                latest_by_key[d.field_key] = d

        # First pass: validate every supplied field key.
        normalized_by_key: dict[str, Any] = {}
        all_errors: list[dict[str, str]] = []
        for key, raw in payload_map.items():
            definition = latest_by_key.get(key)
            if definition is None:
                all_errors.append(
                    {
                        "field": key,
                        "message": "no active ECustom definition for key",
                    }
                )
                continue
            try:
                normalized_by_key[key] = validate_field_value(
                    definition, raw, context=payload_map
                )
            except ValidationError as exc:
                all_errors.extend(exc.errors)

        # Second pass: enforce required + conditional-required for defs
        # not present in payload.
        for key, definition in latest_by_key.items():
            if key in payload_map:
                continue
            try:
                validate_field_value(
                    definition, None, context=payload_map
                )
            except ValidationError as exc:
                all_errors.extend(exc.errors)

        if all_errors:
            raise ValidationError(all_errors)

        existing_rows = await ECustomFieldService.list_values_for_chart(
            session, tenant_id, chart_id
        )
        existing_by_def_id: dict[str, EpcrECustomFieldValue] = {
            r.field_definition_id: r for r in existing_rows
        }

        now = _now()
        seen_def_ids: set[str] = set()

        for key, normalized in normalized_by_key.items():
            definition = latest_by_key[key]
            seen_def_ids.add(definition.id)
            existing = existing_by_def_id.get(definition.id)
            validation_result = {"ok": True, "errors": []}
            if existing is None:
                row = EpcrECustomFieldValue(
                    id=str(uuid4()),
                    tenant_id=tenant_id,
                    chart_id=chart_id,
                    field_definition_id=definition.id,
                    value_json=_dump_value(normalized),
                    validation_result_json=_dump_value(validation_result),
                    audit_user_id=user_id,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
                ECustomFieldService._audit(
                    session,
                    tenant_id=tenant_id,
                    chart_id=chart_id,
                    user_id=user_id,
                    action="ecustom_value.created",
                    detail={
                        "field_key": key,
                        "field_definition_id": definition.id,
                        "before": None,
                        "after": normalized,
                    },
                    performed_at=now,
                )
            else:
                before = _load_value(existing.value_json)
                if before != normalized:
                    existing.value_json = _dump_value(normalized)
                    existing.validation_result_json = _dump_value(
                        validation_result
                    )
                    existing.audit_user_id = user_id
                    existing.updated_at = now
                    ECustomFieldService._audit(
                        session,
                        tenant_id=tenant_id,
                        chart_id=chart_id,
                        user_id=user_id,
                        action="ecustom_value.updated",
                        detail={
                            "field_key": key,
                            "field_definition_id": definition.id,
                            "before": before,
                            "after": normalized,
                        },
                        performed_at=now,
                    )

        # Hard-delete any existing row whose definition was not present
        # in the inbound payload — these tables have no soft-delete
        # column; audit captures the prior state for replay.
        defs_by_id = {d.id: d for d in latest_by_key.values()}
        for def_id, row in existing_by_def_id.items():
            if def_id in seen_def_ids:
                continue
            before = _load_value(row.value_json)
            key = defs_by_id[def_id].field_key if def_id in defs_by_id else None
            ECustomFieldService._audit(
                session,
                tenant_id=tenant_id,
                chart_id=chart_id,
                user_id=user_id,
                action="ecustom_value.deleted",
                detail={
                    "field_key": key,
                    "field_definition_id": def_id,
                    "before": before,
                    "after": None,
                },
                performed_at=now,
            )
            await session.delete(row)

        await session.flush()
        refreshed = await ECustomFieldService.list_values_for_chart(
            session, tenant_id, chart_id
        )
        return [ECustomFieldService.serialize_value(r) for r in refreshed]

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


__all__ = [
    "ECustomFieldService",
    "validate_against_definition",
]
