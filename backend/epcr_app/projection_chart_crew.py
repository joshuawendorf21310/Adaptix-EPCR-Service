"""Projection: :class:`ChartCrewMember` -> NEMSIS field-value ledger rows.

This module is the bridge between the domain model and the
registry-driven export path. Every crew row produces three
``NemsisFieldValue`` rows (one per eCrew.01/02/03) that share the crew
row's UUID as ``occurrence_id`` so the NEMSIS dataset XML builder can
reassemble each crew member as one repeating-group occurrence.

The projector is idempotent: invoking it multiple times for the same
chart upserts by ``(element_number, group_path, occurrence_id)`` per
the service contract.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.services_chart_crew import ChartCrewService
from epcr_app.services_nemsis_field_values import (
    FieldValuePayload,
    NemsisFieldValueService,
)


SECTION = "eCrew"


# (column_name, element_number, NEMSIS element name)
_ELEMENT_BINDING: list[tuple[str, str, str]] = [
    ("crew_member_id", "eCrew.01", "Crew Member ID"),
    ("crew_member_level_code", "eCrew.02", "Crew Member Level"),
    ("crew_member_response_role_code", "eCrew.03", "Crew Member Response Role"),
]


def _payloads_from_record(
    record: dict[str, Any], user_id: str | None
) -> list[FieldValuePayload]:
    occurrence_id = str(record["id"])
    sequence_index = int(record.get("sequence_index") or 0)
    payloads: list[FieldValuePayload] = []
    for column, element_number, element_name in _ELEMENT_BINDING:
        raw = record.get(column)
        if raw is None:
            continue
        payloads.append(
            FieldValuePayload(
                section=SECTION,
                element_number=element_number,
                element_name=element_name,
                value=str(raw),
                group_path="",
                occurrence_id=occurrence_id,
                sequence_index=sequence_index,
                attributes={},
                source="manual",
                validation_status="unvalidated",
                validation_issues=[],
                user_id=user_id,
            )
        )
    return payloads


async def project_chart_crew(
    session: AsyncSession,
    *,
    tenant_id: str,
    chart_id: str,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    """Project all persisted :class:`ChartCrewMember` rows to the ledger.

    Reads every non-deleted crew row for the chart, then upserts three
    ``NemsisFieldValue`` rows per crew member (one per eCrew.01/02/03)
    sharing the crew row's UUID as ``occurrence_id``. Returns the list
    of upserted ledger rows for observability/testing.

    The projection is a no-op (returns ``[]``) when no crew rows exist
    yet; the gate decides whether absence is acceptable.
    """
    records = await ChartCrewService.list_for_chart(
        session, tenant_id=tenant_id, chart_id=chart_id
    )
    if not records:
        return []
    payloads: list[FieldValuePayload] = []
    for record in records:
        payloads.extend(_payloads_from_record(record, user_id))
    if not payloads:
        return []
    return await NemsisFieldValueService.bulk_save(
        session, tenant_id=tenant_id, chart_id=chart_id, payloads=payloads
    )


__all__ = ["project_chart_crew", "SECTION", "_ELEMENT_BINDING"]
