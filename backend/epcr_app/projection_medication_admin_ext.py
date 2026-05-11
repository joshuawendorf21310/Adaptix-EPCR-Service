"""Projection: eMedications-additions -> NEMSIS field-value ledger.

Bridges the per-medication-row extension tables
(:class:`MedicationAdminExt` 1:1 and :class:`MedicationComplication`
1:M) to the registry-driven NEMSIS export ledger.

Each populated NEMSIS-additive scalar on the extension row produces one
``NemsisFieldValue`` ledger row keyed by ``occurrence_id =
medication_admin_id`` so the export builder can correlate every
eMedications scalar back to its parent ``MedicationAdministration``.

eMedications.12 (Medication Authorizing Physician) is a structured
name. It is emitted as a single ledger row at the
``MedicationAuthorizingPhysicianGroup`` group path with attributes
carrying the individual ``lastName`` and ``firstName`` parts, and a
human-readable ``"Last, First"`` value for grep-friendliness.

eMedications.08 (Medication Complication) is a 1:M repeating group;
each complication row produces one ledger row whose ``occurrence_id``
is ``"<medication_admin_id>-comp-<sequence>"`` to keep occurrences
distinct.

Columns/codes that are still ``None`` are NOT projected (they remain
absent from the export); the chart-finalization gate is responsible
for blocking finalization when a Required-at-National element is
missing.

The projector is idempotent: invoking it multiple times for the same
medication upserts by (element_number, group_path, occurrence_id) per
the field-value service contract.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.services_medication_admin_ext import (
    MedicationAdminExtService,
    _EXT_FIELDS,
)
from epcr_app.services_nemsis_field_values import (
    FieldValuePayload,
    NemsisFieldValueService,
)


SECTION = "eMedications"
GROUP_MED = "eMedications.MedicationGroup"
GROUP_PHYSICIAN = "eMedications.MedicationAuthorizingPhysicianGroup"


# (column_name, element_number, NEMSIS element name) for scalar projections.
# eMedications.12 is handled separately because it is a structured name.
_SCALAR_BINDING: list[tuple[str, str, str]] = [
    (
        "prior_to_ems_indicator_code",
        "eMedications.02",
        "Medication Administered Prior to this Unit's EMS Care Indicator",
    ),
    (
        "ems_professional_type_code",
        "eMedications.10",
        "EMS Professional Type Providing Medication",
    ),
    (
        "authorization_code",
        "eMedications.11",
        "Medication Authorization",
    ),
    (
        "by_another_unit_indicator_code",
        "eMedications.13",
        "Medication Administered by Another Unit Indicator",
    ),
]

# Sanity guard: the scalar binding plus the physician-name pair must
# cover every NEMSIS-additive column declared on the extension model.
_BOUND_COLUMNS = {column for column, _, _ in _SCALAR_BINDING} | {
    "authorizing_physician_last_name",
    "authorizing_physician_first_name",
}
assert _BOUND_COLUMNS == set(_EXT_FIELDS), (
    "projection_medication_admin_ext binding drift: missing="
    f"{set(_EXT_FIELDS) - _BOUND_COLUMNS}, "
    f"extra={_BOUND_COLUMNS - set(_EXT_FIELDS)}"
)


def _payloads_from_ext(
    medication_admin_id: str,
    ext: dict[str, Any],
    user_id: str | None,
) -> list[FieldValuePayload]:
    payloads: list[FieldValuePayload] = []
    for column, element_number, element_name in _SCALAR_BINDING:
        raw = ext.get(column)
        if raw is None or raw == "":
            continue
        payloads.append(
            FieldValuePayload(
                section=SECTION,
                element_number=element_number,
                element_name=element_name,
                value=raw,
                group_path=GROUP_MED,
                occurrence_id=medication_admin_id,
                sequence_index=0,
                attributes={},
                source="manual",
                validation_status="unvalidated",
                validation_issues=[],
                user_id=user_id,
            )
        )

    last = ext.get("authorizing_physician_last_name")
    first = ext.get("authorizing_physician_first_name")
    if last or first:
        # Emit one structured name ledger row; pragmatic dual surface so
        # downstream consumers can either parse attributes or read the
        # concatenated value.
        concatenated = ", ".join(p for p in (last or "", first or "") if p).strip(", ")
        payloads.append(
            FieldValuePayload(
                section=SECTION,
                element_number="eMedications.12",
                element_name="Medication Authorizing Physician",
                value=concatenated,
                group_path=GROUP_PHYSICIAN,
                occurrence_id=medication_admin_id,
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
    medication_admin_id: str,
    complications: list[dict[str, Any]],
    user_id: str | None,
) -> list[FieldValuePayload]:
    payloads: list[FieldValuePayload] = []
    for comp in complications:
        code = comp.get("complication_code")
        if not code:
            continue
        seq = int(comp.get("sequence_index") or 0)
        payloads.append(
            FieldValuePayload(
                section=SECTION,
                element_number="eMedications.08",
                element_name="Medication Complication",
                value=code,
                group_path=GROUP_MED,
                occurrence_id=f"{medication_admin_id}-comp-{seq}",
                sequence_index=seq,
                attributes={},
                source="manual",
                validation_status="unvalidated",
                validation_issues=[],
                user_id=user_id,
            )
        )
    return payloads


async def project_medication_admin_ext(
    session: AsyncSession,
    *,
    tenant_id: str,
    chart_id: str,
    medication_admin_id: str,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    """Project the persisted extension + complications to the ledger.

    Reads the ``MedicationAdminExt`` row and any ``MedicationComplication``
    rows for the given medication administration, then upserts one
    ``NemsisFieldValue`` row per populated NEMSIS element. Returns the
    list of upserted ledger rows for observability/testing.

    No-op (returns ``[]``) when neither extension nor complications
    exist yet; the gate decides whether absence is acceptable.
    """
    record = await MedicationAdminExtService.get(
        session,
        tenant_id=tenant_id,
        chart_id=chart_id,
        medication_admin_id=medication_admin_id,
    )
    if record is None:
        return []

    payloads: list[FieldValuePayload] = []
    if record.get("ext"):
        payloads.extend(
            _payloads_from_ext(medication_admin_id, record["ext"], user_id)
        )
    payloads.extend(
        _payloads_from_complications(
            medication_admin_id, record.get("complications", []), user_id
        )
    )
    if not payloads:
        return []
    return await NemsisFieldValueService.bulk_save(
        session, tenant_id=tenant_id, chart_id=chart_id, payloads=payloads
    )


__all__ = [
    "project_medication_admin_ext",
    "SECTION",
    "GROUP_MED",
    "GROUP_PHYSICIAN",
    "_SCALAR_BINDING",
]
