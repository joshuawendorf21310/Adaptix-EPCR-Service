"""NEMSIS ePatient extension service: tenant-scoped upsert/CRUD.

Every read and write is filtered by ``tenant_id`` at the SQL layer so
no cross-tenant escape is possible. The services here are intentionally
thin: they persist the raw scalar/child rows; conversion to NEMSIS XML
is the projection layer's job (:mod:`projection_patient_profile_ext`).

Five aggregates are exposed:

* :class:`PatientProfileExtService`   — scalar 1:1 extension
* :class:`PatientHomeAddressService`  — 1:1 home address group
* :class:`PatientRaceService`         — 1:M ePatient.14 race rows
* :class:`PatientLanguageService`     — 1:M ePatient.24 language rows
* :class:`PatientPhoneNumberService`  — 1:M ePatient.18 phone rows
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models_patient_profile_ext import (
    PatientHomeAddress,
    PatientLanguage,
    PatientPhoneNumber,
    PatientProfileNemsisExt,
    PatientRace,
)


_SCALAR_FIELDS: tuple[str, ...] = (
    "ems_patient_id",
    "country_of_residence_code",
    "patient_home_census_tract",
    "ssn_hash",
    "age_units_code",
    "email_address",
    "driver_license_state",
    "driver_license_number",
    "alternate_home_residence_code",
    "name_suffix",
    "sex_nemsis_code",
)

_ADDRESS_FIELDS: tuple[str, ...] = (
    "home_street_address",
    "home_city",
    "home_county",
    "home_state",
    "home_zip",
)


class PatientProfileExtError(Exception):
    """Raised on caller errors that are safe to surface to the API layer."""

    def __init__(self, status_code: int, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = {"message": message, **extra}


# ---------------------------------------------------------------------------
# Payload dataclasses
# ---------------------------------------------------------------------------


@dataclass
class PatientProfileExtPayload:
    """Caller-side payload for upserting the scalar 1:1 extension.

    All fields are optional. Any field omitted (``None``) retains its
    current persisted value on update. Clearing is done via service
    helpers, not by passing ``None``.
    """

    ems_patient_id: str | None = None
    country_of_residence_code: str | None = None
    patient_home_census_tract: str | None = None
    ssn_hash: str | None = None
    age_units_code: str | None = None
    email_address: str | None = None
    driver_license_state: str | None = None
    driver_license_number: str | None = None
    alternate_home_residence_code: str | None = None
    name_suffix: str | None = None
    sex_nemsis_code: str | None = None


@dataclass
class PatientHomeAddressPayload:
    home_street_address: str | None = None
    home_city: str | None = None
    home_county: str | None = None
    home_state: str | None = None
    home_zip: str | None = None


@dataclass
class PatientRacePayload:
    race_code: str
    sequence_index: int = 0


@dataclass
class PatientLanguagePayload:
    language_code: str
    sequence_index: int = 0


@dataclass
class PatientPhoneNumberPayload:
    phone_number: str
    phone_type_code: str | None = None
    sequence_index: int = 0


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def _serialize_ext(row: PatientProfileNemsisExt) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "chart_id": row.chart_id,
        "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
    }
    for f in _SCALAR_FIELDS:
        out[f] = getattr(row, f)
    return out


def _serialize_address(row: PatientHomeAddress) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "chart_id": row.chart_id,
        "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
    }
    for f in _ADDRESS_FIELDS:
        out[f] = getattr(row, f)
    return out


def _serialize_race(row: PatientRace) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "chart_id": row.chart_id,
        "race_code": row.race_code,
        "sequence_index": row.sequence_index,
        "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
    }


def _serialize_language(row: PatientLanguage) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "chart_id": row.chart_id,
        "language_code": row.language_code,
        "sequence_index": row.sequence_index,
        "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
    }


def _serialize_phone(row: PatientPhoneNumber) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "chart_id": row.chart_id,
        "phone_number": row.phone_number,
        "phone_type_code": row.phone_type_code,
        "sequence_index": row.sequence_index,
        "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
    }


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------


def _require_ids(tenant_id: str, chart_id: str) -> None:
    if not tenant_id:
        raise PatientProfileExtError(400, "tenant_id is required")
    if not chart_id:
        raise PatientProfileExtError(400, "chart_id is required")


class PatientProfileExtService:
    """Tenant-scoped persistence for the 1:1 scalar ePatient extension."""

    @staticmethod
    async def get(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
    ) -> dict[str, Any] | None:
        _require_ids(tenant_id, chart_id)
        stmt = select(PatientProfileNemsisExt).where(
            PatientProfileNemsisExt.tenant_id == tenant_id,
            PatientProfileNemsisExt.chart_id == chart_id,
            PatientProfileNemsisExt.deleted_at.is_(None),
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        return _serialize_ext(row) if row else None

    @staticmethod
    async def upsert(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        payload: PatientProfileExtPayload,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        _require_ids(tenant_id, chart_id)
        now = datetime.now(UTC)
        stmt = select(PatientProfileNemsisExt).where(
            PatientProfileNemsisExt.tenant_id == tenant_id,
            PatientProfileNemsisExt.chart_id == chart_id,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            row = PatientProfileNemsisExt(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                chart_id=chart_id,
                created_by_user_id=user_id,
                updated_by_user_id=user_id,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            for f in _SCALAR_FIELDS:
                setattr(row, f, getattr(payload, f))
            session.add(row)
        else:
            for f in _SCALAR_FIELDS:
                value = getattr(payload, f)
                if value is not None:
                    setattr(row, f, value)
            row.updated_by_user_id = user_id
            row.updated_at = now
            row.deleted_at = None
            row.version = (row.version or 1) + 1
        await session.flush()
        return _serialize_ext(row)


class PatientHomeAddressService:
    """Tenant-scoped persistence for the Patient's Home Address 1:1 row."""

    @staticmethod
    async def get(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
    ) -> dict[str, Any] | None:
        _require_ids(tenant_id, chart_id)
        stmt = select(PatientHomeAddress).where(
            PatientHomeAddress.tenant_id == tenant_id,
            PatientHomeAddress.chart_id == chart_id,
            PatientHomeAddress.deleted_at.is_(None),
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        return _serialize_address(row) if row else None

    @staticmethod
    async def upsert(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        payload: PatientHomeAddressPayload,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        _require_ids(tenant_id, chart_id)
        now = datetime.now(UTC)
        stmt = select(PatientHomeAddress).where(
            PatientHomeAddress.tenant_id == tenant_id,
            PatientHomeAddress.chart_id == chart_id,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            row = PatientHomeAddress(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                chart_id=chart_id,
                created_by_user_id=user_id,
                updated_by_user_id=user_id,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            for f in _ADDRESS_FIELDS:
                setattr(row, f, getattr(payload, f))
            session.add(row)
        else:
            for f in _ADDRESS_FIELDS:
                value = getattr(payload, f)
                if value is not None:
                    setattr(row, f, value)
            row.updated_by_user_id = user_id
            row.updated_at = now
            row.deleted_at = None
            row.version = (row.version or 1) + 1
        await session.flush()
        return _serialize_address(row)


# ---------------------------------------------------------------------------
# Generic 1:M helpers
# ---------------------------------------------------------------------------


async def _list_1m(
    session: AsyncSession,
    *,
    model,
    serialize,
    tenant_id: str,
    chart_id: str,
    order_by,
    include_deleted: bool = False,
) -> list[dict[str, Any]]:
    _require_ids(tenant_id, chart_id)
    stmt = select(model).where(
        model.tenant_id == tenant_id,
        model.chart_id == chart_id,
    )
    if not include_deleted:
        stmt = stmt.where(model.deleted_at.is_(None))
    stmt = stmt.order_by(*order_by)
    rows = (await session.execute(stmt)).scalars().all()
    return [serialize(r) for r in rows]


async def _soft_delete_1m(
    session: AsyncSession,
    *,
    model,
    serialize,
    tenant_id: str,
    chart_id: str,
    row_id: str,
    user_id: str | None,
) -> dict[str, Any]:
    _require_ids(tenant_id, chart_id)
    if not row_id:
        raise PatientProfileExtError(400, "row_id is required")
    stmt = select(model).where(
        model.tenant_id == tenant_id,
        model.chart_id == chart_id,
        model.id == row_id,
        model.deleted_at.is_(None),
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise PatientProfileExtError(404, "row not found", row_id=row_id)
    now = datetime.now(UTC)
    row.deleted_at = now
    row.updated_at = now
    row.updated_by_user_id = user_id
    row.version = (row.version or 1) + 1
    await session.flush()
    return serialize(row)


class PatientRaceService:
    """Tenant-scoped persistence for ePatient.14 Race (1:M)."""

    @staticmethod
    async def list_for_chart(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        return await _list_1m(
            session,
            model=PatientRace,
            serialize=_serialize_race,
            tenant_id=tenant_id,
            chart_id=chart_id,
            order_by=(PatientRace.sequence_index, PatientRace.race_code),
            include_deleted=include_deleted,
        )

    @staticmethod
    async def add(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        payload: PatientRacePayload,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        _require_ids(tenant_id, chart_id)
        if not payload.race_code:
            raise PatientProfileExtError(400, "race_code is required")
        if payload.sequence_index is None or payload.sequence_index < 0:
            raise PatientProfileExtError(400, "sequence_index must be >= 0")
        now = datetime.now(UTC)
        stmt = select(PatientRace).where(
            PatientRace.tenant_id == tenant_id,
            PatientRace.chart_id == chart_id,
            PatientRace.race_code == payload.race_code,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is not None and existing.deleted_at is None:
            raise PatientProfileExtError(
                409, "race already recorded for chart", race_code=payload.race_code
            )
        if existing is not None and existing.deleted_at is not None:
            existing.sequence_index = payload.sequence_index
            existing.updated_by_user_id = user_id
            existing.updated_at = now
            existing.deleted_at = None
            existing.version = (existing.version or 1) + 1
            row = existing
        else:
            row = PatientRace(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                chart_id=chart_id,
                race_code=payload.race_code,
                sequence_index=payload.sequence_index,
                created_by_user_id=user_id,
                updated_by_user_id=user_id,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            session.add(row)
        await session.flush()
        return _serialize_race(row)

    @staticmethod
    async def soft_delete(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        row_id: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        return await _soft_delete_1m(
            session,
            model=PatientRace,
            serialize=_serialize_race,
            tenant_id=tenant_id,
            chart_id=chart_id,
            row_id=row_id,
            user_id=user_id,
        )


class PatientLanguageService:
    """Tenant-scoped persistence for ePatient.24 Preferred Language (1:M)."""

    @staticmethod
    async def list_for_chart(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        return await _list_1m(
            session,
            model=PatientLanguage,
            serialize=_serialize_language,
            tenant_id=tenant_id,
            chart_id=chart_id,
            order_by=(PatientLanguage.sequence_index, PatientLanguage.language_code),
            include_deleted=include_deleted,
        )

    @staticmethod
    async def add(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        payload: PatientLanguagePayload,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        _require_ids(tenant_id, chart_id)
        if not payload.language_code:
            raise PatientProfileExtError(400, "language_code is required")
        if payload.sequence_index is None or payload.sequence_index < 0:
            raise PatientProfileExtError(400, "sequence_index must be >= 0")
        now = datetime.now(UTC)
        stmt = select(PatientLanguage).where(
            PatientLanguage.tenant_id == tenant_id,
            PatientLanguage.chart_id == chart_id,
            PatientLanguage.language_code == payload.language_code,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is not None and existing.deleted_at is None:
            raise PatientProfileExtError(
                409,
                "language already recorded for chart",
                language_code=payload.language_code,
            )
        if existing is not None and existing.deleted_at is not None:
            existing.sequence_index = payload.sequence_index
            existing.updated_by_user_id = user_id
            existing.updated_at = now
            existing.deleted_at = None
            existing.version = (existing.version or 1) + 1
            row = existing
        else:
            row = PatientLanguage(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                chart_id=chart_id,
                language_code=payload.language_code,
                sequence_index=payload.sequence_index,
                created_by_user_id=user_id,
                updated_by_user_id=user_id,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            session.add(row)
        await session.flush()
        return _serialize_language(row)

    @staticmethod
    async def soft_delete(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        row_id: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        return await _soft_delete_1m(
            session,
            model=PatientLanguage,
            serialize=_serialize_language,
            tenant_id=tenant_id,
            chart_id=chart_id,
            row_id=row_id,
            user_id=user_id,
        )


class PatientPhoneNumberService:
    """Tenant-scoped persistence for ePatient.18 Patient's Phone Number (1:M)."""

    @staticmethod
    async def list_for_chart(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        return await _list_1m(
            session,
            model=PatientPhoneNumber,
            serialize=_serialize_phone,
            tenant_id=tenant_id,
            chart_id=chart_id,
            order_by=(PatientPhoneNumber.sequence_index, PatientPhoneNumber.phone_number),
            include_deleted=include_deleted,
        )

    @staticmethod
    async def add(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        payload: PatientPhoneNumberPayload,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        _require_ids(tenant_id, chart_id)
        if not payload.phone_number:
            raise PatientProfileExtError(400, "phone_number is required")
        if payload.sequence_index is None or payload.sequence_index < 0:
            raise PatientProfileExtError(400, "sequence_index must be >= 0")
        now = datetime.now(UTC)
        stmt = select(PatientPhoneNumber).where(
            PatientPhoneNumber.tenant_id == tenant_id,
            PatientPhoneNumber.chart_id == chart_id,
            PatientPhoneNumber.phone_number == payload.phone_number,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is not None and existing.deleted_at is None:
            raise PatientProfileExtError(
                409,
                "phone number already recorded for chart",
                phone_number=payload.phone_number,
            )
        if existing is not None and existing.deleted_at is not None:
            existing.phone_type_code = payload.phone_type_code
            existing.sequence_index = payload.sequence_index
            existing.updated_by_user_id = user_id
            existing.updated_at = now
            existing.deleted_at = None
            existing.version = (existing.version or 1) + 1
            row = existing
        else:
            row = PatientPhoneNumber(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                chart_id=chart_id,
                phone_number=payload.phone_number,
                phone_type_code=payload.phone_type_code,
                sequence_index=payload.sequence_index,
                created_by_user_id=user_id,
                updated_by_user_id=user_id,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            session.add(row)
        await session.flush()
        return _serialize_phone(row)

    @staticmethod
    async def soft_delete(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        row_id: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        return await _soft_delete_1m(
            session,
            model=PatientPhoneNumber,
            serialize=_serialize_phone,
            tenant_id=tenant_id,
            chart_id=chart_id,
            row_id=row_id,
            user_id=user_id,
        )


__all__ = [
    "PatientProfileExtError",
    "PatientProfileExtPayload",
    "PatientHomeAddressPayload",
    "PatientRacePayload",
    "PatientLanguagePayload",
    "PatientPhoneNumberPayload",
    "PatientProfileExtService",
    "PatientHomeAddressService",
    "PatientRaceService",
    "PatientLanguageService",
    "PatientPhoneNumberService",
    "_SCALAR_FIELDS",
    "_ADDRESS_FIELDS",
]
