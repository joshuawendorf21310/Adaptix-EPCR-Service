"""Projection: intervention NEMSIS extension -> NEMSIS field-value ledger.

Bridges :class:`InterventionNemsisExt` and :class:`InterventionComplication`
to the registry-driven export path. The intervention id is used as the
``occurrence_id`` for scalar fields so that multiple interventions on a
chart project to distinct ledger occurrences inside the
``eProcedures.ProcedureGroup``. The authorizing physician composite is
emitted under ``eProcedures.ProcedureAuthorizingPhysicianGroup``.
Complications use a derived occurrence id of
``f"{intervention_id}-comp-{sequence_index}"``.

The projector is idempotent: invoking it multiple times for the same
intervention upserts by ``(element_number, group_path, occurrence_id)``
per the service contract.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.services_intervention_ext import (
    InterventionExtService,
    _EXT_SCALAR_FIELDS,
)
from epcr_app.services_nemsis_field_values import (
    FieldValuePayload,
    NemsisFieldValueService,
)


SECTION = "eProcedures"
PROCEDURE_GROUP_PATH = "eProcedures.ProcedureGroup"
PHYSICIAN_GROUP_PATH = "eProcedures.ProcedureAuthorizingPhysicianGroup"


# (column_name, element_number, NEMSIS element name)
_ELEMENT_BINDING: list[tuple[str, str, str]] = [
    ("prior_to_ems_indicator_code", "eProcedures.02", "Prior to EMS Care Indicator"),
    ("number_of_attempts", "eProcedures.05", "Number of Procedure Attempts"),
    ("procedure_successful_code", "eProcedures.06", "Procedure Successful"),
    ("ems_professional_type_code", "eProcedures.10", "Type of EMS Professional Performing Procedure"),
    ("authorization_code", "eProcedures.11", "Authorization for Procedure"),
    ("by_another_unit_indicator_code", "eProcedures.13", "Procedure Performed Prior to this Unit's EMS Care"),
    ("pre_existing_indicator_code", "eProcedures.14", "Pre-Existing Procedure"),
]

# Sanity guard: the scalar binding must cover every scalar field except
# the authorizing physician name pair which is emitted as a composite.
_BINDING_COLUMNS = {column for column, _, _ in _ELEMENT_BINDING}
_PHYSICIAN_COLUMNS = {
    "authorizing_physician_last_name",
    "authorizing_physician_first_name",
}
assert _BINDING_COLUMNS | _PHYSICIAN_COLUMNS == set(_EXT_SCALAR_FIELDS), (
    "projection_intervention_ext binding drift: scalar fields="
    f"{set(_EXT_SCALAR_FIELDS)}, "
    f"covered={_BINDING_COLUMNS | _PHYSICIAN_COLUMNS}"
)


def _payloads_from_ext(
    record: dict[str, Any],
    *,
    intervention_id: str,
    user_id: str | None,
) -> list[FieldValuePayload]:
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
                value=raw,
                group_path=PROCEDURE_GROUP_PATH,
                occurrence_id=intervention_id,
                sequence_index=0,
                attributes={},
                source="manual",
                validation_status="unvalidated",
                validation_issues=[],
                user_id=user_id,
            )
        )

    last = record.get("authorizing_physician_last_name")
    first = record.get("authorizing_physician_first_name")
    if last or first:
        composite_value = ", ".join(
            part for part in [last or "", first or ""] if part
        )
        payloads.append(
            FieldValuePayload(
                section=SECTION,
                element_number="eProcedures.12",
                element_name="Authorizing Physician",
                value=composite_value,
                group_path=PHYSICIAN_GROUP_PATH,
                occurrence_id=intervention_id,
                sequence_index=0,
                attributes={
                    "lastName": last or "",
                    "firstName": first or "",
                },
                source="manual",
                validation_status="unvalidated",
                validation_issues=[],
                user_id=user_id,
            )
        )

    return payloads


def _payloads_from_complications(
    complications: list[dict[str, Any]],
    *,
    intervention_id: str,
    user_id: str | None,
) -> list[FieldValuePayload]:
    payloads: list[FieldValuePayload] = []
    for comp in complications:
        seq = int(comp.get("sequence_index", 0) or 0)
        payloads.append(
            FieldValuePayload(
                section=SECTION,
                element_number="eProcedures.07",
                element_name="Procedure Complication",
                value=comp.get("complication_code"),
                group_path=PROCEDURE_GROUP_PATH,
                occurrence_id=f"{intervention_id}-comp-{seq}",
                sequence_index=seq,
                attributes={},
                source="manual",
                validation_status="unvalidated",
                validation_issues=[],
                user_id=user_id,
            )
        )
    return payloads


async def project_intervention_ext(
    session: AsyncSession,
    *,
    tenant_id: str,
    chart_id: str,
    intervention_id: str,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    """Project the ext + complications to the NEMSIS field-values ledger.

    Returns the list of upserted ledger rows for observability/testing.
    The projection is a no-op (returns ``[]``) when neither the ext row
    nor any complication exists yet; the chart-finalization gate decides
    whether absence is acceptable for Required-at-National fields.
    """
    ext = await InterventionExtService.get(
        session, tenant_id=tenant_id, intervention_id=intervention_id
    )
    complications = await InterventionExtService.list_complications(
        session, tenant_id=tenant_id, intervention_id=intervention_id
    )

    payloads: list[FieldValuePayload] = []
    if ext is not None:
        payloads.extend(
            _payloads_from_ext(ext, intervention_id=intervention_id, user_id=user_id)
        )
    payloads.extend(
        _payloads_from_complications(
            complications, intervention_id=intervention_id, user_id=user_id
        )
    )
    if not payloads:
        return []
    return await NemsisFieldValueService.bulk_save(
        session, tenant_id=tenant_id, chart_id=chart_id, payloads=payloads
    )


__all__ = [
    "project_intervention_ext",
    "SECTION",
    "PROCEDURE_GROUP_PATH",
    "PHYSICIAN_GROUP_PATH",
    "_ELEMENT_BINDING",
]
