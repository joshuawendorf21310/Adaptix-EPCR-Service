"""Patient registry read/search API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.patient_registry_service import PatientRegistryService


router = APIRouter(prefix="/api/v1/epcr/patient-registry", tags=["patient-registry"])


class PatientRegistrySearchResponse(BaseModel):
    profile_id: str
    canonical_patient_key: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    date_of_birth: str | None = None
    sex: str | None = None
    phone_last4: str | None = None


class PatientRegistryProfileResponse(PatientRegistrySearchResponse):
    merged_into_patient_id: str | None = None


class PatientRegistryChartLinkResponse(BaseModel):
    chart_id: str
    link_status: str
    confidence_status: str | None = None
    linked_at: str


@router.get("/search", response_model=list[PatientRegistrySearchResponse])
async def search_patient_registry(
    first_name: str | None = Query(None),
    last_name: str | None = Query(None),
    date_of_birth: str | None = Query(None),
    phone_number: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    matches = await PatientRegistryService.search_profiles(
        session,
        str(current_user.tenant_id),
        first_name=first_name,
        last_name=last_name,
        date_of_birth=date_of_birth,
        phone_number=phone_number,
    )
    return [
        PatientRegistrySearchResponse(
            profile_id=match.profile_id,
            canonical_patient_key=match.canonical_patient_key,
            first_name=match.first_name,
            last_name=match.last_name,
            date_of_birth=match.date_of_birth,
            sex=match.sex,
            phone_last4=match.phone_last4,
        )
        for match in matches
    ]


@router.get("/{profile_id}", response_model=PatientRegistryProfileResponse)
async def get_patient_registry_profile(
    profile_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    profile = await PatientRegistryService.get_profile(session, str(current_user.tenant_id), profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail={"message": f"Patient registry profile {profile_id} not found"})
    return PatientRegistryProfileResponse(
        profile_id=profile.id,
        canonical_patient_key=profile.canonical_patient_key,
        first_name=profile.first_name,
        last_name=profile.last_name,
        date_of_birth=profile.date_of_birth,
        sex=profile.sex,
        phone_last4=profile.phone_last4,
        merged_into_patient_id=profile.merged_into_patient_id,
    )


@router.get("/{profile_id}/charts", response_model=list[PatientRegistryChartLinkResponse])
async def get_patient_registry_profile_charts(
    profile_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    profile = await PatientRegistryService.get_profile(session, str(current_user.tenant_id), profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail={"message": f"Patient registry profile {profile_id} not found"})
    links = await PatientRegistryService.get_profile_chart_links(session, str(current_user.tenant_id), profile_id)
    return [
        PatientRegistryChartLinkResponse(
            chart_id=link.chart_id,
            link_status=link.link_status,
            confidence_status=link.confidence_status,
            linked_at=link.linked_at.isoformat(),
        )
        for link in links
    ]