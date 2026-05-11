"""NEMSIS eScene service: tenant-scoped upsert/read for chart scene meta
and CRUD for the Other-EMS-or-Public-Safety-Agencies repeating group.

Every read and write is filtered by ``tenant_id`` at the SQL layer so no
cross-tenant escape is possible. The service is intentionally thin: it
persists raw coded values; conversion to NEMSIS XML is the projection
layer's job (:mod:`projection_chart_scene`).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models_chart_scene import ChartScene, ChartSceneOtherAgency


# Scalar fields on the 1:1 ChartScene (all NEMSIS-bound).
_SCENE_FIELDS: tuple[str, ...] = (
    "first_ems_unit_indicator_code",
    "initial_responder_arrived_at",
    "number_of_patients",
    "mci_indicator_code",
    "mci_triage_classification_code",
    "incident_location_type_code",
    "incident_facility_code",
    "scene_lat",
    "scene_long",
    "scene_usng",
    "incident_facility_name",
    "mile_post_or_major_roadway",
    "incident_street_address",
    "incident_apartment",
    "incident_city",
    "incident_state",
    "incident_zip",
    "scene_cross_street",
    "incident_county",
    "incident_country",
    "incident_census_tract",
)

# NEMSIS-bound fields on the 1:M ChartSceneOtherAgency (excluding
# sequence_index, which is ordering metadata not a NEMSIS element).
_AGENCY_FIELDS: tuple[str, ...] = (
    "agency_id",
    "other_service_type_code",
    "first_to_provide_patient_care_indicator",
    "patient_care_handoff_code",
)


class ChartSceneError(Exception):
    """Raised on caller errors that are safe to surface to the API layer."""

    def __init__(self, status_code: int, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = {"message": message, **extra}


@dataclass
class ChartScenePayload:
    """Caller-side payload for upsert.

    All fields are optional. Any field omitted (left as ``None``) retains
    its current persisted value. To explicitly clear a field, use
    :meth:`ChartSceneService.clear_field`.
    """

    first_ems_unit_indicator_code: str | None = None
    initial_responder_arrived_at: datetime | None = None
    number_of_patients: int | None = None
    mci_indicator_code: str | None = None
    mci_triage_classification_code: str | None = None
    incident_location_type_code: str | None = None
    incident_facility_code: str | None = None
    scene_lat: float | None = None
    scene_long: float | None = None
    scene_usng: str | None = None
    incident_facility_name: str | None = None
    mile_post_or_major_roadway: str | None = None
    incident_street_address: str | None = None
    incident_apartment: str | None = None
    incident_city: str | None = None
    incident_state: str | None = None
    incident_zip: str | None = None
    scene_cross_street: str | None = None
    incident_county: str | None = None
    incident_country: str | None = None
    incident_census_tract: str | None = None


@dataclass
class ChartSceneOtherAgencyPayload:
    """Caller-side payload for creating one other-agency row.

    ``agency_id`` and ``other_service_type_code`` are required because
    eScene.03/.04 are Required-at-National. The handoff indicator and
    care-handoff code are optional and may be filled in later via PATCH.
    """

    agency_id: str
    other_service_type_code: str
    first_to_provide_patient_care_indicator: str | None = None
    patient_care_handoff_code: str | None = None
    sequence_index: int = 0


def _serialize_scene(row: ChartScene) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "chart_id": row.chart_id,
    }
    for field in _SCENE_FIELDS:
        value = getattr(row, field)
        if isinstance(value, datetime):
            out[field] = value.isoformat()
        else:
            out[field] = value
    out["version"] = row.version
    out["created_at"] = row.created_at.isoformat() if row.created_at else None
    out["updated_at"] = row.updated_at.isoformat() if row.updated_at else None
    out["deleted_at"] = row.deleted_at.isoformat() if row.deleted_at else None
    return out


def _serialize_agency(row: ChartSceneOtherAgency) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "chart_id": row.chart_id,
        "agency_id": row.agency_id,
        "other_service_type_code": row.other_service_type_code,
        "first_to_provide_patient_care_indicator": row.first_to_provide_patient_care_indicator,
        "patient_care_handoff_code": row.patient_care_handoff_code,
        "sequence_index": row.sequence_index,
        "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
    }


class ChartSceneService:
    """Tenant-scoped persistence for the chart scene 1:1 meta."""

    @staticmethod
    async def get(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
    ) -> dict[str, Any] | None:
        if not tenant_id:
            raise ChartSceneError(400, "tenant_id is required")
        if not chart_id:
            raise ChartSceneError(400, "chart_id is required")

        stmt = select(ChartScene).where(
            ChartScene.tenant_id == tenant_id,
            ChartScene.chart_id == chart_id,
            ChartScene.deleted_at.is_(None),
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        return _serialize_scene(row) if row else None

    @staticmethod
    async def upsert(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        payload: ChartScenePayload,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if not tenant_id:
            raise ChartSceneError(400, "tenant_id is required")
        if not chart_id:
            raise ChartSceneError(400, "chart_id is required")

        now = datetime.now(UTC)

        stmt = select(ChartScene).where(
            ChartScene.tenant_id == tenant_id,
            ChartScene.chart_id == chart_id,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()

        if row is None:
            row = ChartScene(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                chart_id=chart_id,
                created_by_user_id=user_id,
                updated_by_user_id=user_id,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            for field in _SCENE_FIELDS:
                value = getattr(payload, field)
                setattr(row, field, value)
            # eScene.22 country defaults to "US" when not supplied.
            if row.incident_country is None:
                row.incident_country = "US"
            session.add(row)
        else:
            for field in _SCENE_FIELDS:
                value = getattr(payload, field)
                # Only overwrite when the caller actually supplied a
                # value. ``None`` retains the existing value so partial
                # updates work; explicit clearing is a separate endpoint.
                if value is not None:
                    setattr(row, field, value)
            row.updated_by_user_id = user_id
            row.updated_at = now
            row.deleted_at = None
            row.version = (row.version or 1) + 1

        await session.flush()
        return _serialize_scene(row)

    @staticmethod
    async def clear_field(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        field: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Explicitly set one column to NULL.

        Reserved for the rare correction path where a previously
        recorded scene value was wrong and must be erased rather than
        overwritten. Audit trail lives in :class:`Chart` versioning.
        """
        if field not in _SCENE_FIELDS:
            raise ChartSceneError(
                400, "unknown field", field=field, allowed=list(_SCENE_FIELDS)
            )
        stmt = select(ChartScene).where(
            ChartScene.tenant_id == tenant_id,
            ChartScene.chart_id == chart_id,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise ChartSceneError(404, "chart_scene not found", chart_id=chart_id)
        setattr(row, field, None)
        row.updated_at = datetime.now(UTC)
        row.updated_by_user_id = user_id
        row.version = (row.version or 1) + 1
        await session.flush()
        return _serialize_scene(row)


class ChartSceneOtherAgencyService:
    """Tenant-scoped CRUD for the eScene other-agencies 1:M group."""

    @staticmethod
    async def list_for_chart(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        if not tenant_id:
            raise ChartSceneError(400, "tenant_id is required")
        if not chart_id:
            raise ChartSceneError(400, "chart_id is required")

        stmt = select(ChartSceneOtherAgency).where(
            ChartSceneOtherAgency.tenant_id == tenant_id,
            ChartSceneOtherAgency.chart_id == chart_id,
        )
        if not include_deleted:
            stmt = stmt.where(ChartSceneOtherAgency.deleted_at.is_(None))
        stmt = stmt.order_by(
            ChartSceneOtherAgency.sequence_index,
            ChartSceneOtherAgency.agency_id,
        )
        rows = (await session.execute(stmt)).scalars().all()
        return [_serialize_agency(r) for r in rows]

    @staticmethod
    async def add(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        payload: ChartSceneOtherAgencyPayload,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if not tenant_id:
            raise ChartSceneError(400, "tenant_id is required")
        if not chart_id:
            raise ChartSceneError(400, "chart_id is required")
        if not payload.agency_id:
            raise ChartSceneError(400, "agency_id is required")
        if not payload.other_service_type_code:
            raise ChartSceneError(400, "other_service_type_code is required")
        if payload.sequence_index is None or payload.sequence_index < 0:
            raise ChartSceneError(400, "sequence_index must be >= 0")

        now = datetime.now(UTC)

        # Reject duplicates (same agency twice on same chart). Reuse the
        # row if it was previously soft-deleted, otherwise reject.
        stmt = select(ChartSceneOtherAgency).where(
            ChartSceneOtherAgency.tenant_id == tenant_id,
            ChartSceneOtherAgency.chart_id == chart_id,
            ChartSceneOtherAgency.agency_id == payload.agency_id,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is not None and existing.deleted_at is None:
            raise ChartSceneError(
                409,
                "other agency already on chart",
                agency_id=payload.agency_id,
            )
        if existing is not None and existing.deleted_at is not None:
            existing.other_service_type_code = payload.other_service_type_code
            existing.first_to_provide_patient_care_indicator = (
                payload.first_to_provide_patient_care_indicator
            )
            existing.patient_care_handoff_code = payload.patient_care_handoff_code
            existing.sequence_index = payload.sequence_index
            existing.updated_by_user_id = user_id
            existing.updated_at = now
            existing.deleted_at = None
            existing.version = (existing.version or 1) + 1
            row = existing
        else:
            row = ChartSceneOtherAgency(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                chart_id=chart_id,
                agency_id=payload.agency_id,
                other_service_type_code=payload.other_service_type_code,
                first_to_provide_patient_care_indicator=(
                    payload.first_to_provide_patient_care_indicator
                ),
                patient_care_handoff_code=payload.patient_care_handoff_code,
                sequence_index=payload.sequence_index,
                created_by_user_id=user_id,
                updated_by_user_id=user_id,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            session.add(row)

        await session.flush()
        return _serialize_agency(row)

    @staticmethod
    async def soft_delete(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        row_id: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if not tenant_id:
            raise ChartSceneError(400, "tenant_id is required")
        if not chart_id:
            raise ChartSceneError(400, "chart_id is required")
        if not row_id:
            raise ChartSceneError(400, "row_id is required")

        stmt = select(ChartSceneOtherAgency).where(
            ChartSceneOtherAgency.tenant_id == tenant_id,
            ChartSceneOtherAgency.chart_id == chart_id,
            ChartSceneOtherAgency.id == row_id,
            ChartSceneOtherAgency.deleted_at.is_(None),
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise ChartSceneError(
                404, "chart_scene_other_agency not found", row_id=row_id
            )

        now = datetime.now(UTC)
        row.deleted_at = now
        row.updated_at = now
        row.updated_by_user_id = user_id
        row.version = (row.version or 1) + 1
        await session.flush()
        return _serialize_agency(row)


__all__ = [
    "ChartSceneService",
    "ChartSceneOtherAgencyService",
    "ChartScenePayload",
    "ChartSceneOtherAgencyPayload",
    "ChartSceneError",
    "_SCENE_FIELDS",
    "_AGENCY_FIELDS",
]
