from __future__ import annotations

from types import SimpleNamespace

import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.api import router as epcr_router
from epcr_app.db import get_session
from epcr_app.dependencies import get_current_user
from epcr_app.models import Base


@pytest_asyncio.fixture
async def app_with_db(tmp_path):
    db_file = tmp_path / "incident_numbering_api.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file.as_posix()}")
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app = FastAPI()
    app.include_router(epcr_router)

    async def _override_session():
        async with sessionmaker() as session:
            yield session

    def _override_user():
        return SimpleNamespace(
            tenant_id="tenant-numbering",
            user_id="user-numbering",
            email="admin@example.test",
            roles=["admin"],
        )

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user

    yield app
    await engine.dispose()


def test_agency_provisioning_and_chart_numbering_round_trip(app_with_db) -> None:
    with TestClient(app_with_db) as client:
        agency = client.post(
            "/api/v1/epcr/agencies",
            json={
                "agency_name": "Madison EMS",
                "agency_code": "MADISONEMS",
                "state": "WI",
                "agency_type": "EMS",
                "operational_mode": "EMS_TRANSPORT",
                "billing_mode": "FUSION_RCM",
                "activate": True,
            },
        )
        assert agency.status_code == 201, agency.text
        agency_id = agency.json()["id"]

        chart_1 = client.post(
            "/api/v1/epcr/charts",
            json={
                "agency_id": agency_id,
                "incident_type": "medical",
                "incident_datetime": "2026-05-09T12:00:00Z",
            },
        )
        assert chart_1.status_code == 201, chart_1.text
        body_1 = chart_1.json()
        assert body_1["incident_number"] == "2026-MADISONEMS-000001"
        assert body_1["response_number"] == "2026-MADISONEMS-000001-R01"
        assert body_1["pcr_number"] == "2026-MADISONEMS-000001-PCR01"
        assert body_1["billing_case_number"] == "2026-MADISONEMS-000001-BILL01"
        assert body_1["call_number"] == "2026-MADISONEMS-000001"

        identifiers = client.get(f"/api/v1/epcr/charts/{body_1['id']}/identifiers")
        assert identifiers.status_code == 200, identifiers.text
        assert identifiers.json()["incident_number"] == "2026-MADISONEMS-000001"

        chart_2 = client.post(
            "/api/v1/epcr/charts",
            json={
                "agency_id": agency_id,
                "incident_type": "medical",
                "incident_datetime": "2026-05-09T12:30:00Z",
            },
        )
        assert chart_2.status_code == 201, chart_2.text
        assert chart_2.json()["incident_number"] == "2026-MADISONEMS-000002"


def test_chart_creation_blocks_without_provisioned_agency_code(app_with_db) -> None:
    with TestClient(app_with_db) as client:
        response = client.post(
            "/api/v1/epcr/charts",
            json={
                "incident_type": "medical",
                "incident_datetime": "2026-05-09T12:00:00Z",
            },
        )
        assert response.status_code == 400, response.text
        assert "agency_code is missing" in response.json()["detail"]