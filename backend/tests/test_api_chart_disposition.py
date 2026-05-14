"""API tests for the eDisposition router (:mod:`epcr_app.api_chart_disposition`).

Hermetic: in-memory SQLite, FastAPI TestClient, dependency-overridden
auth and session.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.api_chart_disposition import router as disposition_router
from epcr_app.db import get_session
from epcr_app.dependencies import get_current_user
from epcr_app.models import Base, Chart
from epcr_app.models_chart_disposition import ChartDisposition  # noqa: F401
from epcr_app.models_nemsis_field_values import NemsisFieldValue


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Pre-seed one chart for tenant T-1
    async with sessionmaker() as s:
        chart = Chart(
            id="chart-1",
            tenant_id="T-1",
            call_number="C-1",
            created_by_user_id="user-1",
        )
        s.add(chart)
        await s.commit()

    app = FastAPI()
    app.include_router(disposition_router)

    async def _override_session():
        async with sessionmaker() as session:
            yield session

    def _override_user():
        return SimpleNamespace(
            tenant_id="T-1", user_id="user-1", email="x@x", roles=["paramedic"]
        )

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user

    with TestClient(app) as c:
        yield c, sessionmaker
    await engine.dispose()


def test_get_returns_404_when_absent(client) -> None:
    c, _ = client
    r = c.get("/api/v1/epcr/charts/chart-1/disposition")
    assert r.status_code == 404


def test_put_creates_then_get_returns(client) -> None:
    c, _ = client
    body = {
        "destination_name": "Memorial Hospital",
        "incident_patient_disposition_code": "4212001",
        "transport_disposition_code": "4227005",
        "level_of_care_provided_code": "4218015",
    }
    r = c.put("/api/v1/epcr/charts/chart-1/disposition", json=body)
    assert r.status_code == 200, r.text
    body_out = r.json()
    assert body_out["destination_name"] == "Memorial Hospital"
    assert body_out["incident_patient_disposition_code"] == "4212001"

    g = c.get("/api/v1/epcr/charts/chart-1/disposition")
    assert g.status_code == 200
    assert g.json()["transport_disposition_code"] == "4227005"


def test_put_projects_scalars_and_lists_to_field_values_ledger(client) -> None:
    c, sessionmaker = client
    body = {
        "destination_name": "Memorial Hospital",
        "incident_patient_disposition_code": "4212001",
        "transport_disposition_code": "4227005",
        "level_of_care_provided_code": "4218015",
        "hospital_capability_codes_json": ["4209007", "4209013"],
        "crew_disposition_codes_json": ["4234007"],
    }
    r = c.put("/api/v1/epcr/charts/chart-1/disposition", json=body)
    assert r.status_code == 200, r.text

    async def _check():
        async with sessionmaker() as s:
            rows = (
                await s.execute(
                    select(NemsisFieldValue).where(
                        NemsisFieldValue.chart_id == "chart-1",
                        NemsisFieldValue.section == "eDisposition",
                    )
                )
            ).scalars().all()
            elements = {r.element_number for r in rows}
            # Scalars must be present
            assert {
                "eDisposition.01",
                "eDisposition.12",
                "eDisposition.16",
                "eDisposition.18",
            } <= elements
            # List columns project one row per entry
            cap_rows = [r for r in rows if r.element_number == "eDisposition.09"]
            assert len(cap_rows) == 2
            crew_rows = [r for r in rows if r.element_number == "eDisposition.27"]
            assert len(crew_rows) == 1

    import asyncio
    asyncio.get_event_loop().run_until_complete(_check())


def test_delete_clears_one_field(client) -> None:
    c, _ = client
    c.put(
        "/api/v1/epcr/charts/chart-1/disposition",
        json={
            "destination_name": "Mercy",
            "transport_disposition_code": "4227005",
        },
    )
    r = c.delete("/api/v1/epcr/charts/chart-1/disposition/destination_name")
    assert r.status_code == 200, r.text
    assert r.json()["destination_name"] is None
    assert r.json()["transport_disposition_code"] == "4227005"


def test_delete_unknown_field_400(client) -> None:
    c, _ = client
    c.put(
        "/api/v1/epcr/charts/chart-1/disposition",
        json={"transport_disposition_code": "4227005"},
    )
    r = c.delete("/api/v1/epcr/charts/chart-1/disposition/not_a_column")
    assert r.status_code == 400


def test_put_rejects_unknown_field(client) -> None:
    c, _ = client
    r = c.put(
        "/api/v1/epcr/charts/chart-1/disposition",
        json={"not_a_real_field": "x"},
    )
    assert r.status_code == 422


def test_delete_clears_json_list_field(client) -> None:
    c, _ = client
    c.put(
        "/api/v1/epcr/charts/chart-1/disposition",
        json={"hospital_capability_codes_json": ["4209007", "4209013"]},
    )
    r = c.delete(
        "/api/v1/epcr/charts/chart-1/disposition/hospital_capability_codes_json"
    )
    assert r.status_code == 200, r.text
    assert r.json()["hospital_capability_codes_json"] is None
