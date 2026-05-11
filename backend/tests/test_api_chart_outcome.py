"""API tests for the eOutcome router (:mod:`epcr_app.api_chart_outcome`).

Hermetic: in-memory SQLite, FastAPI TestClient, dependency-overridden
auth and session.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.api_chart_outcome import router as outcome_router
from epcr_app.db import get_session
from epcr_app.dependencies import get_current_user
from epcr_app.models import Base, Chart
from epcr_app.models_chart_outcome import ChartOutcome  # noqa: F401
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
    app.include_router(outcome_router)

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
    r = c.get("/api/v1/epcr/charts/chart-1/outcome")
    assert r.status_code == 404


def test_put_creates_then_get_returns(client) -> None:
    c, _ = client
    t0 = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
    body = {
        "emergency_department_disposition_code": "4209001",
        "hospital_disposition_code": "4210001",
        "emergency_department_diagnosis_codes_json": ["I21.4", "E11.9"],
        "hospital_length_of_stay_days": 5,
        "icu_length_of_stay_days": 2,
        "emergency_department_arrival_at": t0.isoformat(),
        "hospital_discharge_at": (t0 + timedelta(days=5)).isoformat(),
        "medical_record_number": "MRN-0001",
        "referred_to_facility_name": "St Mercy",
    }
    r = c.put("/api/v1/epcr/charts/chart-1/outcome", json=body)
    assert r.status_code == 200, r.text
    body_out = r.json()
    assert body_out["emergency_department_disposition_code"] == "4209001"
    assert body_out["emergency_department_diagnosis_codes_json"] == ["I21.4", "E11.9"]
    assert body_out["hospital_length_of_stay_days"] == 5

    g = c.get("/api/v1/epcr/charts/chart-1/outcome")
    assert g.status_code == 200
    assert g.json()["medical_record_number"] == "MRN-0001"


def test_put_projects_to_field_values_ledger(client) -> None:
    c, sessionmaker = client
    body = {
        "emergency_department_disposition_code": "4209001",
        "emergency_department_diagnosis_codes_json": ["I21.4", "E11.9", "J18.9"],
        "cause_of_death_codes_json": ["I46.9"],
        "hospital_length_of_stay_days": 5,
    }
    r = c.put("/api/v1/epcr/charts/chart-1/outcome", json=body)
    assert r.status_code == 200, r.text

    async def _check():
        async with sessionmaker() as s:
            rows = (
                await s.execute(
                    select(NemsisFieldValue).where(
                        NemsisFieldValue.chart_id == "chart-1",
                        NemsisFieldValue.section == "eOutcome",
                    )
                )
            ).scalars().all()
            elements = {r.element_number for r in rows}
            assert {"eOutcome.01", "eOutcome.03", "eOutcome.16", "eOutcome.19"} <= elements
            # eOutcome.03 must be expanded to 3 occurrences
            e03 = [r for r in rows if r.element_number == "eOutcome.03"]
            assert len(e03) == 3
            assert {r.sequence_index for r in e03} == {0, 1, 2}

    import asyncio
    asyncio.get_event_loop().run_until_complete(_check())


def test_delete_clears_one_field(client) -> None:
    c, _ = client
    c.put(
        "/api/v1/epcr/charts/chart-1/outcome",
        json={
            "emergency_department_disposition_code": "4209001",
            "hospital_disposition_code": "4210001",
        },
    )
    r = c.delete(
        "/api/v1/epcr/charts/chart-1/outcome/emergency_department_disposition_code"
    )
    assert r.status_code == 200, r.text
    assert r.json()["emergency_department_disposition_code"] is None
    assert r.json()["hospital_disposition_code"] == "4210001"


def test_delete_unknown_field_400(client) -> None:
    c, _ = client
    c.put(
        "/api/v1/epcr/charts/chart-1/outcome",
        json={"hospital_disposition_code": "4210001"},
    )
    r = c.delete("/api/v1/epcr/charts/chart-1/outcome/not_a_column")
    assert r.status_code == 400


def test_put_rejects_unknown_field(client) -> None:
    c, _ = client
    r = c.put(
        "/api/v1/epcr/charts/chart-1/outcome",
        json={"not_a_real_field": "x"},
    )
    assert r.status_code == 422
