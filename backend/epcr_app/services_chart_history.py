"""NEMSIS eHistory service: tenant-scoped CRUD for chart medical history.

Every read and write is filtered by ``tenant_id`` at the SQL layer so no
cross-tenant escape is possible. The service is intentionally thin: it
persists raw history rows; conversion to NEMSIS XML is the projection
layer's job (:mod:`projection_chart_history`).

The eHistory aggregate is composed of one 1:1 meta row plus four
1:M child collections (allergies, surgical history, current
medications, immunizations). The service exposes one focused class per
collection so the API layer can compose them without leaking SQL.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models_chart_history import (
    ChartHistoryAllergy,
    ChartHistoryCurrentMedication,
    ChartHistoryImmunization,
    ChartHistoryMeta,
    ChartHistorySurgical,
)


ALLERGY_KINDS: tuple[str, ...] = ("medication", "environmental_food")


_META_LIST_FIELDS: tuple[str, ...] = (
    "barriers_to_care_codes_json",
    "advance_directives_codes_json",
    "medical_history_obtained_from_codes_json",
    "alcohol_drug_use_codes_json",
)

_META_SCALAR_FIELDS: tuple[str, ...] = (
    "practitioner_last_name",
    "practitioner_first_name",
    "practitioner_middle_name",
    "pregnancy_code",
    "last_oral_intake_at",
    "emergency_information_form_code",
)

_META_FIELDS: tuple[str, ...] = _META_LIST_FIELDS + _META_SCALAR_FIELDS


class ChartHistoryError(Exception):
    """Raised on caller errors that are safe to surface to the API layer."""

    def __init__(self, status_code: int, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = {"message": message, **extra}


@dataclass
class ChartHistoryMetaPayload:
    """Caller-side payload for upserting the meta row.

    All fields optional; ``None`` retains the existing value so partial
    updates work. Use the dedicated child endpoints to manage 1:M
    collections (allergies, surgical, medications, immunizations).
    """

    barriers_to_care_codes_json: list[str] | None = None
    advance_directives_codes_json: list[str] | None = None
    medical_history_obtained_from_codes_json: list[str] | None = None
    alcohol_drug_use_codes_json: list[str] | None = None
    practitioner_last_name: str | None = None
    practitioner_first_name: str | None = None
    practitioner_middle_name: str | None = None
    pregnancy_code: str | None = None
    last_oral_intake_at: datetime | None = None
    emergency_information_form_code: str | None = None


@dataclass
class AllergyPayload:
    allergy_kind: str
    allergy_code: str
    allergy_text: str | None = None
    sequence_index: int = 0


@dataclass
class SurgicalPayload:
    condition_code: str
    condition_text: str | None = None
    sequence_index: int = 0


@dataclass
class CurrentMedicationPayload:
    drug_code: str
    dose_value: str | None = None
    dose_unit_code: str | None = None
    route_code: str | None = None
    frequency_code: str | None = None
    sequence_index: int = 0


@dataclass
class ImmunizationPayload:
    immunization_type_code: str
    immunization_year: int | None = None
    sequence_index: int = 0


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _serialize_meta(row: ChartHistoryMeta) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "chart_id": row.chart_id,
        "barriers_to_care_codes_json": row.barriers_to_care_codes_json,
        "advance_directives_codes_json": row.advance_directives_codes_json,
        "medical_history_obtained_from_codes_json": (
            row.medical_history_obtained_from_codes_json
        ),
        "alcohol_drug_use_codes_json": row.alcohol_drug_use_codes_json,
        "practitioner_last_name": row.practitioner_last_name,
        "practitioner_first_name": row.practitioner_first_name,
        "practitioner_middle_name": row.practitioner_middle_name,
        "pregnancy_code": row.pregnancy_code,
        "last_oral_intake_at": _iso(row.last_oral_intake_at),
        "emergency_information_form_code": row.emergency_information_form_code,
        "version": row.version,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "deleted_at": _iso(row.deleted_at),
    }


def _serialize_allergy(row: ChartHistoryAllergy) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "chart_id": row.chart_id,
        "allergy_kind": row.allergy_kind,
        "allergy_code": row.allergy_code,
        "allergy_text": row.allergy_text,
        "sequence_index": row.sequence_index,
        "version": row.version,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "deleted_at": _iso(row.deleted_at),
    }


def _serialize_surgical(row: ChartHistorySurgical) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "chart_id": row.chart_id,
        "condition_code": row.condition_code,
        "condition_text": row.condition_text,
        "sequence_index": row.sequence_index,
        "version": row.version,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "deleted_at": _iso(row.deleted_at),
    }


def _serialize_medication(row: ChartHistoryCurrentMedication) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "chart_id": row.chart_id,
        "drug_code": row.drug_code,
        "dose_value": row.dose_value,
        "dose_unit_code": row.dose_unit_code,
        "route_code": row.route_code,
        "frequency_code": row.frequency_code,
        "sequence_index": row.sequence_index,
        "version": row.version,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "deleted_at": _iso(row.deleted_at),
    }


def _serialize_immunization(row: ChartHistoryImmunization) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "chart_id": row.chart_id,
        "immunization_type_code": row.immunization_type_code,
        "immunization_year": row.immunization_year,
        "sequence_index": row.sequence_index,
        "version": row.version,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "deleted_at": _iso(row.deleted_at),
    }


def _require_tenant_chart(tenant_id: str, chart_id: str) -> None:
    if not tenant_id:
        raise ChartHistoryError(400, "tenant_id is required")
    if not chart_id:
        raise ChartHistoryError(400, "chart_id is required")


class ChartHistoryMetaService:
    """Tenant-scoped persistence for the eHistory single-row meta."""

    @staticmethod
    async def get(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
    ) -> dict[str, Any] | None:
        _require_tenant_chart(tenant_id, chart_id)
        stmt = select(ChartHistoryMeta).where(
            ChartHistoryMeta.tenant_id == tenant_id,
            ChartHistoryMeta.chart_id == chart_id,
            ChartHistoryMeta.deleted_at.is_(None),
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        return _serialize_meta(row) if row else None

    @staticmethod
    async def upsert(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        payload: ChartHistoryMetaPayload,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        _require_tenant_chart(tenant_id, chart_id)

        now = datetime.now(UTC)
        stmt = select(ChartHistoryMeta).where(
            ChartHistoryMeta.tenant_id == tenant_id,
            ChartHistoryMeta.chart_id == chart_id,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()

        if row is None:
            row = ChartHistoryMeta(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                chart_id=chart_id,
                created_by_user_id=user_id,
                updated_by_user_id=user_id,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            for field_name in _META_FIELDS:
                value = getattr(payload, field_name)
                setattr(row, field_name, value)
            session.add(row)
        else:
            for field_name in _META_FIELDS:
                value = getattr(payload, field_name)
                # ``None`` retains the existing value so partial updates
                # are non-destructive. Explicit clearing is reserved for
                # a future correction endpoint.
                if value is not None:
                    setattr(row, field_name, value)
            row.updated_by_user_id = user_id
            row.updated_at = now
            row.deleted_at = None
            row.version = (row.version or 1) + 1

        await session.flush()
        return _serialize_meta(row)


class ChartHistoryAllergyService:
    """Tenant-scoped CRUD for eHistory.06 / eHistory.07 allergies."""

    @staticmethod
    async def list_for_chart(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        _require_tenant_chart(tenant_id, chart_id)
        stmt = select(ChartHistoryAllergy).where(
            ChartHistoryAllergy.tenant_id == tenant_id,
            ChartHistoryAllergy.chart_id == chart_id,
        )
        if not include_deleted:
            stmt = stmt.where(ChartHistoryAllergy.deleted_at.is_(None))
        stmt = stmt.order_by(
            ChartHistoryAllergy.allergy_kind,
            ChartHistoryAllergy.sequence_index,
            ChartHistoryAllergy.allergy_code,
        )
        rows = (await session.execute(stmt)).scalars().all()
        return [_serialize_allergy(r) for r in rows]

    @staticmethod
    async def add(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        payload: AllergyPayload,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        _require_tenant_chart(tenant_id, chart_id)
        if payload.allergy_kind not in ALLERGY_KINDS:
            raise ChartHistoryError(
                400,
                "invalid allergy_kind",
                allowed=list(ALLERGY_KINDS),
                received=payload.allergy_kind,
            )
        if not payload.allergy_code:
            raise ChartHistoryError(400, "allergy_code is required")
        if payload.sequence_index is None or payload.sequence_index < 0:
            raise ChartHistoryError(400, "sequence_index must be >= 0")

        now = datetime.now(UTC)
        stmt = select(ChartHistoryAllergy).where(
            ChartHistoryAllergy.tenant_id == tenant_id,
            ChartHistoryAllergy.chart_id == chart_id,
            ChartHistoryAllergy.allergy_kind == payload.allergy_kind,
            ChartHistoryAllergy.allergy_code == payload.allergy_code,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is not None and existing.deleted_at is None:
            raise ChartHistoryError(
                409,
                "allergy already on chart",
                allergy_kind=payload.allergy_kind,
                allergy_code=payload.allergy_code,
            )
        if existing is not None and existing.deleted_at is not None:
            existing.allergy_text = payload.allergy_text
            existing.sequence_index = payload.sequence_index
            existing.updated_by_user_id = user_id
            existing.updated_at = now
            existing.deleted_at = None
            existing.version = (existing.version or 1) + 1
            row = existing
        else:
            row = ChartHistoryAllergy(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                chart_id=chart_id,
                allergy_kind=payload.allergy_kind,
                allergy_code=payload.allergy_code,
                allergy_text=payload.allergy_text,
                sequence_index=payload.sequence_index,
                created_by_user_id=user_id,
                updated_by_user_id=user_id,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            session.add(row)
        await session.flush()
        return _serialize_allergy(row)

    @staticmethod
    async def soft_delete(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        row_id: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        _require_tenant_chart(tenant_id, chart_id)
        if not row_id:
            raise ChartHistoryError(400, "row_id is required")
        stmt = select(ChartHistoryAllergy).where(
            ChartHistoryAllergy.tenant_id == tenant_id,
            ChartHistoryAllergy.chart_id == chart_id,
            ChartHistoryAllergy.id == row_id,
            ChartHistoryAllergy.deleted_at.is_(None),
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise ChartHistoryError(404, "allergy not found", row_id=row_id)
        now = datetime.now(UTC)
        row.deleted_at = now
        row.updated_at = now
        row.updated_by_user_id = user_id
        row.version = (row.version or 1) + 1
        await session.flush()
        return _serialize_allergy(row)


class ChartHistorySurgicalService:
    """Tenant-scoped CRUD for eHistory.08 medical/surgical history."""

    @staticmethod
    async def list_for_chart(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        _require_tenant_chart(tenant_id, chart_id)
        stmt = select(ChartHistorySurgical).where(
            ChartHistorySurgical.tenant_id == tenant_id,
            ChartHistorySurgical.chart_id == chart_id,
        )
        if not include_deleted:
            stmt = stmt.where(ChartHistorySurgical.deleted_at.is_(None))
        stmt = stmt.order_by(
            ChartHistorySurgical.sequence_index,
            ChartHistorySurgical.condition_code,
        )
        rows = (await session.execute(stmt)).scalars().all()
        return [_serialize_surgical(r) for r in rows]

    @staticmethod
    async def add(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        payload: SurgicalPayload,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        _require_tenant_chart(tenant_id, chart_id)
        if not payload.condition_code:
            raise ChartHistoryError(400, "condition_code is required")
        if payload.sequence_index is None or payload.sequence_index < 0:
            raise ChartHistoryError(400, "sequence_index must be >= 0")

        now = datetime.now(UTC)
        stmt = select(ChartHistorySurgical).where(
            ChartHistorySurgical.tenant_id == tenant_id,
            ChartHistorySurgical.chart_id == chart_id,
            ChartHistorySurgical.condition_code == payload.condition_code,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is not None and existing.deleted_at is None:
            raise ChartHistoryError(
                409,
                "surgical condition already on chart",
                condition_code=payload.condition_code,
            )
        if existing is not None and existing.deleted_at is not None:
            existing.condition_text = payload.condition_text
            existing.sequence_index = payload.sequence_index
            existing.updated_by_user_id = user_id
            existing.updated_at = now
            existing.deleted_at = None
            existing.version = (existing.version or 1) + 1
            row = existing
        else:
            row = ChartHistorySurgical(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                chart_id=chart_id,
                condition_code=payload.condition_code,
                condition_text=payload.condition_text,
                sequence_index=payload.sequence_index,
                created_by_user_id=user_id,
                updated_by_user_id=user_id,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            session.add(row)
        await session.flush()
        return _serialize_surgical(row)

    @staticmethod
    async def soft_delete(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        row_id: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        _require_tenant_chart(tenant_id, chart_id)
        if not row_id:
            raise ChartHistoryError(400, "row_id is required")
        stmt = select(ChartHistorySurgical).where(
            ChartHistorySurgical.tenant_id == tenant_id,
            ChartHistorySurgical.chart_id == chart_id,
            ChartHistorySurgical.id == row_id,
            ChartHistorySurgical.deleted_at.is_(None),
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise ChartHistoryError(404, "surgical not found", row_id=row_id)
        now = datetime.now(UTC)
        row.deleted_at = now
        row.updated_at = now
        row.updated_by_user_id = user_id
        row.version = (row.version or 1) + 1
        await session.flush()
        return _serialize_surgical(row)


class ChartHistoryCurrentMedicationService:
    """Tenant-scoped CRUD for eHistory.12/13/14/15/20 current medications."""

    @staticmethod
    async def list_for_chart(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        _require_tenant_chart(tenant_id, chart_id)
        stmt = select(ChartHistoryCurrentMedication).where(
            ChartHistoryCurrentMedication.tenant_id == tenant_id,
            ChartHistoryCurrentMedication.chart_id == chart_id,
        )
        if not include_deleted:
            stmt = stmt.where(ChartHistoryCurrentMedication.deleted_at.is_(None))
        stmt = stmt.order_by(
            ChartHistoryCurrentMedication.sequence_index,
            ChartHistoryCurrentMedication.drug_code,
        )
        rows = (await session.execute(stmt)).scalars().all()
        return [_serialize_medication(r) for r in rows]

    @staticmethod
    async def add(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        payload: CurrentMedicationPayload,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        _require_tenant_chart(tenant_id, chart_id)
        if not payload.drug_code:
            raise ChartHistoryError(400, "drug_code is required")
        if payload.sequence_index is None or payload.sequence_index < 0:
            raise ChartHistoryError(400, "sequence_index must be >= 0")

        now = datetime.now(UTC)
        stmt = select(ChartHistoryCurrentMedication).where(
            ChartHistoryCurrentMedication.tenant_id == tenant_id,
            ChartHistoryCurrentMedication.chart_id == chart_id,
            ChartHistoryCurrentMedication.drug_code == payload.drug_code,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is not None and existing.deleted_at is None:
            raise ChartHistoryError(
                409,
                "current medication already on chart",
                drug_code=payload.drug_code,
            )
        if existing is not None and existing.deleted_at is not None:
            existing.dose_value = payload.dose_value
            existing.dose_unit_code = payload.dose_unit_code
            existing.route_code = payload.route_code
            existing.frequency_code = payload.frequency_code
            existing.sequence_index = payload.sequence_index
            existing.updated_by_user_id = user_id
            existing.updated_at = now
            existing.deleted_at = None
            existing.version = (existing.version or 1) + 1
            row = existing
        else:
            row = ChartHistoryCurrentMedication(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                chart_id=chart_id,
                drug_code=payload.drug_code,
                dose_value=payload.dose_value,
                dose_unit_code=payload.dose_unit_code,
                route_code=payload.route_code,
                frequency_code=payload.frequency_code,
                sequence_index=payload.sequence_index,
                created_by_user_id=user_id,
                updated_by_user_id=user_id,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            session.add(row)
        await session.flush()
        return _serialize_medication(row)

    @staticmethod
    async def soft_delete(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        row_id: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        _require_tenant_chart(tenant_id, chart_id)
        if not row_id:
            raise ChartHistoryError(400, "row_id is required")
        stmt = select(ChartHistoryCurrentMedication).where(
            ChartHistoryCurrentMedication.tenant_id == tenant_id,
            ChartHistoryCurrentMedication.chart_id == chart_id,
            ChartHistoryCurrentMedication.id == row_id,
            ChartHistoryCurrentMedication.deleted_at.is_(None),
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise ChartHistoryError(404, "current medication not found", row_id=row_id)
        now = datetime.now(UTC)
        row.deleted_at = now
        row.updated_at = now
        row.updated_by_user_id = user_id
        row.version = (row.version or 1) + 1
        await session.flush()
        return _serialize_medication(row)


class ChartHistoryImmunizationService:
    """Tenant-scoped CRUD for eHistory.10 / eHistory.11 immunizations."""

    @staticmethod
    async def list_for_chart(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        _require_tenant_chart(tenant_id, chart_id)
        stmt = select(ChartHistoryImmunization).where(
            ChartHistoryImmunization.tenant_id == tenant_id,
            ChartHistoryImmunization.chart_id == chart_id,
        )
        if not include_deleted:
            stmt = stmt.where(ChartHistoryImmunization.deleted_at.is_(None))
        stmt = stmt.order_by(
            ChartHistoryImmunization.sequence_index,
            ChartHistoryImmunization.immunization_type_code,
        )
        rows = (await session.execute(stmt)).scalars().all()
        return [_serialize_immunization(r) for r in rows]

    @staticmethod
    async def add(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        payload: ImmunizationPayload,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        _require_tenant_chart(tenant_id, chart_id)
        if not payload.immunization_type_code:
            raise ChartHistoryError(400, "immunization_type_code is required")
        if payload.sequence_index is None or payload.sequence_index < 0:
            raise ChartHistoryError(400, "sequence_index must be >= 0")
        if payload.immunization_year is not None and payload.immunization_year < 0:
            raise ChartHistoryError(400, "immunization_year must be >= 0")

        now = datetime.now(UTC)
        row = ChartHistoryImmunization(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            chart_id=chart_id,
            immunization_type_code=payload.immunization_type_code,
            immunization_year=payload.immunization_year,
            sequence_index=payload.sequence_index,
            created_by_user_id=user_id,
            updated_by_user_id=user_id,
            created_at=now,
            updated_at=now,
            deleted_at=None,
        )
        session.add(row)
        await session.flush()
        return _serialize_immunization(row)

    @staticmethod
    async def soft_delete(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        row_id: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        _require_tenant_chart(tenant_id, chart_id)
        if not row_id:
            raise ChartHistoryError(400, "row_id is required")
        stmt = select(ChartHistoryImmunization).where(
            ChartHistoryImmunization.tenant_id == tenant_id,
            ChartHistoryImmunization.chart_id == chart_id,
            ChartHistoryImmunization.id == row_id,
            ChartHistoryImmunization.deleted_at.is_(None),
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise ChartHistoryError(404, "immunization not found", row_id=row_id)
        now = datetime.now(UTC)
        row.deleted_at = now
        row.updated_at = now
        row.updated_by_user_id = user_id
        row.version = (row.version or 1) + 1
        await session.flush()
        return _serialize_immunization(row)


class ChartHistoryService:
    """Composite read for the eHistory aggregate.

    Returns the meta row alongside all four 1:M collections in one
    payload so the API GET / endpoint is a single SQL-bounded call set.
    """

    @staticmethod
    async def get_composite(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
    ) -> dict[str, Any]:
        _require_tenant_chart(tenant_id, chart_id)
        meta = await ChartHistoryMetaService.get(
            session, tenant_id=tenant_id, chart_id=chart_id
        )
        allergies = await ChartHistoryAllergyService.list_for_chart(
            session, tenant_id=tenant_id, chart_id=chart_id
        )
        surgical = await ChartHistorySurgicalService.list_for_chart(
            session, tenant_id=tenant_id, chart_id=chart_id
        )
        current_medications = (
            await ChartHistoryCurrentMedicationService.list_for_chart(
                session, tenant_id=tenant_id, chart_id=chart_id
            )
        )
        immunizations = await ChartHistoryImmunizationService.list_for_chart(
            session, tenant_id=tenant_id, chart_id=chart_id
        )
        return {
            "meta": meta,
            "allergies": allergies,
            "surgical": surgical,
            "current_medications": current_medications,
            "immunizations": immunizations,
        }


__all__ = [
    "ALLERGY_KINDS",
    "AllergyPayload",
    "ChartHistoryAllergyService",
    "ChartHistoryCurrentMedicationService",
    "ChartHistoryError",
    "ChartHistoryImmunizationService",
    "ChartHistoryMetaPayload",
    "ChartHistoryMetaService",
    "ChartHistoryService",
    "ChartHistorySurgicalService",
    "CurrentMedicationPayload",
    "ImmunizationPayload",
    "SurgicalPayload",
    "_META_FIELDS",
    "_META_LIST_FIELDS",
    "_META_SCALAR_FIELDS",
]
