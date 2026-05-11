"""API tests for the intervention NEMSIS extension router.

Hermetic: in-memory SQLite, FastAPI TestClient, dependency-overridden
auth and session. Verifies GET/PUT for ext, POST/DELETE for the 1:M
complications child, and that PUT projects to the NEMSIS field-values
ledger under section ``eProcedures``.
"""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.api_intervention_ext import router as ext_router
from epcr_app.db import get_session
from epcr_app.dependencies import get_current_user
from epcr_app.models import (
    Base,
    Chart,
    ClinicalIntervention,
    InterventionExportState,
    ProtocolFamily,
)
from epcr_app.models_intervention_ext import (  # noqa: F401
    InterventionComplication,
    InterventionNemsisExt,
)
from epcr_app.models_nemsis_field_values import NemsisFieldValue


CHART_ID = "chart-1"
INTERVENTION_ID = "intervention-1"


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Pre-seed one chart and one intervention for tenant T-1
    async with sessionmaker() as s:
        chart = Chart(
            id=CHART_ID,
            tenant_id="T-1",
            call_number="C-1",
            created_by_user_id="user-1",
        )
        s.add(chart)
        now = datetime.now(UTC)
        iv = ClinicalIntervention(
            id=INTERVENTION_ID,
            chart_id=CHART_ID,
            tenant_id="T-1",
            category="airway",
            name="endotracheal intubation",
            indication="respiratory failure",
            intent="secure airway",
            expected_response="adequate ventilation",
            protocol_family=ProtocolFamily.GENERAL,
            export_state=InterventionExportState.PENDING_MAPPING,
            performed_at=now,
            updated_at=now,
            provider_id="provider-1",
        )
        s.add(iv)
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


def _url(suffix: str = "") -> str:
    return (
        f"/api/v1/epcr/charts/{CHART_ID}/procedures/{INTERVENTION_ID}/ext{suffix}"
    )


def test_get_returns_404_when_absent(client) -> None:
    c, _ = client
    r = c.get(_url(""))
    assert r.status_code == 404


def test_put_creates_then_get_returns(client) -> None:
    c, _ = client
    body = {
        "prior_to_ems_indicator_code": "9923003",
        "number_of_attempts": 2,
        "procedure_successful_code": "9923001",
        "ems_professional_type_code": "2710001",
        "authorizing_physician_last_name": "Doe",
        "authorizing_physician_first_name": "Jane",
    }
    r = c.put(_url(""), json=body)
    assert r.status_code == 200, r.text
    body_out = r.json()
    assert body_out["number_of_attempts"] == 2
    assert body_out["authorizing_physician_last_name"] == "Doe"

    g = c.get(_url(""))
    assert g.status_code == 200
    payload = g.json()
    assert payload["ext"]["number_of_attempts"] == 2
    assert payload["complications"] == []


def test_put_projects_to_field_values_ledger(client) -> None:
    c, sessionmaker = client
    body = {
        "prior_to_ems_indicator_code": "9923003",
        "number_of_attempts": 1,
        "procedure_successful_code": "9923001",
        "ems_professional_type_code": "2710001",
        "authorizing_physician_last_name": "Doe",
        "authorizing_physician_first_name": "Jane",
    }
    r = c.put(_url(""), json=body)
    assert r.status_code == 200, r.text

    async def _check():
        async with sessionmaker() as s:
            rows = (
                await s.execute(
                    select(NemsisFieldValue).where(
                        NemsisFieldValue.chart_id == CHART_ID,
                        NemsisFieldValue.section == "eProcedures",
                    )
                )
            ).scalars().all()
            elements = {r.element_number for r in rows}
            assert {
                "eProcedures.02",
                "eProcedures.05",
                "eProcedures.06",
                "eProcedures.10",
                "eProcedures.12",
            } <= elements

    import asyncio
    asyncio.get_event_loop().run_until_complete(_check())


def test_post_then_delete_complication(client) -> None:
    c, sessionmaker = client
    # PUT the ext first so GET returns 200 after complication is deleted
    c.put(_url(""), json={"number_of_attempts": 1})

    r = c.post(_url("/complications"), json={"complication_code": "9908001"})
    assert r.status_code == 201, r.text
    comp = r.json()
    assert comp["complication_code"] == "9908001"
    assert comp["sequence_index"] == 0

    g = c.get(_url(""))
    assert g.status_code == 200
    assert len(g.json()["complications"]) == 1

    r2 = c.post(_url("/complications"), json={"complication_code": "9908002"})
    assert r2.status_code == 201

    async def _check_projection():
        async with sessionmaker() as s:
            rows = (
                await s.execute(
                    select(NemsisFieldValue).where(
                        NemsisFieldValue.chart_id == CHART_ID,
                        NemsisFieldValue.element_number == "eProcedures.07",
                    )
                )
            ).scalars().all()
            assert len(rows) == 2

    import asyncio
    asyncio.get_event_loop().run_until_complete(_check_projection())

    d = c.delete(_url(f"/complications/{comp['id']}"))
    assert d.status_code == 200, d.text
    assert d.json()["deleted_at"] is not None

    g2 = c.get(_url(""))
    assert g2.status_code == 200
    remaining = g2.json()["complications"]
    assert len(remaining) == 1
    assert remaining[0]["complication_code"] == "9908002"


def test_delete_unknown_complication_404(client) -> None:
    c, _ = client
    c.put(_url(""), json={"number_of_attempts": 1})
    r = c.delete(_url("/complications/not-a-real-id"))
    assert r.status_code == 404


def test_put_rejects_unknown_field(client) -> None:
    c, _ = client
    r = c.put(_url(""), json={"not_a_real_field": "x"})
    assert r.status_code == 422


def test_post_complication_rejects_missing_code(client) -> None:
    c, _ = client
    r = c.post(_url("/complications"), json={"sequence_index": 0})
    assert r.status_code == 422
