"""Projection: :class:`ChartDispatch` -> NEMSIS field-value ledger rows.

This module is the bridge between the domain model and the
registry-driven export path. Every domain dispatch column produces one
``NemsisFieldValue`` row whose ``element_number`` is the NEMSIS v3.5.1
canonical element ID and whose ``value`` is the coded string the
NEMSIS schema expects. Columns that are still ``None`` are NOT projected
(they remain absent from the export); the chart-finalization gate is
responsible for blocking finalization when a Mandatory/Required-at-
National value is missing.

The projector is idempotent: invoking it multiple times for the same
chart upserts by ``(element_number, group_path, occurrence_id)`` per the
service contract.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.services_chart_dispatch import ChartDispatchService, _DISPATCH_FIELDS
from epcr_app.services_nemsis_field_values import (
    FieldValuePayload,
    NemsisFieldValueService,
)


SECTION = "eDispatch"


# (column_name, element_number, NEMSIS element name)
_ELEMENT_BINDING: list[tuple[str, str, str]] = [
    ("dispatch_reason_code", "eDispatch.01", "Dispatch Reason"),
    ("emd_performed_code", "eDispatch.02", "EMD Performed"),
    ("emd_determinant_code", "eDispatch.03", "EMD Determinant Code"),
    ("dispatch_center_id", "eDispatch.04", "Dispatch Center Name or ID"),
    ("dispatch_priority_code", "eDispatch.05", "Dispatch Priority (Patient Acuity)"),
    ("cad_record_id", "eDispatch.06", "Unit Dispatched CAD Record ID"),
]

# Sanity guard: the binding must cover every column declared on the
# model so we never silently drop a column from the export.
_BINDING_COLUMNS = {column for column, _, _ in _ELEMENT_BINDING}
assert _BINDING_COLUMNS == set(_DISPATCH_FIELDS), (
    "projection_chart_dispatch binding drift: missing="
    f"{set(_DISPATCH_FIELDS) - _BINDING_COLUMNS}, "
    f"extra={_BINDING_COLUMNS - set(_DISPATCH_FIELDS)}"
)


def _fmt(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _payloads_from_record(record: dict[str, Any], user_id: str | None) -> list[FieldValuePayload]:
    payloads: list[FieldValuePayload] = []
    for column, element_number, element_name in _ELEMENT_BINDING:
        raw = record.get(column)
        formatted = _fmt(raw)
        if formatted is None:
            continue
        payloads.append(
            FieldValuePayload(
                section=SECTION,
                element_number=element_number,
                element_name=element_name,
                value=formatted,
                group_path="",
                occurrence_id="",
                sequence_index=0,
                attributes={},
                source="manual",
                validation_status="unvalidated",
                validation_issues=[],
                user_id=user_id,
            )
        )
    return payloads


async def project_chart_dispatch(
    session: AsyncSession,
    *,
    tenant_id: str,
    chart_id: str,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    """Project the persisted :class:`ChartDispatch` row to the field-values ledger.

    Reads ``ChartDispatch`` for the given chart, then upserts one
    ``NemsisFieldValue`` row per populated column. Returns the list of
    upserted ledger rows for observability/testing.

    The projection is a no-op (returns ``[]``) when no ``ChartDispatch``
    row exists yet; the gate decides whether absence is acceptable.
    """
    record = await ChartDispatchService.get(
        session, tenant_id=tenant_id, chart_id=chart_id
    )
    if record is None:
        return []
    payloads = _payloads_from_record(record, user_id)
    if not payloads:
        return []
    return await NemsisFieldValueService.bulk_save(
        session, tenant_id=tenant_id, chart_id=chart_id, payloads=payloads
    )


__all__ = ["project_chart_dispatch", "SECTION"]
