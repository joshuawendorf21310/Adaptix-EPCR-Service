"""API tests for the ePatient extension router."""
from __future__ import annotations

from types import SimpleNamespace

import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.api_patient_profile_ext import router as patient_ext_router
from epcr_app.db import get_session
from epcr_app.dependencies import get_current_user
from epcr_app.models import Base, Chart
from epcr_app.models_nemsis_field_values import NemsisFieldValue
from epcr_app.models_patient_profile_ext import (  # noqa: F401 - register tables
    PatientHomeAddress,
    PatientLanguage,
    PatientPhoneNumber,
    PatientProfileNemsisExt,
    PatientRace,
)


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
    app.include_router(patient_ext_router)

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


def test_get_returns_empty_snapshot_when_nothing_recorded(client) -> None:
    c, _ = client
    r = c.get("/api/v1/epcr/charts/chart-1/patient-ext")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scalar"] is None
    assert body["home_address"] is None
    assert body["races"] == []
    assert body["languages"] == []
    assert body["phones"] == []


def test_put_scalar_creates_then_get_returns(client) -> None:
    c, _ = client
    body = {
        "ems_patient_id": "EMS-1",
        "sex_nemsis_code": "9906001",
        "name_suffix": "JR",
        "email_address": "p@example.com",
    }
    r = c.put("/api/v1/epcr/charts/chart-1/patient-ext/scalar", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["ems_patient_id"] == "EMS-1"
    assert r.json()["sex_nemsis_code"] == "9906001"

    g = c.get("/api/v1/epcr/charts/chart-1/patient-ext")
    assert g.status_code == 200
    assert g.json()["scalar"]["ems_patient_id"] == "EMS-1"


def test_put_scalar_projects_to_ledger(client) -> None:
    c, sessionmaker = client
    r = c.put(
        "/api/v1/epcr/charts/chart-1/patient-ext/scalar",
        json={"ems_patient_id": "EMS-2", "sex_nemsis_code": "9906001"},
    )
    assert r.status_code == 200, r.text

    async def _check():
        async with sessionmaker() as s:
            rows = (
                await s.execute(
                    select(NemsisFieldValue).where(
                        NemsisFieldValue.chart_id == "chart-1",
                        NemsisFieldValue.section == "ePatient",
                    )
                )
            ).scalars().all()
            elements = {r.element_number for r in rows}
            assert "ePatient.01" in elements
            assert "ePatient.25" in elements

    import asyncio
    asyncio.get_event_loop().run_until_complete(_check())


def test_put_home_address(client) -> None:
    c, _ = client
    r = c.put(
        "/api/v1/epcr/charts/chart-1/patient-ext/home-address",
        json={
            "home_street_address": "123 Main St",
            "home_city": "Anytown",
            "home_state": "WA",
            "home_zip": "98101",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["home_state"] == "WA"

    g = c.get("/api/v1/epcr/charts/chart-1/patient-ext")
    assert g.json()["home_address"]["home_zip"] == "98101"


def test_post_and_delete_race(client) -> None:
    c, _ = client
    r = c.post(
        "/api/v1/epcr/charts/chart-1/patient-ext/races",
        json={"race_code": "2106-3", "sequence_index": 0},
    )
    assert r.status_code == 201, r.text
    race_id = r.json()["id"]

    r2 = c.post(
        "/api/v1/epcr/charts/chart-1/patient-ext/races",
        json={"race_code": "2054-5", "sequence_index": 1},
    )
    assert r2.status_code == 201

    g = c.get("/api/v1/epcr/charts/chart-1/patient-ext")
    assert {r["race_code"] for r in g.json()["races"]} == {"2106-3", "2054-5"}

    d = c.delete(f"/api/v1/epcr/charts/chart-1/patient-ext/races/{race_id}")
    assert d.status_code == 200
    g2 = c.get("/api/v1/epcr/charts/chart-1/patient-ext")
    assert {r["race_code"] for r in g2.json()["races"]} == {"2054-5"}


def test_post_duplicate_race_conflict(client) -> None:
    c, _ = client
    c.post(
        "/api/v1/epcr/charts/chart-1/patient-ext/races",
        json={"race_code": "2106-3"},
    )
    r = c.post(
        "/api/v1/epcr/charts/chart-1/patient-ext/races",
        json={"race_code": "2106-3"},
    )
    assert r.status_code == 409


def test_post_and_delete_language(client) -> None:
    c, _ = client
    r = c.post(
        "/api/v1/epcr/charts/chart-1/patient-ext/languages",
        json={"language_code": "eng"},
    )
    assert r.status_code == 201
    lang_id = r.json()["id"]

    d = c.delete(f"/api/v1/epcr/charts/chart-1/patient-ext/languages/{lang_id}")
    assert d.status_code == 200
    g = c.get("/api/v1/epcr/charts/chart-1/patient-ext")
    assert g.json()["languages"] == []


def test_post_phone_with_type_and_delete(client) -> None:
    c, _ = client
    r = c.post(
        "/api/v1/epcr/charts/chart-1/patient-ext/phones",
        json={"phone_number": "555-0100", "phone_type_code": "9913003"},
    )
    assert r.status_code == 201
    phone_id = r.json()["id"]
    assert r.json()["phone_type_code"] == "9913003"

    d = c.delete(f"/api/v1/epcr/charts/chart-1/patient-ext/phones/{phone_id}")
    assert d.status_code == 200
    g = c.get("/api/v1/epcr/charts/chart-1/patient-ext")
    assert g.json()["phones"] == []


def test_put_scalar_rejects_unknown_field(client) -> None:
    c, _ = client
    r = c.put(
        "/api/v1/epcr/charts/chart-1/patient-ext/scalar",
        json={"not_a_real_field": "x"},
    )
    assert r.status_code == 422


def test_post_race_rejects_blank_code(client) -> None:
    c, _ = client
    r = c.post(
        "/api/v1/epcr/charts/chart-1/patient-ext/races",
        json={"race_code": ""},
    )
    assert r.status_code == 422
