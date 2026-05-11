"""API tests for the eArrest router (:mod:`epcr_app.api_chart_arrest`).

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

from epcr_app.api_chart_arrest import router as arrest_router
from epcr_app.db import get_session
from epcr_app.dependencies import get_current_user
from epcr_app.models import Base, Chart
from epcr_app.models_chart_arrest import ChartArrest  # noqa: F401
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
    app.include_router(arrest_router)

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
    r = c.get("/api/v1/epcr/charts/chart-1/arrest")
    assert r.status_code == 404


def test_put_creates_then_get_returns(client) -> None:
    c, _ = client
    t0 = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
    body = {
        "cardiac_arrest_code": "9512001",
        "etiology_code": "9514001",
        "witnessed_by_codes_json": ["9516001", "9516003"],
        "arrest_at": t0.isoformat(),
        "initial_cpr_at": (t0 + timedelta(minutes=1)).isoformat(),
    }
    r = c.put("/api/v1/epcr/charts/chart-1/arrest", json=body)
    assert r.status_code == 200, r.text
    body_out = r.json()
    assert body_out["cardiac_arrest_code"] == "9512001"
    assert body_out["witnessed_by_codes_json"] == ["9516001", "9516003"]

    g = c.get("/api/v1/epcr/charts/chart-1/arrest")
    assert g.status_code == 200
    assert g.json()["cardiac_arrest_code"] == "9512001"


def test_put_without_cardiac_arrest_code_on_initial_400(client) -> None:
    c, _ = client
    r = c.put(
        "/api/v1/epcr/charts/chart-1/arrest",
        json={"etiology_code": "9514001"},
    )
    assert r.status_code == 400


def test_put_projects_to_field_values_ledger(client) -> None:
    c, sessionmaker = client
    body = {
        "cardiac_arrest_code": "9512001",
        "resuscitation_attempted_codes_json": ["9515003", "9515005"],
        "cpr_type_codes_json": ["9520001"],
        "first_monitored_rhythm_code": "9522001",
    }
    r = c.put("/api/v1/epcr/charts/chart-1/arrest", json=body)
    assert r.status_code == 200, r.text

    async def _check():
        async with sessionmaker() as s:
            rows = (
                await s.execute(
                    select(NemsisFieldValue).where(
                        NemsisFieldValue.chart_id == "chart-1",
                        NemsisFieldValue.section == "eArrest",
                    )
                )
            ).scalars().all()
            elements = {r.element_number for r in rows}
            assert {"eArrest.01", "eArrest.03", "eArrest.09", "eArrest.11"} <= elements
            # eArrest.03 must be expanded to 2 occurrences
            e03 = [r for r in rows if r.element_number == "eArrest.03"]
            assert len(e03) == 2
            assert {r.sequence_index for r in e03} == {0, 1}

    import asyncio
    asyncio.get_event_loop().run_until_complete(_check())


def test_delete_clears_one_field(client) -> None:
    c, _ = client
    c.put(
        "/api/v1/epcr/charts/chart-1/arrest",
        json={
            "cardiac_arrest_code": "9512001",
            "etiology_code": "9514001",
        },
    )
    r = c.delete("/api/v1/epcr/charts/chart-1/arrest/etiology_code")
    assert r.status_code == 200, r.text
    assert r.json()["etiology_code"] is None
    assert r.json()["cardiac_arrest_code"] == "9512001"


def test_delete_unknown_field_400(client) -> None:
    c, _ = client
    c.put(
        "/api/v1/epcr/charts/chart-1/arrest",
        json={"cardiac_arrest_code": "9512001"},
    )
    r = c.delete("/api/v1/epcr/charts/chart-1/arrest/not_a_column")
    assert r.status_code == 400


def test_delete_cardiac_arrest_code_400(client) -> None:
    c, _ = client
    c.put(
        "/api/v1/epcr/charts/chart-1/arrest",
        json={"cardiac_arrest_code": "9512001"},
    )
    r = c.delete("/api/v1/epcr/charts/chart-1/arrest/cardiac_arrest_code")
    assert r.status_code == 400


def test_put_rejects_unknown_field(client) -> None:
    c, _ = client
    r = c.put(
        "/api/v1/epcr/charts/chart-1/arrest",
        json={"cardiac_arrest_code": "9512001", "not_a_real_field": "x"},
    )
    assert r.status_code == 422
