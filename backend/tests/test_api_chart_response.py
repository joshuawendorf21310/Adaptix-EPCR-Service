"""API tests for the eResponse router (:mod:`epcr_app.api_chart_response`).

Hermetic: in-memory SQLite, FastAPI TestClient, dependency-overridden
auth and session.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.api_chart_response import router as response_router
from epcr_app.db import get_session
from epcr_app.dependencies import get_current_user
from epcr_app.models import Base, Chart
from epcr_app.models_chart_response import (  # noqa: F401
    ChartResponse,
    ChartResponseDelay,
)
from epcr_app.models_nemsis_field_values import NemsisFieldValue


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Pre-seed one chart for tenant T-1.
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
    app.include_router(response_router)

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
    r = c.get("/api/v1/epcr/charts/chart-1/response")
    assert r.status_code == 404


def test_put_creates_then_get_returns(client) -> None:
    c, _ = client
    body = {
        "agency_number": "A123",
        "agency_name": "Adaptix EMS",
        "type_of_service_requested_code": "2205001",
        "unit_transport_capability_code": "2208005",
        "unit_vehicle_number": "MEDIC-7",
        "unit_call_sign": "M7",
        "response_mode_to_scene_code": "2235003",
        "additional_response_descriptors_json": ["X1", "X2"],
    }
    r = c.put("/api/v1/epcr/charts/chart-1/response", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["meta"]["agency_number"] == "A123"
    assert out["meta"]["additional_response_descriptors_json"] == ["X1", "X2"]
    assert "delays_by_kind" in out

    g = c.get("/api/v1/epcr/charts/chart-1/response")
    assert g.status_code == 200
    assert g.json()["meta"]["agency_name"] == "Adaptix EMS"


def test_put_projects_to_field_values_ledger(client) -> None:
    c, sessionmaker = client
    body = {
        "agency_number": "A123",
        "agency_name": "Adaptix EMS",
        "type_of_service_requested_code": "2205001",
        "unit_vehicle_number": "MEDIC-7",
        "unit_call_sign": "M7",
        "response_mode_to_scene_code": "2235003",
        "vehicle_dispatch_lat": 37.7749,
        "vehicle_dispatch_long": -122.4194,
    }
    r = c.put("/api/v1/epcr/charts/chart-1/response", json=body)
    assert r.status_code == 200, r.text

    async def _check():
        async with sessionmaker() as s:
            rows = (
                await s.execute(
                    select(NemsisFieldValue).where(
                        NemsisFieldValue.chart_id == "chart-1",
                        NemsisFieldValue.section == "eResponse",
                    )
                )
            ).scalars().all()
            elements = {r.element_number for r in rows}
            assert {
                "eResponse.01",
                "eResponse.02",
                "eResponse.05",
                "eResponse.13",
                "eResponse.14",
                "eResponse.17",
                "eResponse.23",
            } <= elements

    import asyncio
    asyncio.get_event_loop().run_until_complete(_check())


def test_post_delay_creates_row(client) -> None:
    c, _ = client
    r = c.post(
        "/api/v1/epcr/charts/chart-1/response/delays",
        json={"kind": "dispatch", "code": "D1"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["delay_kind"] == "dispatch"
    assert body["delay_code"] == "D1"

    # Reading back via GET shows it grouped.
    g = c.get("/api/v1/epcr/charts/chart-1/response")
    assert g.status_code == 200
    delays = g.json()["delays_by_kind"]
    assert len(delays["dispatch"]) == 1
    assert delays["dispatch"][0]["delay_code"] == "D1"


def test_post_delay_rejects_unknown_kind(client) -> None:
    c, _ = client
    r = c.post(
        "/api/v1/epcr/charts/chart-1/response/delays",
        json={"kind": "not_a_real_kind", "code": "X"},
    )
    assert r.status_code == 400


def test_post_delay_rejects_duplicate(client) -> None:
    c, _ = client
    c.post(
        "/api/v1/epcr/charts/chart-1/response/delays",
        json={"kind": "scene", "code": "S1"},
    )
    r = c.post(
        "/api/v1/epcr/charts/chart-1/response/delays",
        json={"kind": "scene", "code": "S1"},
    )
    assert r.status_code == 409


def test_delete_delay_soft_deletes(client) -> None:
    c, _ = client
    # Seed metadata so GET still returns 200 once the only delay is deleted.
    c.put("/api/v1/epcr/charts/chart-1/response", json={"agency_number": "A1"})

    created = c.post(
        "/api/v1/epcr/charts/chart-1/response/delays",
        json={"kind": "transport", "code": "T1"},
    )
    assert created.status_code == 201, created.text
    delay_id = created.json()["id"]

    r = c.delete(f"/api/v1/epcr/charts/chart-1/response/delays/{delay_id}")
    assert r.status_code == 200, r.text
    assert r.json()["deleted_at"] is not None

    g = c.get("/api/v1/epcr/charts/chart-1/response")
    assert g.status_code == 200
    assert g.json()["delays_by_kind"]["transport"] == []


def test_delete_delay_not_found(client) -> None:
    c, _ = client
    # Need a row in chart_response so the chart isn't 404 globally.
    c.put(
        "/api/v1/epcr/charts/chart-1/response",
        json={"agency_number": "A1"},
    )
    r = c.delete("/api/v1/epcr/charts/chart-1/response/delays/does-not-exist")
    assert r.status_code == 404


def test_put_rejects_unknown_field(client) -> None:
    c, _ = client
    r = c.put(
        "/api/v1/epcr/charts/chart-1/response",
        json={"not_a_real_field": "x"},
    )
    assert r.status_code == 422


def test_post_delay_projects_to_ledger(client) -> None:
    c, sessionmaker = client
    r = c.post(
        "/api/v1/epcr/charts/chart-1/response/delays",
        json={"kind": "turn_around", "code": "TA1"},
    )
    assert r.status_code == 201, r.text

    async def _check():
        async with sessionmaker() as s:
            rows = (
                await s.execute(
                    select(NemsisFieldValue).where(
                        NemsisFieldValue.chart_id == "chart-1",
                        NemsisFieldValue.element_number == "eResponse.12",
                    )
                )
            ).scalars().all()
            assert len(rows) == 1
            assert rows[0].occurrence_id  # delay.id

    import asyncio
    asyncio.get_event_loop().run_until_complete(_check())
