"""API tests for the eScene router (:mod:`epcr_app.api_chart_scene`).

Hermetic: in-memory SQLite, FastAPI TestClient, dependency-overridden
auth and session. Covers GET/PUT for the 1:1 scene meta plus POST/DELETE
for the 1:M other-agencies repeating group.
"""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.api_chart_scene import router as scene_router
from epcr_app.db import get_session
from epcr_app.dependencies import get_current_user
from epcr_app.models import Base, Chart
from epcr_app.models_chart_scene import (  # noqa: F401
    ChartScene,
    ChartSceneOtherAgency,
)
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
    app.include_router(scene_router)

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
    r = c.get("/api/v1/epcr/charts/chart-1/scene")
    assert r.status_code == 404


def test_put_creates_then_get_returns(client) -> None:
    c, _ = client
    body = {
        "first_ems_unit_indicator_code": "Yes",
        "incident_location_type_code": "2204001",
        "incident_street_address": "123 Elm",
        "incident_city": "Boise",
        "incident_state": "ID",
        "incident_zip": "83702",
        "number_of_patients": 1,
    }
    r = c.put("/api/v1/epcr/charts/chart-1/scene", json=body)
    assert r.status_code == 200, r.text
    body_out = r.json()
    assert body_out["incident_city"] == "Boise"
    # Default country sticks on first insert.
    assert body_out["incident_country"] == "US"

    g = c.get("/api/v1/epcr/charts/chart-1/scene")
    assert g.status_code == 200
    assert g.json()["incident_state"] == "ID"


def test_put_projects_to_field_values_ledger(client) -> None:
    c, sessionmaker = client
    body = {
        "first_ems_unit_indicator_code": "Yes",
        "incident_location_type_code": "2204001",
        "incident_street_address": "123 Elm",
        "incident_city": "Boise",
        "incident_state": "ID",
        "incident_zip": "83702",
    }
    r = c.put("/api/v1/epcr/charts/chart-1/scene", json=body)
    assert r.status_code == 200, r.text

    async def _check():
        async with sessionmaker() as s:
            rows = (
                await s.execute(
                    select(NemsisFieldValue).where(
                        NemsisFieldValue.chart_id == "chart-1",
                        NemsisFieldValue.section == "eScene",
                    )
                )
            ).scalars().all()
            elements = {r.element_number for r in rows}
            assert {"eScene.01", "eScene.09", "eScene.15", "eScene.17", "eScene.18", "eScene.19"} <= elements

    import asyncio
    asyncio.get_event_loop().run_until_complete(_check())


def test_delete_clears_one_field(client) -> None:
    c, _ = client
    c.put(
        "/api/v1/epcr/charts/chart-1/scene",
        json={"incident_apartment": "Apt 4B", "incident_city": "Boise"},
    )
    r = c.delete("/api/v1/epcr/charts/chart-1/scene/incident_apartment")
    assert r.status_code == 200, r.text
    assert r.json()["incident_apartment"] is None
    assert r.json()["incident_city"] == "Boise"


def test_delete_unknown_field_400(client) -> None:
    c, _ = client
    c.put("/api/v1/epcr/charts/chart-1/scene", json={"incident_city": "Boise"})
    r = c.delete("/api/v1/epcr/charts/chart-1/scene/not_a_column")
    assert r.status_code == 400


def test_put_rejects_unknown_field(client) -> None:
    c, _ = client
    r = c.put(
        "/api/v1/epcr/charts/chart-1/scene",
        json={"not_a_real_field": "x"},
    )
    assert r.status_code == 422


def test_post_other_agency_creates_and_projects(client) -> None:
    c, sessionmaker = client
    r = c.post(
        "/api/v1/epcr/charts/chart-1/scene/other-agencies",
        json={
            "agency_id": "AG-1",
            "other_service_type_code": "2208001",
            "first_to_provide_patient_care_indicator": "Yes",
            "sequence_index": 0,
        },
    )
    assert r.status_code == 201, r.text
    created_id = r.json()["id"]

    async def _check():
        async with sessionmaker() as s:
            rows = (
                await s.execute(
                    select(NemsisFieldValue).where(
                        NemsisFieldValue.chart_id == "chart-1",
                        NemsisFieldValue.section == "eScene",
                        NemsisFieldValue.occurrence_id == created_id,
                    )
                )
            ).scalars().all()
            elements = {r.element_number for r in rows}
            assert {"eScene.03", "eScene.04", "eScene.24"} <= elements

    import asyncio
    asyncio.get_event_loop().run_until_complete(_check())


def test_post_other_agency_duplicate_409(client) -> None:
    c, _ = client
    c.post(
        "/api/v1/epcr/charts/chart-1/scene/other-agencies",
        json={"agency_id": "AG-DUP", "other_service_type_code": "2208001"},
    )
    r = c.post(
        "/api/v1/epcr/charts/chart-1/scene/other-agencies",
        json={"agency_id": "AG-DUP", "other_service_type_code": "2208002"},
    )
    assert r.status_code == 409


def test_delete_other_agency_soft_deletes(client) -> None:
    c, _ = client
    r = c.post(
        "/api/v1/epcr/charts/chart-1/scene/other-agencies",
        json={"agency_id": "AG-DEL", "other_service_type_code": "2208001"},
    )
    row_id = r.json()["id"]
    d = c.delete(f"/api/v1/epcr/charts/chart-1/scene/other-agencies/{row_id}")
    assert d.status_code == 200, d.text
    assert d.json()["deleted_at"] is not None


def test_delete_other_agency_404_on_missing(client) -> None:
    c, _ = client
    r = c.delete("/api/v1/epcr/charts/chart-1/scene/other-agencies/no-such-row")
    assert r.status_code == 404


def test_put_accepts_datetime_field(client) -> None:
    c, _ = client
    arrived = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
    r = c.put(
        "/api/v1/epcr/charts/chart-1/scene",
        json={"initial_responder_arrived_at": arrived.isoformat()},
    )
    assert r.status_code == 200, r.text
    assert r.json()["initial_responder_arrived_at"].startswith("2026-05-10T12:00:00")
