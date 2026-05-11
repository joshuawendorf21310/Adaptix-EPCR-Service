"""API tests for the eHistory router (:mod:`epcr_app.api_chart_history`).

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

from epcr_app.api_chart_history import router as history_router
from epcr_app.db import get_session
from epcr_app.dependencies import get_current_user
from epcr_app.models import Base, Chart
from epcr_app.models_chart_history import (  # noqa: F401 - register tables
    ChartHistoryAllergy,
    ChartHistoryCurrentMedication,
    ChartHistoryImmunization,
    ChartHistoryMeta,
    ChartHistorySurgical,
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
    app.include_router(history_router)

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


def test_get_returns_empty_composite_initially(client) -> None:
    c, _ = client
    r = c.get("/api/v1/epcr/charts/chart-1/history")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["meta"] is None
    assert body["allergies"] == []
    assert body["surgical"] == []
    assert body["current_medications"] == []
    assert body["immunizations"] == []


def test_put_meta_creates_then_get_returns(client) -> None:
    c, _ = client
    t0 = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
    body = {
        "practitioner_last_name": "Doe",
        "practitioner_first_name": "Jane",
        "barriers_to_care_codes_json": ["8801001"],
        "last_oral_intake_at": t0.isoformat(),
    }
    r = c.put("/api/v1/epcr/charts/chart-1/history/meta", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["practitioner_last_name"] == "Doe"

    g = c.get("/api/v1/epcr/charts/chart-1/history")
    assert g.status_code == 200
    assert g.json()["meta"]["practitioner_last_name"] == "Doe"


def test_put_meta_projects_to_field_values_ledger(client) -> None:
    c, sessionmaker = client
    body = {
        "practitioner_last_name": "Doe",
        "barriers_to_care_codes_json": ["8801001", "8801003"],
        "pregnancy_code": "3535005",
    }
    r = c.put("/api/v1/epcr/charts/chart-1/history/meta", json=body)
    assert r.status_code == 200, r.text

    async def _check():
        async with sessionmaker() as s:
            rows = (
                await s.execute(
                    select(NemsisFieldValue).where(
                        NemsisFieldValue.chart_id == "chart-1",
                        NemsisFieldValue.section == "eHistory",
                    )
                )
            ).scalars().all()
            elements = {r.element_number for r in rows}
            assert "eHistory.02" in elements
            assert "eHistory.18" in elements
            # Two barriers entries -> at least 2 rows for eHistory.01
            count_01 = sum(1 for r in rows if r.element_number == "eHistory.01")
            assert count_01 == 2

    import asyncio
    asyncio.get_event_loop().run_until_complete(_check())


def test_post_allergy_then_delete(client) -> None:
    c, _ = client
    r = c.post(
        "/api/v1/epcr/charts/chart-1/history/allergies",
        json={"allergy_kind": "medication", "allergy_code": "RX-1", "allergy_text": "PCN"},
    )
    assert r.status_code == 201, r.text
    row_id = r.json()["id"]

    g = c.get("/api/v1/epcr/charts/chart-1/history")
    assert any(a["id"] == row_id for a in g.json()["allergies"])

    d = c.delete(f"/api/v1/epcr/charts/chart-1/history/allergies/{row_id}")
    assert d.status_code == 200, d.text
    g2 = c.get("/api/v1/epcr/charts/chart-1/history")
    assert g2.json()["allergies"] == []


def test_post_allergy_rejects_invalid_kind(client) -> None:
    c, _ = client
    r = c.post(
        "/api/v1/epcr/charts/chart-1/history/allergies",
        json={"allergy_kind": "bogus", "allergy_code": "X"},
    )
    assert r.status_code == 400


def test_post_surgical_then_delete(client) -> None:
    c, _ = client
    r = c.post(
        "/api/v1/epcr/charts/chart-1/history/surgical",
        json={"condition_code": "I10", "condition_text": "HTN"},
    )
    assert r.status_code == 201, r.text
    row_id = r.json()["id"]

    d = c.delete(f"/api/v1/epcr/charts/chart-1/history/surgical/{row_id}")
    assert d.status_code == 200, d.text


def test_post_medication_then_delete_and_projection(client) -> None:
    c, sessionmaker = client
    r = c.post(
        "/api/v1/epcr/charts/chart-1/history/medications",
        json={
            "drug_code": "RXN-1",
            "dose_value": "10",
            "dose_unit_code": "mg",
            "route_code": "PO",
            "frequency_code": "BID",
        },
    )
    assert r.status_code == 201, r.text
    row_id = r.json()["id"]

    async def _check_projection():
        async with sessionmaker() as s:
            rows = (
                await s.execute(
                    select(NemsisFieldValue).where(
                        NemsisFieldValue.chart_id == "chart-1",
                        NemsisFieldValue.section == "eHistory",
                    )
                )
            ).scalars().all()
            elements = {r.element_number for r in rows}
            assert {"eHistory.12", "eHistory.13", "eHistory.14",
                    "eHistory.15", "eHistory.20"} <= elements
            for r in rows:
                if r.element_number in {"eHistory.12", "eHistory.13",
                                        "eHistory.14", "eHistory.15", "eHistory.20"}:
                    assert r.group_path == "eHistory.CurrentMedicationGroup"
                    assert r.occurrence_id == row_id

    import asyncio
    asyncio.get_event_loop().run_until_complete(_check_projection())

    d = c.delete(f"/api/v1/epcr/charts/chart-1/history/medications/{row_id}")
    assert d.status_code == 200, d.text


def test_post_immunization_then_delete(client) -> None:
    c, _ = client
    r = c.post(
        "/api/v1/epcr/charts/chart-1/history/immunizations",
        json={"immunization_type_code": "COVID19", "immunization_year": 2024},
    )
    assert r.status_code == 201, r.text
    row_id = r.json()["id"]

    d = c.delete(f"/api/v1/epcr/charts/chart-1/history/immunizations/{row_id}")
    assert d.status_code == 200, d.text


def test_put_meta_rejects_unknown_field(client) -> None:
    c, _ = client
    r = c.put(
        "/api/v1/epcr/charts/chart-1/history/meta",
        json={"not_a_real_field": "x"},
    )
    assert r.status_code == 422


def test_delete_unknown_row_returns_404(client) -> None:
    c, _ = client
    r = c.delete("/api/v1/epcr/charts/chart-1/history/allergies/does-not-exist")
    assert r.status_code == 404
