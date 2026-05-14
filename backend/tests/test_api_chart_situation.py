"""API tests for the eSituation router (:mod:`epcr_app.api_chart_situation`).

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

from epcr_app.api_chart_situation import router as situation_router
from epcr_app.db import get_session
from epcr_app.dependencies import get_current_user
from epcr_app.models import Base, Chart
from epcr_app.models_chart_situation import (  # noqa: F401
    ChartSituation,
    ChartSituationOtherSymptom,
    ChartSituationSecondaryImpression,
)
from epcr_app.models_nemsis_field_values import NemsisFieldValue


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

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
    app.include_router(situation_router)

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


# ---------- 1:1 scalar row ----------


def test_get_returns_404_when_absent(client) -> None:
    c, _ = client
    r = c.get("/api/v1/epcr/charts/chart-1/situation")
    assert r.status_code == 404


def test_put_creates_then_get_returns(client) -> None:
    c, _ = client
    onset = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
    body = {
        "symptom_onset_at": onset.isoformat(),
        "complaint_text": "Chest pain",
        "primary_symptom_code": "R07.9",
        "provider_primary_impression_code": "I21.9",
    }
    r = c.put("/api/v1/epcr/charts/chart-1/situation", json=body)
    assert r.status_code == 200, r.text
    body_out = r.json()
    assert body_out["complaint_text"] == "Chest pain"
    assert body_out["primary_symptom_code"] == "R07.9"

    g = c.get("/api/v1/epcr/charts/chart-1/situation")
    assert g.status_code == 200
    assert g.json()["provider_primary_impression_code"] == "I21.9"


def test_put_projects_to_field_values_ledger(client) -> None:
    c, sessionmaker = client
    body = {
        "complaint_text": "Chest pain",
        "primary_symptom_code": "R07.9",
        "provider_primary_impression_code": "I21.9",
        "initial_patient_acuity_code": "2207003",
    }
    r = c.put("/api/v1/epcr/charts/chart-1/situation", json=body)
    assert r.status_code == 200, r.text

    async def _check():
        async with sessionmaker() as s:
            rows = (
                await s.execute(
                    select(NemsisFieldValue).where(
                        NemsisFieldValue.chart_id == "chart-1",
                        NemsisFieldValue.section == "eSituation",
                    )
                )
            ).scalars().all()
            elements = {r.element_number for r in rows}
            assert {
                "eSituation.04",
                "eSituation.09",
                "eSituation.11",
                "eSituation.13",
            } <= elements

    import asyncio
    asyncio.get_event_loop().run_until_complete(_check())


def test_delete_clears_one_field(client) -> None:
    c, _ = client
    c.put(
        "/api/v1/epcr/charts/chart-1/situation",
        json={"complaint_text": "abc", "primary_symptom_code": "R07.9"},
    )
    r = c.delete("/api/v1/epcr/charts/chart-1/situation/complaint_text")
    assert r.status_code == 200, r.text
    assert r.json()["complaint_text"] is None
    assert r.json()["primary_symptom_code"] == "R07.9"


def test_delete_unknown_field_400(client) -> None:
    c, _ = client
    c.put(
        "/api/v1/epcr/charts/chart-1/situation",
        json={"complaint_text": "abc"},
    )
    r = c.delete("/api/v1/epcr/charts/chart-1/situation/not_a_column")
    assert r.status_code == 400


def test_put_rejects_unknown_field(client) -> None:
    c, _ = client
    r = c.put(
        "/api/v1/epcr/charts/chart-1/situation",
        json={"not_a_real_field": "x"},
    )
    assert r.status_code == 422


# ---------- eSituation.10 Other Associated Symptoms ----------


def test_post_other_symptom_then_list(client) -> None:
    c, _ = client
    r = c.post(
        "/api/v1/epcr/charts/chart-1/situation/other-symptoms",
        json={"symptom_code": "R06.0", "sequence_index": 0},
    )
    assert r.status_code == 201, r.text
    assert r.json()["symptom_code"] == "R06.0"

    g = c.get("/api/v1/epcr/charts/chart-1/situation/other-symptoms")
    assert g.status_code == 200
    assert [row["symptom_code"] for row in g.json()] == ["R06.0"]


def test_post_other_symptom_duplicate_409(client) -> None:
    c, _ = client
    c.post(
        "/api/v1/epcr/charts/chart-1/situation/other-symptoms",
        json={"symptom_code": "R06.0"},
    )
    r = c.post(
        "/api/v1/epcr/charts/chart-1/situation/other-symptoms",
        json={"symptom_code": "R06.0"},
    )
    assert r.status_code == 409


def test_delete_other_symptom_soft_deletes(client) -> None:
    c, _ = client
    created = c.post(
        "/api/v1/epcr/charts/chart-1/situation/other-symptoms",
        json={"symptom_code": "R06.0"},
    ).json()
    r = c.delete(
        f"/api/v1/epcr/charts/chart-1/situation/other-symptoms/{created['id']}"
    )
    assert r.status_code == 200
    g = c.get("/api/v1/epcr/charts/chart-1/situation/other-symptoms")
    assert g.json() == []


def test_post_other_symptom_projects_to_ledger(client) -> None:
    c, sessionmaker = client
    c.post(
        "/api/v1/epcr/charts/chart-1/situation/other-symptoms",
        json={"symptom_code": "R06.0", "sequence_index": 0},
    )

    async def _check():
        async with sessionmaker() as s:
            rows = (
                await s.execute(
                    select(NemsisFieldValue).where(
                        NemsisFieldValue.chart_id == "chart-1",
                        NemsisFieldValue.element_number == "eSituation.10",
                    )
                )
            ).scalars().all()
            assert len(rows) == 1
            assert rows[0].value_json == "R06.0"
            assert rows[0].occurrence_id  # non-empty

    import asyncio
    asyncio.get_event_loop().run_until_complete(_check())


# ---------- eSituation.12 Provider's Secondary Impressions ----------


def test_post_secondary_impression_then_list(client) -> None:
    c, _ = client
    r = c.post(
        "/api/v1/epcr/charts/chart-1/situation/secondary-impressions",
        json={"impression_code": "I50.9", "sequence_index": 0},
    )
    assert r.status_code == 201, r.text
    assert r.json()["impression_code"] == "I50.9"

    g = c.get("/api/v1/epcr/charts/chart-1/situation/secondary-impressions")
    assert g.status_code == 200
    assert [row["impression_code"] for row in g.json()] == ["I50.9"]


def test_post_secondary_impression_duplicate_409(client) -> None:
    c, _ = client
    c.post(
        "/api/v1/epcr/charts/chart-1/situation/secondary-impressions",
        json={"impression_code": "I50.9"},
    )
    r = c.post(
        "/api/v1/epcr/charts/chart-1/situation/secondary-impressions",
        json={"impression_code": "I50.9"},
    )
    assert r.status_code == 409


def test_delete_secondary_impression_soft_deletes(client) -> None:
    c, _ = client
    created = c.post(
        "/api/v1/epcr/charts/chart-1/situation/secondary-impressions",
        json={"impression_code": "I50.9"},
    ).json()
    r = c.delete(
        f"/api/v1/epcr/charts/chart-1/situation/secondary-impressions/{created['id']}"
    )
    assert r.status_code == 200
    g = c.get("/api/v1/epcr/charts/chart-1/situation/secondary-impressions")
    assert g.json() == []


def test_post_secondary_impression_projects_to_ledger(client) -> None:
    c, sessionmaker = client
    c.post(
        "/api/v1/epcr/charts/chart-1/situation/secondary-impressions",
        json={"impression_code": "I50.9"},
    )

    async def _check():
        async with sessionmaker() as s:
            rows = (
                await s.execute(
                    select(NemsisFieldValue).where(
                        NemsisFieldValue.chart_id == "chart-1",
                        NemsisFieldValue.element_number == "eSituation.12",
                    )
                )
            ).scalars().all()
            assert len(rows) == 1
            assert rows[0].value_json == "I50.9"
            assert rows[0].occurrence_id

    import asyncio
    asyncio.get_event_loop().run_until_complete(_check())
