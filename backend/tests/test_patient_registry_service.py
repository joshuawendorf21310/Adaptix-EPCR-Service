from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.chart_service import ChartService
from epcr_app.models import (
    AgencyProfile,
    Base,
    PatientRegistryChartLink,
    PatientRegistryIdentifier,
    PatientRegistryProfile,
)
from epcr_app.patient_registry_service import PatientRegistryService


@pytest_asyncio.fixture
async def registry_db(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EPCR_REGISTRY_HASH_KEY", "test-registry-hash-key")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with sessionmaker() as session:
        now = datetime.now(UTC)
        session.add_all(
            [
                AgencyProfile(
                    id=str(uuid4()),
                    tenant_id="tenant-1",
                    agency_code="MADISONEMS",
                    agency_name="Madison EMS",
                    numbering_policy_json="{}",
                    activated_at=now,
                    created_at=now,
                    updated_at=now,
                ),
                AgencyProfile(
                    id=str(uuid4()),
                    tenant_id="tenant-2",
                    agency_code="MADISONEMS",
                    agency_name="Madison EMS",
                    numbering_policy_json="{}",
                    activated_at=now,
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        await session.commit()
    yield sessionmaker
    await engine.dispose()


async def _create_chart(session: AsyncSession, tenant_id: str, created_by: str, call_number: str) -> str:
    chart = await ChartService.create_chart(
        session=session,
        tenant_id=tenant_id,
        call_number=call_number,
        incident_type="medical",
        created_by_user_id=created_by,
        agency_code="MADISONEMS",
        incident_datetime=datetime(2026, 5, 10, tzinfo=UTC),
    )
    return chart.id


@pytest.mark.asyncio
async def test_patient_registry_sync_creates_profile_identifier_and_link(registry_db) -> None:
    async with registry_db() as session:
        chart_id = await _create_chart(session, "tenant-1", "medic-1", "CALL-001")
        await ChartService.upsert_patient_profile(
            session=session,
            tenant_id="tenant-1",
            chart_id=chart_id,
            provider_id="medic-1",
            profile_data={
                "first_name": "Ada",
                "last_name": "Lovelace",
                "date_of_birth": "1815-12-10",
                "sex": "female",
                "phone_number": "555-111-2222",
            },
        )

        profiles = list((await session.execute(select(PatientRegistryProfile))).scalars().all())
        identifiers = list((await session.execute(select(PatientRegistryIdentifier))).scalars().all())
        links = list((await session.execute(select(PatientRegistryChartLink))).scalars().all())

        assert len(profiles) == 1
        assert profiles[0].canonical_patient_key == PatientRegistryService.build_canonical_patient_key("Ada", "Lovelace", "1815-12-10")
        assert profiles[0].phone_last4 == "2222"
        assert len(identifiers) == 1
        assert identifiers[0].identifier_hash != "5551112222"
        assert len(links) == 1
        assert links[0].chart_id == chart_id
        assert links[0].confidence_status == "exact_duplicate"


@pytest.mark.asyncio
async def test_patient_registry_reuses_profile_for_repeat_patient(registry_db) -> None:
    async with registry_db() as session:
        chart_1 = await _create_chart(session, "tenant-1", "medic-1", "CALL-001")
        chart_2 = await _create_chart(session, "tenant-1", "medic-1", "CALL-002")

        payload = {
            "first_name": "Ada",
            "last_name": "Lovelace",
            "date_of_birth": "1815-12-10",
            "sex": "female",
            "phone_number": "555-111-2222",
        }
        await ChartService.upsert_patient_profile(session, "tenant-1", chart_1, "medic-1", payload)
        await ChartService.upsert_patient_profile(session, "tenant-1", chart_2, "medic-1", payload)

        profiles = list((await session.execute(select(PatientRegistryProfile))).scalars().all())
        links = list((await session.execute(select(PatientRegistryChartLink))).scalars().all())

        assert len(profiles) == 1
        assert len(links) == 2
        assert {link.chart_id for link in links} == {chart_1, chart_2}


@pytest.mark.asyncio
async def test_patient_registry_is_tenant_scoped(registry_db) -> None:
    async with registry_db() as session:
        chart_1 = await _create_chart(session, "tenant-1", "medic-1", "CALL-001")
        chart_2 = await _create_chart(session, "tenant-2", "medic-2", "CALL-002")

        payload = {
            "first_name": "Ada",
            "last_name": "Lovelace",
            "date_of_birth": "1815-12-10",
            "sex": "female",
            "phone_number": "555-111-2222",
        }
        await ChartService.upsert_patient_profile(session, "tenant-1", chart_1, "medic-1", payload)
        await ChartService.upsert_patient_profile(session, "tenant-2", chart_2, "medic-2", payload)

        tenant_1 = await PatientRegistryService.search_profiles(
            session,
            "tenant-1",
            first_name="Ada",
            last_name="Lovelace",
            date_of_birth="1815-12-10",
        )
        tenant_2 = await PatientRegistryService.search_profiles(
            session,
            "tenant-2",
            first_name="Ada",
            last_name="Lovelace",
            date_of_birth="1815-12-10",
        )

        assert len(tenant_1) == 1
        assert len(tenant_2) == 1
        assert tenant_1[0].profile_id != tenant_2[0].profile_id