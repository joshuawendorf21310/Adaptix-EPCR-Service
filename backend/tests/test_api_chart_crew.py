"""API tests for the eCrew router (:mod:`epcr_app.api_chart_crew`).

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

from epcr_app.api_chart_crew import router as crew_router
from epcr_app.db import get_session
from epcr_app.dependencies import get_current_user
from epcr_app.models import Base, Chart
from epcr_app.models_chart_crew import ChartCrewMember  # noqa: F401
from epcr_app.models_nemsis_field_values import NemsisFieldValue


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Pre-seed one chart for tenant T-1 and one for T-OTHER.
    async with sessionmaker() as s:
        s.add(
            Chart(
                id="chart-1",
                tenant_id="T-1",
                call_number="C-1",
                created_by_user_id="user-1",
            )
        )
        s.add(
            Chart(
                id="chart-other",
                tenant_id="T-OTHER",
                call_number="C-O",
                created_by_user_id="user-2",
            )
        )
        await s.commit()

    app = FastAPI()
    app.include_router(crew_router)

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


def test_get_returns_empty_list_when_no_crew(client) -> None:
    c, _ = client
    r = c.get("/api/v1/epcr/charts/chart-1/crew")
    assert r.status_code == 200
    assert r.json() == []


def test_post_creates_then_get_lists(client) -> None:
    c, _ = client
    body = {
        "crew_member_id": "EMP-1",
        "crew_member_level_code": "Paramedic",
        "crew_member_response_role_code": "lead",
        "sequence_index": 0,
    }
    r = c.post("/api/v1/epcr/charts/chart-1/crew", json=body)
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["crew_member_id"] == "EMP-1"
    row_id = created["id"]

    g = c.get("/api/v1/epcr/charts/chart-1/crew")
    assert g.status_code == 200
    listing = g.json()
    assert len(listing) == 1
    assert listing[0]["id"] == row_id


def test_post_projects_to_field_values_ledger(client) -> None:
    c, sessionmaker = client
    body = {
        "crew_member_id": "EMP-PROJ",
        "crew_member_level_code": "AEMT",
        "crew_member_response_role_code": "treat",
        "sequence_index": 0,
    }
    r = c.post("/api/v1/epcr/charts/chart-1/crew", json=body)
    assert r.status_code == 201, r.text
    row_id = r.json()["id"]

    async def _check():
        async with sessionmaker() as s:
            rows = (
                await s.execute(
                    select(NemsisFieldValue).where(
                        NemsisFieldValue.chart_id == "chart-1",
                        NemsisFieldValue.section == "eCrew",
                    )
                )
            ).scalars().all()
            elements = {r.element_number for r in rows}
            assert elements == {"eCrew.01", "eCrew.02", "eCrew.03"}
            for r in rows:
                assert r.occurrence_id == row_id

    import asyncio
    asyncio.get_event_loop().run_until_complete(_check())


def test_patch_updates_level_and_role(client) -> None:
    c, _ = client
    create = c.post(
        "/api/v1/epcr/charts/chart-1/crew",
        json={
            "crew_member_id": "EMP-2",
            "crew_member_level_code": "EMT",
            "crew_member_response_role_code": "driver",
            "sequence_index": 0,
        },
    )
    assert create.status_code == 201, create.text
    row_id = create.json()["id"]

    r = c.patch(
        f"/api/v1/epcr/charts/chart-1/crew/{row_id}",
        json={
            "crew_member_level_code": "Paramedic",
            "crew_member_response_role_code": "lead",
            "sequence_index": 2,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["crew_member_level_code"] == "Paramedic"
    assert body["crew_member_response_role_code"] == "lead"
    assert body["sequence_index"] == 2


def test_delete_removes_from_listing(client) -> None:
    c, _ = client
    create = c.post(
        "/api/v1/epcr/charts/chart-1/crew",
        json={
            "crew_member_id": "EMP-3",
            "crew_member_level_code": "EMT",
            "crew_member_response_role_code": "driver",
            "sequence_index": 0,
        },
    )
    assert create.status_code == 201, create.text
    row_id = create.json()["id"]

    r = c.delete(f"/api/v1/epcr/charts/chart-1/crew/{row_id}")
    assert r.status_code == 200, r.text

    listing = c.get("/api/v1/epcr/charts/chart-1/crew").json()
    assert listing == []


def test_patch_unknown_row_404(client) -> None:
    c, _ = client
    r = c.patch(
        "/api/v1/epcr/charts/chart-1/crew/does-not-exist",
        json={"crew_member_level_code": "EMT"},
    )
    assert r.status_code == 404


def test_delete_wrong_tenant_chart_404(client) -> None:
    """A row created under a different tenant must be invisible to T-1.

    The auth override fixes the caller's tenant to T-1, so attempting to
    DELETE a row that lives under chart-other (T-OTHER) must return 404
    because the SQL query is tenant-scoped.
    """
    c, sessionmaker = client

    # Seed a crew row directly under T-OTHER.
    import asyncio
    import uuid

    other_row_id = str(uuid.uuid4())

    async def _seed():
        async with sessionmaker() as s:
            s.add(
                ChartCrewMember(
                    id=other_row_id,
                    tenant_id="T-OTHER",
                    chart_id="chart-other",
                    crew_member_id="EMP-OTHER",
                    crew_member_level_code="EMT",
                    crew_member_response_role_code="driver",
                    sequence_index=0,
                )
            )
            await s.commit()

    asyncio.get_event_loop().run_until_complete(_seed())

    r = c.delete(f"/api/v1/epcr/charts/chart-other/crew/{other_row_id}")
    assert r.status_code == 404


def test_post_rejects_unknown_field(client) -> None:
    c, _ = client
    r = c.post(
        "/api/v1/epcr/charts/chart-1/crew",
        json={
            "crew_member_id": "EMP-X",
            "crew_member_level_code": "EMT",
            "crew_member_response_role_code": "driver",
            "not_a_real_field": "x",
        },
    )
    assert r.status_code == 422


def test_post_duplicate_member_409(client) -> None:
    c, _ = client
    body = {
        "crew_member_id": "EMP-DUP",
        "crew_member_level_code": "EMT",
        "crew_member_response_role_code": "driver",
        "sequence_index": 0,
    }
    r1 = c.post("/api/v1/epcr/charts/chart-1/crew", json=body)
    assert r1.status_code == 201, r1.text
    r2 = c.post("/api/v1/epcr/charts/chart-1/crew", json=body)
    assert r2.status_code == 409
