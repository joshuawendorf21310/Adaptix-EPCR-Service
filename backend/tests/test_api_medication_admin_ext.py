"""API tests for the eMedications-additions router.

Hermetic: in-memory SQLite, FastAPI TestClient, dependency-overridden
auth and session.
"""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.api_medication_admin_ext import router as ext_router
from epcr_app.db import get_session
from epcr_app.dependencies import get_current_user
from epcr_app.models import Base, Chart, MedicationAdministration
from epcr_app.models_medication_admin_ext import (  # noqa: F401
    MedicationAdminExt,
    MedicationComplication,
)
from epcr_app.models_nemsis_field_values import NemsisFieldValue


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Pre-seed one chart and one MedicationAdministration for tenant T-1.
    async with sessionmaker() as s:
        chart = Chart(
            id="chart-1",
            tenant_id="T-1",
            call_number="C-1",
            created_by_user_id="user-1",
        )
        s.add(chart)
        med = MedicationAdministration(
            id="med-1",
            tenant_id="T-1",
            chart_id="chart-1",
            medication_name="Epinephrine",
            route="IV",
            indication="Cardiac arrest",
            administered_at=datetime.now(UTC),
            administered_by_user_id="user-1",
        )
        s.add(med)
        await s.commit()

    app = FastAPI()
    app.include_router(ext_router)

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


BASE = "/api/v1/epcr/charts/chart-1/medications/med-1/ext"


def test_get_returns_404_when_absent(client) -> None:
    c, _ = client
    r = c.get(BASE)
    assert r.status_code == 404


def test_put_creates_then_get_returns(client) -> None:
    c, _ = client
    body = {
        "prior_to_ems_indicator_code": "9923001",
        "ems_professional_type_code": "9924007",
        "authorization_code": "9908001",
        "authorizing_physician_last_name": "Strange",
        "authorizing_physician_first_name": "Stephen",
        "by_another_unit_indicator_code": "9923003",
    }
    r = c.put(BASE, json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["prior_to_ems_indicator_code"] == "9923001"
    assert out["ems_professional_type_code"] == "9924007"
    assert out["authorizing_physician_last_name"] == "Strange"

    g = c.get(BASE)
    assert g.status_code == 200
    body_out = g.json()
    assert body_out["ext"]["ems_professional_type_code"] == "9924007"
    assert body_out["complications"] == []


def test_put_projects_to_field_values_ledger(client) -> None:
    c, sessionmaker = client
    body = {
        "prior_to_ems_indicator_code": "9923001",
        "ems_professional_type_code": "9924007",
        "authorizing_physician_last_name": "Strange",
        "authorizing_physician_first_name": "Stephen",
    }
    r = c.put(BASE, json=body)
    assert r.status_code == 200, r.text

    async def _check():
        async with sessionmaker() as s:
            rows = (
                await s.execute(
                    select(NemsisFieldValue).where(
                        NemsisFieldValue.chart_id == "chart-1",
                        NemsisFieldValue.section == "eMedications",
                    )
                )
            ).scalars().all()
            elements = {r.element_number for r in rows}
            assert {"eMedications.02", "eMedications.10", "eMedications.12"} <= elements

    import asyncio
    asyncio.get_event_loop().run_until_complete(_check())


def test_post_complication_then_projection(client) -> None:
    c, sessionmaker = client
    r = c.post(
        f"{BASE}/complications",
        json={"complication_code": "9925003", "sequence_index": 0},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["complication_code"] == "9925003"

    g = c.get(BASE)
    assert g.status_code == 200
    assert len(g.json()["complications"]) == 1

    async def _check():
        async with sessionmaker() as s:
            rows = (
                await s.execute(
                    select(NemsisFieldValue).where(
                        NemsisFieldValue.chart_id == "chart-1",
                        NemsisFieldValue.element_number == "eMedications.08",
                    )
                )
            ).scalars().all()
            assert len(rows) == 1
            assert rows[0].occurrence_id == "med-1-comp-0"

    import asyncio
    asyncio.get_event_loop().run_until_complete(_check())


def test_delete_complication(client) -> None:
    c, _ = client
    add = c.post(
        f"{BASE}/complications",
        json={"complication_code": "9925003", "sequence_index": 0},
    )
    assert add.status_code == 201, add.text
    comp_id = add.json()["id"]

    r = c.delete(f"{BASE}/complications/{comp_id}")
    assert r.status_code == 200, r.text
    assert r.json()["removed"] is True


def test_delete_unknown_complication_404(client) -> None:
    c, _ = client
    r = c.delete(f"{BASE}/complications/does-not-exist")
    assert r.status_code == 404


def test_put_rejects_unknown_field(client) -> None:
    c, _ = client
    r = c.put(BASE, json={"not_a_real_field": "x"})
    assert r.status_code == 422


def test_post_complication_rejects_empty_code(client) -> None:
    c, _ = client
    r = c.post(f"{BASE}/complications", json={"complication_code": ""})
    # Either pydantic min_length (422) or service-side 400 is acceptable;
    # both signal validation rejection.
    assert r.status_code in (400, 422)
