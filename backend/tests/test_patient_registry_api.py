from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.api_patient_registry import router as patient_registry_router
from epcr_app.chart_service import ChartService
from epcr_app.db import get_session
from epcr_app.dependencies import get_current_user
from epcr_app.models import AgencyProfile, Base


@pytest_asyncio.fixture
async def registry_app(monkeypatch):
    monkeypatch.setenv("EPCR_REGISTRY_HASH_KEY", "test-registry-hash-key")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with sessionmaker() as session:
        now = datetime.now(UTC)
        session.add(
            AgencyProfile(
                id=str(uuid4()),
                tenant_id="tenant-api",
                agency_code="MADISONEMS",
                agency_name="Madison EMS",
                numbering_policy_json="{}",
                activated_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()

    app = FastAPI()
    app.include_router(patient_registry_router)

    async def _override_session():
        async with sessionmaker() as session:
            yield session

    def _override_user():
        return SimpleNamespace(
            tenant_id="tenant-api",
            user_id="user-api",
            email="api@x",
            roles=["paramedic"],
        )

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user

    async with sessionmaker() as session:
        chart_1 = await ChartService.create_chart(
            session=session,
            tenant_id="tenant-api",
            call_number="API-CALL-001",
            incident_type="medical",
            created_by_user_id="user-api",
            agency_code="MADISONEMS",
            incident_datetime=datetime(2026, 5, 10, tzinfo=UTC),
        )
        chart_2 = await ChartService.create_chart(
            session=session,
            tenant_id="tenant-api",
            call_number="API-CALL-002",
            incident_type="medical",
            created_by_user_id="user-api",
            agency_code="MADISONEMS",
            incident_datetime=datetime(2026, 5, 10, tzinfo=UTC),
        )
        payload = {
            "first_name": "Ada",
            "last_name": "Lovelace",
            "date_of_birth": "1815-12-10",
            "sex": "female",
            "phone_number": "555-111-2222",
        }
        await ChartService.upsert_patient_profile(session, "tenant-api", chart_1.id, "user-api", payload)
        await ChartService.upsert_patient_profile(session, "tenant-api", chart_2.id, "user-api", payload)

    yield app
    await engine.dispose()


def test_patient_registry_search_get_and_chart_links(registry_app) -> None:
    with TestClient(registry_app) as client:
        search = client.get(
            "/api/v1/epcr/patient-registry/search",
            params={
                "first_name": "Ada",
                "last_name": "Lovelace",
                "date_of_birth": "1815-12-10",
            },
        )
        assert search.status_code == 200, search.text
        results = search.json()
        assert len(results) == 1
        profile_id = results[0]["profile_id"]
        assert results[0]["phone_last4"] == "2222"

        profile = client.get(f"/api/v1/epcr/patient-registry/{profile_id}")
        assert profile.status_code == 200
        assert profile.json()["first_name"] == "Ada"

        charts = client.get(f"/api/v1/epcr/patient-registry/{profile_id}/charts")
        assert charts.status_code == 200
        chart_links = charts.json()
        assert len(chart_links) == 2
        assert all(link["link_status"] == "linked" for link in chart_links)