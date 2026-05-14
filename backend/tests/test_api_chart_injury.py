"""API tests for the eInjury router (:mod:`epcr_app.api_chart_injury`).

Hermetic: in-memory SQLite, FastAPI TestClient, dependency-overridden
auth and session.
"""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.api_chart_injury import router as injury_router
from epcr_app.db import get_session
from epcr_app.dependencies import get_current_user
from epcr_app.models import Base, Chart
from epcr_app.models_chart_injury import ChartInjury, ChartInjuryAcn  # noqa: F401
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
    app.include_router(injury_router)

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
    r = c.get("/api/v1/epcr/charts/chart-1/injury")
    assert r.status_code == 404


def test_put_injury_creates_then_get_returns_merged(client) -> None:
    c, _ = client
    body = {
        "cause_of_injury_codes_json": ["3030001", "3030003"],
        "mechanism_of_injury_code": "3040001",
        "height_of_fall_feet": 12.5,
    }
    r = c.put("/api/v1/epcr/charts/chart-1/injury", json=body)
    assert r.status_code == 200, r.text
    body_out = r.json()
    assert body_out["mechanism_of_injury_code"] == "3040001"
    assert body_out["height_of_fall_feet"] == 12.5

    g = c.get("/api/v1/epcr/charts/chart-1/injury")
    assert g.status_code == 200
    merged = g.json()
    assert merged["injury"]["mechanism_of_injury_code"] == "3040001"
    assert merged["acn"] is None


def test_put_acn_requires_parent_injury_409(client) -> None:
    c, _ = client
    r = c.put(
        "/api/v1/epcr/charts/chart-1/injury/acn",
        json={"acn_system_company": "Acme"},
    )
    assert r.status_code == 409, r.text


def test_put_acn_after_injury(client) -> None:
    c, _ = client
    c.put("/api/v1/epcr/charts/chart-1/injury", json={"mechanism_of_injury_code": "3040001"})

    t0 = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
    r = c.put(
        "/api/v1/epcr/charts/chart-1/injury/acn",
        json={
            "acn_system_company": "Acme Telematics",
            "acn_incident_at": t0.isoformat(),
            "acn_delta_velocity": 42.5,
            "acn_vehicle_model_year": 2024,
        },
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["acn_system_company"] == "Acme Telematics"
    assert out["acn_delta_velocity"] == 42.5

    g = c.get("/api/v1/epcr/charts/chart-1/injury")
    assert g.status_code == 200
    merged = g.json()
    assert merged["acn"]["acn_system_company"] == "Acme Telematics"


def test_put_projects_injury_to_field_values_ledger(client) -> None:
    c, sessionmaker = client
    body = {
        "cause_of_injury_codes_json": ["3030001", "3030003"],
        "mechanism_of_injury_code": "3040001",
        "trauma_triage_high_codes_json": ["3050001"],
    }
    r = c.put("/api/v1/epcr/charts/chart-1/injury", json=body)
    assert r.status_code == 200, r.text

    async def _check():
        async with sessionmaker() as s:
            rows = (
                await s.execute(
                    select(NemsisFieldValue).where(
                        NemsisFieldValue.chart_id == "chart-1",
                        NemsisFieldValue.section == "eInjury",
                    )
                )
            ).scalars().all()
            elements = [r.element_number for r in rows]
            # 2 cause + 1 mechanism + 1 high trauma triage = 4 rows
            assert elements.count("eInjury.01") == 2
            assert elements.count("eInjury.02") == 1
            assert elements.count("eInjury.03") == 1

    import asyncio
    asyncio.get_event_loop().run_until_complete(_check())


def test_put_projects_acn_to_field_values_with_group_path(client) -> None:
    c, sessionmaker = client
    c.put("/api/v1/epcr/charts/chart-1/injury", json={"mechanism_of_injury_code": "3040001"})
    r = c.put(
        "/api/v1/epcr/charts/chart-1/injury/acn",
        json={"acn_system_company": "Acme", "acn_delta_velocity": 30.5},
    )
    assert r.status_code == 200, r.text

    async def _check():
        async with sessionmaker() as s:
            rows = (
                await s.execute(
                    select(NemsisFieldValue).where(
                        NemsisFieldValue.chart_id == "chart-1",
                        NemsisFieldValue.section == "eInjury",
                        NemsisFieldValue.group_path == "eInjury.AutomatedCrashNotificationGroup",
                    )
                )
            ).scalars().all()
            elements = {r.element_number for r in rows}
            assert {"eInjury.11", "eInjury.22"} <= elements

    import asyncio
    asyncio.get_event_loop().run_until_complete(_check())


def test_delete_clears_one_injury_field(client) -> None:
    c, _ = client
    c.put(
        "/api/v1/epcr/charts/chart-1/injury",
        json={"mechanism_of_injury_code": "3040001", "airbag_deployment_code": "3070001"},
    )
    r = c.delete("/api/v1/epcr/charts/chart-1/injury/mechanism_of_injury_code")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["mechanism_of_injury_code"] is None
    assert out["airbag_deployment_code"] == "3070001"


def test_delete_clears_one_acn_field(client) -> None:
    c, _ = client
    c.put("/api/v1/epcr/charts/chart-1/injury", json={"mechanism_of_injury_code": "3040001"})
    c.put(
        "/api/v1/epcr/charts/chart-1/injury/acn",
        json={"acn_system_company": "Acme", "acn_delta_velocity": 30.5},
    )
    r = c.delete(
        "/api/v1/epcr/charts/chart-1/injury/acn_system_company?block=acn"
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["acn_system_company"] is None
    assert out["acn_delta_velocity"] == 30.5


def test_delete_unknown_field_400(client) -> None:
    c, _ = client
    c.put("/api/v1/epcr/charts/chart-1/injury", json={"mechanism_of_injury_code": "3040001"})
    r = c.delete("/api/v1/epcr/charts/chart-1/injury/not_a_column")
    assert r.status_code == 400


def test_delete_unknown_block_400(client) -> None:
    c, _ = client
    c.put("/api/v1/epcr/charts/chart-1/injury", json={"mechanism_of_injury_code": "3040001"})
    r = c.delete(
        "/api/v1/epcr/charts/chart-1/injury/mechanism_of_injury_code?block=bogus"
    )
    assert r.status_code == 400


def test_put_rejects_unknown_field(client) -> None:
    c, _ = client
    r = c.put(
        "/api/v1/epcr/charts/chart-1/injury",
        json={"not_a_real_field": "x"},
    )
    assert r.status_code == 422
