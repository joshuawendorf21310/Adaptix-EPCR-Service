"""API tests for the ePayment router (:mod:`epcr_app.api_chart_payment`).

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

from epcr_app.api_chart_payment import router as payment_router
from epcr_app.db import get_session
from epcr_app.dependencies import get_current_user
from epcr_app.models import Base, Chart
from epcr_app.models_chart_payment import ChartPayment  # noqa: F401
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
    app.include_router(payment_router)

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
    r = c.get("/api/v1/epcr/charts/chart-1/payment")
    assert r.status_code == 404


def test_put_create_requires_primary_method(client) -> None:
    c, _ = client
    r = c.put(
        "/api/v1/epcr/charts/chart-1/payment",
        json={"insurance_company_name": "Acme"},
    )
    assert r.status_code == 400, r.text


def test_put_creates_then_get_returns(client) -> None:
    c, _ = client
    body = {
        "primary_method_of_payment_code": "9954001",
        "insurance_company_name": "Acme Health",
        "insurance_company_state": "IL",
        "pcs_signed_date": "2026-05-01",
    }
    r = c.put("/api/v1/epcr/charts/chart-1/payment", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["primary_method_of_payment_code"] == "9954001"
    assert out["insurance_company_name"] == "Acme Health"
    assert out["pcs_signed_date"] == "2026-05-01"
    assert out["supply_items"] == []

    g = c.get("/api/v1/epcr/charts/chart-1/payment")
    assert g.status_code == 200
    assert g.json()["insurance_company_state"] == "IL"


def test_put_projects_scalars_and_lists_to_field_values_ledger(client) -> None:
    c, sessionmaker = client
    body = {
        "primary_method_of_payment_code": "9954001",
        "insurance_company_name": "Acme Health",
        "reason_for_pcs_codes_json": ["RP1", "RP2"],
        "ems_condition_codes_json": ["EC1"],
    }
    r = c.put("/api/v1/epcr/charts/chart-1/payment", json=body)
    assert r.status_code == 200, r.text

    async def _check():
        async with sessionmaker() as s:
            rows = (
                await s.execute(
                    select(NemsisFieldValue).where(
                        NemsisFieldValue.chart_id == "chart-1",
                        NemsisFieldValue.section == "ePayment",
                    )
                )
            ).scalars().all()
            elements = {r.element_number for r in rows}
            assert {"ePayment.01", "ePayment.10"} <= elements
            reason_rows = [r for r in rows if r.element_number == "ePayment.04"]
            assert len(reason_rows) == 2
            ems_rows = [r for r in rows if r.element_number == "ePayment.51"]
            assert len(ems_rows) == 1

    import asyncio
    asyncio.get_event_loop().run_until_complete(_check())


def test_post_supply_adds_row_and_projects_paired_group(client) -> None:
    c, sessionmaker = client
    c.put(
        "/api/v1/epcr/charts/chart-1/payment",
        json={"primary_method_of_payment_code": "9954001"},
    )
    r = c.post(
        "/api/v1/epcr/charts/chart-1/payment/supplies",
        json={"supply_item_name": "IV Catheter 18g", "supply_item_quantity": 2},
    )
    assert r.status_code == 201, r.text
    supply_id = r.json()["id"]

    g = c.get("/api/v1/epcr/charts/chart-1/payment")
    assert g.status_code == 200
    assert len(g.json()["supply_items"]) == 1
    assert g.json()["supply_items"][0]["supply_item_name"] == "IV Catheter 18g"

    async def _check_ledger():
        async with sessionmaker() as s:
            rows = (
                await s.execute(
                    select(NemsisFieldValue).where(
                        NemsisFieldValue.chart_id == "chart-1",
                        NemsisFieldValue.section == "ePayment",
                    )
                )
            ).scalars().all()
            name_rows = [r for r in rows if r.element_number == "ePayment.55"]
            qty_rows = [r for r in rows if r.element_number == "ePayment.56"]
            assert len(name_rows) == 1
            assert len(qty_rows) == 1
            # Paired group: same occurrence_id == supply row id.
            assert name_rows[0].occurrence_id == supply_id
            assert qty_rows[0].occurrence_id == supply_id
            assert name_rows[0].group_path == "ePayment.SupplyUsedGroup"

    import asyncio
    asyncio.get_event_loop().run_until_complete(_check_ledger())


def test_post_supply_rejects_duplicate_name(client) -> None:
    c, _ = client
    c.put(
        "/api/v1/epcr/charts/chart-1/payment",
        json={"primary_method_of_payment_code": "9954001"},
    )
    c.post(
        "/api/v1/epcr/charts/chart-1/payment/supplies",
        json={"supply_item_name": "Bandage", "supply_item_quantity": 1},
    )
    r = c.post(
        "/api/v1/epcr/charts/chart-1/payment/supplies",
        json={"supply_item_name": "Bandage", "supply_item_quantity": 2},
    )
    assert r.status_code == 409, r.text


def test_delete_supply_soft_deletes(client) -> None:
    c, _ = client
    c.put(
        "/api/v1/epcr/charts/chart-1/payment",
        json={"primary_method_of_payment_code": "9954001"},
    )
    add = c.post(
        "/api/v1/epcr/charts/chart-1/payment/supplies",
        json={"supply_item_name": "Bandage", "supply_item_quantity": 1},
    )
    supply_id = add.json()["id"]
    r = c.delete(f"/api/v1/epcr/charts/chart-1/payment/supplies/{supply_id}")
    assert r.status_code == 200, r.text
    assert r.json()["deleted_at"] is not None

    g = c.get("/api/v1/epcr/charts/chart-1/payment")
    assert g.json()["supply_items"] == []


def test_delete_supply_404_unknown(client) -> None:
    c, _ = client
    c.put(
        "/api/v1/epcr/charts/chart-1/payment",
        json={"primary_method_of_payment_code": "9954001"},
    )
    r = c.delete("/api/v1/epcr/charts/chart-1/payment/supplies/does-not-exist")
    assert r.status_code == 404


def test_delete_clears_one_field(client) -> None:
    c, _ = client
    c.put(
        "/api/v1/epcr/charts/chart-1/payment",
        json={
            "primary_method_of_payment_code": "9954001",
            "insurance_company_name": "Acme",
        },
    )
    r = c.delete("/api/v1/epcr/charts/chart-1/payment/insurance_company_name")
    assert r.status_code == 200, r.text
    assert r.json()["insurance_company_name"] is None
    assert r.json()["primary_method_of_payment_code"] == "9954001"


def test_delete_refuses_required_column(client) -> None:
    c, _ = client
    c.put(
        "/api/v1/epcr/charts/chart-1/payment",
        json={"primary_method_of_payment_code": "9954001"},
    )
    r = c.delete(
        "/api/v1/epcr/charts/chart-1/payment/primary_method_of_payment_code"
    )
    assert r.status_code == 400


def test_delete_unknown_field_400(client) -> None:
    c, _ = client
    c.put(
        "/api/v1/epcr/charts/chart-1/payment",
        json={"primary_method_of_payment_code": "9954001"},
    )
    r = c.delete("/api/v1/epcr/charts/chart-1/payment/not_a_column")
    assert r.status_code == 400


def test_put_rejects_unknown_field(client) -> None:
    c, _ = client
    r = c.put(
        "/api/v1/epcr/charts/chart-1/payment",
        json={"not_a_real_field": "x"},
    )
    assert r.status_code == 422


def test_delete_clears_json_list_field(client) -> None:
    c, _ = client
    c.put(
        "/api/v1/epcr/charts/chart-1/payment",
        json={
            "primary_method_of_payment_code": "9954001",
            "reason_for_pcs_codes_json": ["RP1", "RP2"],
        },
    )
    r = c.delete(
        "/api/v1/epcr/charts/chart-1/payment/reason_for_pcs_codes_json"
    )
    assert r.status_code == 200, r.text
    assert r.json()["reason_for_pcs_codes_json"] is None
