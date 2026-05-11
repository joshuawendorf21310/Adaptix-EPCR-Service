"""API tests for the eVitals extension router.

Hermetic: in-memory SQLite, FastAPI TestClient, dependency-overridden
auth and session. The fixture seeds one Chart and one Vitals row so
the extension routes have something to attach to.
"""
from __future__ import annotations

from types import SimpleNamespace
from datetime import UTC, datetime

import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.api_vitals_ext import router as vitals_ext_router
from epcr_app.db import get_session
from epcr_app.dependencies import get_current_user
from epcr_app.models import Base, Chart, Vitals
from epcr_app.models_nemsis_field_values import NemsisFieldValue
from epcr_app.models_vitals_ext import (  # noqa: F401
    VitalsGcsQualifier,
    VitalsNemsisExt,
    VitalsReperfusionChecklist,
)


CHART_ID = "chart-1"
VITALS_ID = "vitals-1"
BASE_URL = f"/api/v1/epcr/charts/{CHART_ID}/vitals/{VITALS_ID}/ext"


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with sessionmaker() as s:
        chart = Chart(
            id=CHART_ID,
            tenant_id="T-1",
            call_number="C-1",
            created_by_user_id="user-1",
        )
        s.add(chart)
        await s.flush()
        vitals = Vitals(
            id=VITALS_ID,
            chart_id=CHART_ID,
            tenant_id="T-1",
            recorded_at=datetime.now(UTC),
        )
        s.add(vitals)
        await s.commit()

    app = FastAPI()
    app.include_router(vitals_ext_router)

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
    r = c.get(BASE_URL)
    assert r.status_code == 404


def test_put_creates_then_get_returns(client) -> None:
    c, _ = client
    body = {
        "etco2": 35,
        "gcs_eye_code": "3518003",
        "gcs_verbal_code": "3519005",
        "gcs_motor_code": "3520006",
        "gcs_total": 14,
        "avpu_code": "3523001",
        "cardiac_rhythm_codes_json": ["3508001", "3508003"],
    }
    r = c.put(BASE_URL, json=body)
    assert r.status_code == 200, r.text
    body_out = r.json()
    assert body_out["etco2"] == 35
    assert body_out["gcs_total"] == 14

    g = c.get(BASE_URL)
    assert g.status_code == 200
    payload = g.json()
    assert payload["ext"]["etco2"] == 35
    assert payload["ext"]["cardiac_rhythm_codes_json"] == ["3508001", "3508003"]


def test_put_projects_to_field_values_ledger(client) -> None:
    c, sessionmaker = client
    body = {
        "etco2": 30,
        "gcs_eye_code": "3518003",
        "gcs_verbal_code": "3519005",
        "gcs_motor_code": "3520006",
        "avpu_code": "3523001",
    }
    r = c.put(BASE_URL, json=body)
    assert r.status_code == 200, r.text

    async def _check():
        async with sessionmaker() as s:
            rows = (
                await s.execute(
                    select(NemsisFieldValue).where(
                        NemsisFieldValue.chart_id == CHART_ID,
                        NemsisFieldValue.section == "eVitals",
                    )
                )
            ).scalars().all()
            elements = {r.element_number for r in rows}
            assert {
                "eVitals.16",
                "eVitals.19",
                "eVitals.20",
                "eVitals.21",
                "eVitals.26",
            } <= elements
            # Every ledger row for eVitals must be keyed on vitals_id
            # so each VitalGroup occurrence is addressable.
            for row in rows:
                assert row.occurrence_id.startswith(VITALS_ID)

    import asyncio
    asyncio.get_event_loop().run_until_complete(_check())


def test_post_and_delete_gcs_qualifier(client) -> None:
    c, _ = client
    # PUT one ext scalar so the GET later returns a non-empty record.
    c.put(BASE_URL, json={"gcs_total": 15})

    r = c.post(
        f"{BASE_URL}/gcs-qualifiers",
        json={"qualifier_code": "3521001", "sequence_index": 0},
    )
    assert r.status_code == 201, r.text
    qual_id = r.json()["id"]

    g = c.get(BASE_URL)
    assert g.status_code == 200
    listed = g.json()["gcs_qualifiers"]
    assert len(listed) == 1 and listed[0]["qualifier_code"] == "3521001"

    d = c.delete(f"{BASE_URL}/gcs-qualifiers/{qual_id}")
    assert d.status_code == 200, d.text

    g2 = c.get(BASE_URL)
    assert g2.status_code == 200
    assert g2.json()["gcs_qualifiers"] == []


def test_post_and_delete_reperfusion_item(client) -> None:
    c, _ = client
    c.put(BASE_URL, json={"stroke_scale_score": 2})

    r = c.post(
        f"{BASE_URL}/reperfusion-items",
        json={"item_code": "3528001", "sequence_index": 0},
    )
    assert r.status_code == 201, r.text
    item_id = r.json()["id"]

    g = c.get(BASE_URL)
    listed = g.json()["reperfusion_checklist"]
    assert len(listed) == 1 and listed[0]["item_code"] == "3528001"

    d = c.delete(f"{BASE_URL}/reperfusion-items/{item_id}")
    assert d.status_code == 200, d.text


def test_delete_unknown_gcs_qualifier_404(client) -> None:
    c, _ = client
    c.put(BASE_URL, json={"gcs_total": 14})
    r = c.delete(f"{BASE_URL}/gcs-qualifiers/does-not-exist")
    assert r.status_code == 404


def test_put_rejects_unknown_field(client) -> None:
    c, _ = client
    r = c.put(BASE_URL, json={"not_a_real_field": "x"})
    assert r.status_code == 422
