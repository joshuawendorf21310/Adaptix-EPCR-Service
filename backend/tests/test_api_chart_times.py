"""API tests for the eTimes router (:mod:`epcr_app.api_chart_times`).

Hermetic: in-memory SQLite, FastAPI TestClient, dependency-overridden
auth and session.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.api_chart_times import router as times_router
from epcr_app.db import get_session
from epcr_app.dependencies import get_current_user
from epcr_app.models import Base, Chart
from epcr_app.models_chart_times import ChartTimes  # noqa: F401
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
    app.include_router(times_router)

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
    r = c.get("/api/v1/epcr/charts/chart-1/times")
    assert r.status_code == 404


def test_put_creates_then_get_returns(client) -> None:
    c, _ = client
    t0 = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
    body = {
        "psap_call_at": t0.isoformat(),
        "unit_on_scene_at": (t0 + timedelta(minutes=5)).isoformat(),
        "unit_left_scene_at": (t0 + timedelta(minutes=15)).isoformat(),
    }
    r = c.put("/api/v1/epcr/charts/chart-1/times", json=body)
    assert r.status_code == 200, r.text
    body_out = r.json()
    assert body_out["psap_call_at"] is not None
    assert body_out["unit_on_scene_at"] is not None

    g = c.get("/api/v1/epcr/charts/chart-1/times")
    assert g.status_code == 200
    assert g.json()["psap_call_at"] is not None


def test_put_projects_to_field_values_ledger(client) -> None:
    c, sessionmaker = client
    t0 = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
    body = {
        "psap_call_at": t0.isoformat(),
        "unit_notified_by_dispatch_at": (t0 + timedelta(seconds=10)).isoformat(),
        "unit_en_route_at": (t0 + timedelta(minutes=1)).isoformat(),
        "unit_on_scene_at": (t0 + timedelta(minutes=5)).isoformat(),
    }
    r = c.put("/api/v1/epcr/charts/chart-1/times", json=body)
    assert r.status_code == 200, r.text

    async def _check():
        async with sessionmaker() as s:
            rows = (
                await s.execute(
                    select(NemsisFieldValue).where(
                        NemsisFieldValue.chart_id == "chart-1",
                        NemsisFieldValue.section == "eTimes",
                    )
                )
            ).scalars().all()
            elements = {r.element_number for r in rows}
            assert {"eTimes.01", "eTimes.03", "eTimes.05", "eTimes.06"} <= elements

    import asyncio
    asyncio.get_event_loop().run_until_complete(_check())


def test_delete_clears_one_field(client) -> None:
    c, _ = client
    t0 = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
    c.put(
        "/api/v1/epcr/charts/chart-1/times",
        json={"psap_call_at": t0.isoformat(), "unit_on_scene_at": t0.isoformat()},
    )
    r = c.delete("/api/v1/epcr/charts/chart-1/times/psap_call_at")
    assert r.status_code == 200, r.text
    assert r.json()["psap_call_at"] is None
    assert r.json()["unit_on_scene_at"] is not None


def test_delete_unknown_field_400(client) -> None:
    c, _ = client
    t0 = datetime.now(UTC)
    c.put("/api/v1/epcr/charts/chart-1/times", json={"psap_call_at": t0.isoformat()})
    r = c.delete("/api/v1/epcr/charts/chart-1/times/not_a_column")
    assert r.status_code == 400


def test_put_rejects_unknown_field(client) -> None:
    c, _ = client
    r = c.put(
        "/api/v1/epcr/charts/chart-1/times",
        json={"not_a_real_field": "2026-01-01T00:00:00+00:00"},
    )
    assert r.status_code == 422
