"""NEMSIS ePatient extension API router.

Tenant-scoped HTTP surface for the ePatient elements not already covered
by :class:`PatientProfile`. Every route enforces real authentication via
``get_current_user`` and uses a real database session via
``get_session``. Tenant isolation is delegated to the service layer and
verified at the SQL level.

Routes (mounted at ``/api/v1/epcr/charts/{chart_id}/patient-ext``):

* ``GET    /``               -> full snapshot: scalar ext + home_address +
                                 races + languages + phones.
* ``PUT    /scalar``         -> upsert the scalar 1:1 extension.
* ``PUT    /home-address``   -> upsert the Patient's Home Address group.
* ``POST   /races``          -> add a race row.
* ``DELETE /races/{row_id}`` -> soft-delete a race row.
* ``POST   /languages``      -> add a preferred-language row.
* ``DELETE /languages/{row_id}``
* ``POST   /phones``         -> add a phone-number row.
* ``DELETE /phones/{row_id}``
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.projection_patient_profile_ext import project_patient_profile_ext
from epcr_app.services_patient_profile_ext import (
    PatientHomeAddressPayload,
    PatientHomeAddressService,
    PatientLanguagePayload,
    PatientLanguageService,
    PatientPhoneNumberPayload,
    PatientPhoneNumberService,
    PatientProfileExtError,
    PatientProfileExtPayload,
    PatientProfileExtService,
    PatientRacePayload,
    PatientRaceService,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/epcr/charts/{chart_id}/patient-ext",
    tags=["nemsis-epatient-ext"],
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class PatientProfileExtRequest(BaseModel):
    """Caller request body for PUT /scalar."""

    model_config = ConfigDict(extra="forbid")

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


class PatientHomeAddressRequest(BaseModel):
    """Caller request body for PUT /home-address."""

    model_config = ConfigDict(extra="forbid")

    home_street_address: str | None = None
    home_city: str | None = None
    home_county: str | None = None
    home_state: str | None = None
    home_zip: str | None = None


class PatientRaceRequest(BaseModel):
    """Caller request body for POST /races."""

    model_config = ConfigDict(extra="forbid")

    race_code: str = Field(..., min_length=1)
    sequence_index: int = Field(default=0, ge=0)


class PatientLanguageRequest(BaseModel):
    """Caller request body for POST /languages."""

    model_config = ConfigDict(extra="forbid")

    language_code: str = Field(..., min_length=1)
    sequence_index: int = Field(default=0, ge=0)


class PatientPhoneNumberRequest(BaseModel):
    """Caller request body for POST /phones."""

    model_config = ConfigDict(extra="forbid")

    phone_number: str = Field(..., min_length=1)
    phone_type_code: str | None = None
    sequence_index: int = Field(default=0, ge=0)


class AnyResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# GET full snapshot
# ---------------------------------------------------------------------------


@router.get("", response_model=AnyResponse)
async def get_patient_ext(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Return the full ePatient-extension snapshot for the chart."""
    tenant_id = str(user.tenant_id)
    try:
        scalar = await PatientProfileExtService.get(
            session, tenant_id=tenant_id, chart_id=chart_id
        )
        address = await PatientHomeAddressService.get(
            session, tenant_id=tenant_id, chart_id=chart_id
        )
        races = await PatientRaceService.list_for_chart(
            session, tenant_id=tenant_id, chart_id=chart_id
        )
        languages = await PatientLanguageService.list_for_chart(
            session, tenant_id=tenant_id, chart_id=chart_id
        )
        phones = await PatientPhoneNumberService.list_for_chart(
            session, tenant_id=tenant_id, chart_id=chart_id
        )
    except PatientProfileExtError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return {
        "scalar": scalar,
        "home_address": address,
        "races": races,
        "languages": languages,
        "phones": phones,
    }


# ---------------------------------------------------------------------------
# Scalar 1:1
# ---------------------------------------------------------------------------


@router.put("/scalar", response_model=AnyResponse, status_code=status.HTTP_200_OK)
async def upsert_patient_ext_scalar(
    chart_id: str,
    body: PatientProfileExtRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Upsert the scalar 1:1 ePatient extension row."""
    tenant_id = str(user.tenant_id)
    user_id = str(user.user_id)
    try:
        record = await PatientProfileExtService.upsert(
            session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            payload=PatientProfileExtPayload(**body.model_dump(exclude_unset=False)),
            user_id=user_id,
        )
        await project_patient_profile_ext(
            session, tenant_id=tenant_id, chart_id=chart_id, user_id=user_id
        )
        await session.commit()
    except PatientProfileExtError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return record


# ---------------------------------------------------------------------------
# Home address 1:1
# ---------------------------------------------------------------------------


@router.put("/home-address", response_model=AnyResponse, status_code=status.HTTP_200_OK)
async def upsert_patient_home_address(
    chart_id: str,
    body: PatientHomeAddressRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Upsert the Patient's Home Address 1:1 row."""
    tenant_id = str(user.tenant_id)
    user_id = str(user.user_id)
    try:
        record = await PatientHomeAddressService.upsert(
            session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            payload=PatientHomeAddressPayload(**body.model_dump(exclude_unset=False)),
            user_id=user_id,
        )
        await project_patient_profile_ext(
            session, tenant_id=tenant_id, chart_id=chart_id, user_id=user_id
        )
        await session.commit()
    except PatientProfileExtError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return record


# ---------------------------------------------------------------------------
# Races 1:M
# ---------------------------------------------------------------------------


@router.post("/races", response_model=AnyResponse, status_code=status.HTTP_201_CREATED)
async def add_patient_race(
    chart_id: str,
    body: PatientRaceRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Add one race code (ePatient.14) to the chart."""
    tenant_id = str(user.tenant_id)
    user_id = str(user.user_id)
    try:
        record = await PatientRaceService.add(
            session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            payload=PatientRacePayload(
                race_code=body.race_code, sequence_index=body.sequence_index
            ),
            user_id=user_id,
        )
        await project_patient_profile_ext(
            session, tenant_id=tenant_id, chart_id=chart_id, user_id=user_id
        )
        await session.commit()
    except PatientProfileExtError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return record


@router.delete("/races/{row_id}", response_model=AnyResponse)
async def delete_patient_race(
    chart_id: str,
    row_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Soft-delete one race row."""
    tenant_id = str(user.tenant_id)
    user_id = str(user.user_id)
    try:
        record = await PatientRaceService.soft_delete(
            session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            row_id=row_id,
            user_id=user_id,
        )
        await project_patient_profile_ext(
            session, tenant_id=tenant_id, chart_id=chart_id, user_id=user_id
        )
        await session.commit()
    except PatientProfileExtError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return record


# ---------------------------------------------------------------------------
# Languages 1:M
# ---------------------------------------------------------------------------


@router.post("/languages", response_model=AnyResponse, status_code=status.HTTP_201_CREATED)
async def add_patient_language(
    chart_id: str,
    body: PatientLanguageRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Add one preferred-language code (ePatient.24) to the chart."""
    tenant_id = str(user.tenant_id)
    user_id = str(user.user_id)
    try:
        record = await PatientLanguageService.add(
            session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            payload=PatientLanguagePayload(
                language_code=body.language_code, sequence_index=body.sequence_index
            ),
            user_id=user_id,
        )
        await project_patient_profile_ext(
            session, tenant_id=tenant_id, chart_id=chart_id, user_id=user_id
        )
        await session.commit()
    except PatientProfileExtError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return record


@router.delete("/languages/{row_id}", response_model=AnyResponse)
async def delete_patient_language(
    chart_id: str,
    row_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Soft-delete one preferred-language row."""
    tenant_id = str(user.tenant_id)
    user_id = str(user.user_id)
    try:
        record = await PatientLanguageService.soft_delete(
            session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            row_id=row_id,
            user_id=user_id,
        )
        await project_patient_profile_ext(
            session, tenant_id=tenant_id, chart_id=chart_id, user_id=user_id
        )
        await session.commit()
    except PatientProfileExtError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return record


# ---------------------------------------------------------------------------
# Phones 1:M
# ---------------------------------------------------------------------------


@router.post("/phones", response_model=AnyResponse, status_code=status.HTTP_201_CREATED)
async def add_patient_phone(
    chart_id: str,
    body: PatientPhoneNumberRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Add one Patient's Phone Number row (ePatient.18) to the chart."""
    tenant_id = str(user.tenant_id)
    user_id = str(user.user_id)
    try:
        record = await PatientPhoneNumberService.add(
            session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            payload=PatientPhoneNumberPayload(
                phone_number=body.phone_number,
                phone_type_code=body.phone_type_code,
                sequence_index=body.sequence_index,
            ),
            user_id=user_id,
        )
        await project_patient_profile_ext(
            session, tenant_id=tenant_id, chart_id=chart_id, user_id=user_id
        )
        await session.commit()
    except PatientProfileExtError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return record


@router.delete("/phones/{row_id}", response_model=AnyResponse)
async def delete_patient_phone(
    chart_id: str,
    row_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Soft-delete one phone-number row."""
    tenant_id = str(user.tenant_id)
    user_id = str(user.user_id)
    try:
        record = await PatientPhoneNumberService.soft_delete(
            session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            row_id=row_id,
            user_id=user_id,
        )
        await project_patient_profile_ext(
            session, tenant_id=tenant_id, chart_id=chart_id, user_id=user_id
        )
        await session.commit()
    except PatientProfileExtError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return record


__all__ = ["router"]
