"""API tests for the eDispatch router (:mod:`epcr_app.api_chart_dispatch`).

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

from epcr_app.api_chart_dispatch import router as dispatch_router
from epcr_app.db import get_session
from epcr_app.dependencies import get_current_user
from epcr_app.models import Base, Chart
from epcr_app.models_chart_dispatch import ChartDispatch  # noqa: F401
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
    app.include_router(dispatch_router)

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
    r = c.get("/api/v1/epcr/charts/chart-1/dispatch")
    assert r.status_code == 404


def test_put_creates_then_get_returns(client) -> None:
    c, _ = client
    body = {
        "dispatch_reason_code": "2301001",
        "emd_performed_code": "2302003",
        "dispatch_center_id": "DC-001",
    }
    r = c.put("/api/v1/epcr/charts/chart-1/dispatch", json=body)
    assert r.status_code == 200, r.text
    body_out = r.json()
    assert body_out["dispatch_reason_code"] == "2301001"
    assert body_out["emd_performed_code"] == "2302003"
    assert body_out["dispatch_center_id"] == "DC-001"

    g = c.get("/api/v1/epcr/charts/chart-1/dispatch")
    assert g.status_code == 200
    assert g.json()["dispatch_reason_code"] == "2301001"


def test_put_projects_to_field_values_ledger(client) -> None:
    c, sessionmaker = client
    body = {
        "dispatch_reason_code": "2301001",
        "emd_performed_code": "2302003",
        "emd_determinant_code": "26-D-1",
        "dispatch_priority_code": "2305003",
    }
    r = c.put("/api/v1/epcr/charts/chart-1/dispatch", json=body)
    assert r.status_code == 200, r.text

    async def _check():
        async with sessionmaker() as s:
            rows = (
                await s.execute(
                    select(NemsisFieldValue).where(
                        NemsisFieldValue.chart_id == "chart-1",
                        NemsisFieldValue.section == "eDispatch",
                    )
                )
            ).scalars().all()
            elements = {r.element_number for r in rows}
            assert {
                "eDispatch.01",
                "eDispatch.02",
                "eDispatch.03",
                "eDispatch.05",
            } <= elements

    import asyncio
    asyncio.get_event_loop().run_until_complete(_check())


def test_delete_clears_one_field(client) -> None:
    c, _ = client
    c.put(
        "/api/v1/epcr/charts/chart-1/dispatch",
        json={
            "dispatch_reason_code": "2301001",
            "dispatch_center_id": "DC-001",
        },
    )
    r = c.delete("/api/v1/epcr/charts/chart-1/dispatch/dispatch_reason_code")
    assert r.status_code == 200, r.text
    assert r.json()["dispatch_reason_code"] is None
    assert r.json()["dispatch_center_id"] == "DC-001"


def test_delete_unknown_field_400(client) -> None:
    c, _ = client
    c.put(
        "/api/v1/epcr/charts/chart-1/dispatch",
        json={"dispatch_reason_code": "2301001"},
    )
    r = c.delete("/api/v1/epcr/charts/chart-1/dispatch/not_a_column")
    assert r.status_code == 400


def test_put_rejects_unknown_field(client) -> None:
    c, _ = client
    r = c.put(
        "/api/v1/epcr/charts/chart-1/dispatch",
        json={"not_a_real_field": "value"},
    )
    assert r.status_code == 422
