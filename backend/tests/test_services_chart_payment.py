"""Service tests for :class:`ChartPaymentService`.

Covers upsert (creation requires ePayment.01, partial updates retain
existing values), get (joins embedded supply_items), clear_field
(refuses to clear NEMSIS-Required column), supply CRUD with
sequence_index auto-assignment, tenant isolation, and error contracts.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart
from epcr_app.models_chart_payment import ChartPayment  # noqa: F401 - registers table
from epcr_app.services_chart_payment import (
    ChartPaymentError,
    ChartPaymentPayload,
    ChartPaymentService,
)


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with sessionmaker() as s:
        yield s
    await engine.dispose()


async def _seed_chart(session: AsyncSession, tenant_id: str, call_number: str) -> Chart:
    chart = Chart(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        call_number=call_number,
        created_by_user_id="user-1",
    )
    session.add(chart)
    await session.flush()
    return chart


@pytest.mark.asyncio
async def test_upsert_create_requires_primary_method(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-1")
    with pytest.raises(ChartPaymentError) as exc:
        await ChartPaymentService.upsert(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            payload=ChartPaymentPayload(insurance_company_name="Acme"),
            user_id="u",
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_upsert_creates_then_reads(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-1")
    payload = ChartPaymentPayload(
        primary_method_of_payment_code="9954001",
        insurance_company_name="Acme Health",
        insurance_company_state="IL",
        pcs_signed_date=date(2026, 5, 1),
        mileage_to_closest_hospital=12.3,
        reason_for_pcs_codes_json=["R1", "R2"],
    )
    result = await ChartPaymentService.upsert(
        session, tenant_id="t-1", chart_id=chart.id, payload=payload, user_id="u"
    )
    assert result["primary_method_of_payment_code"] == "9954001"
    assert result["insurance_company_name"] == "Acme Health"
    assert result["insurance_company_state"] == "IL"
    assert result["pcs_signed_date"] == "2026-05-01"
    assert result["mileage_to_closest_hospital"] == 12.3
    assert result["reason_for_pcs_codes_json"] == ["R1", "R2"]
    assert result["supply_items"] == []

    fetched = await ChartPaymentService.get(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert fetched is not None
    assert fetched["primary_method_of_payment_code"] == "9954001"
    # SQLite drops tz info; compare timestamp prefix only.
    assert fetched["created_at"].startswith("2026-")


@pytest.mark.asyncio
async def test_partial_update_preserves_existing(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-2")
    await ChartPaymentService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartPaymentPayload(
            primary_method_of_payment_code="9954001",
            insurance_company_name="Acme",
            insurance_company_state="IL",
        ),
        user_id="u",
    )
    # Only set insurance_company_phone; existing values must remain.
    await ChartPaymentService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartPaymentPayload(insurance_company_phone="555-1212"),
        user_id="u2",
    )
    fetched = await ChartPaymentService.get(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert fetched["primary_method_of_payment_code"] == "9954001"
    assert fetched["insurance_company_name"] == "Acme"
    assert fetched["insurance_company_state"] == "IL"
    assert fetched["insurance_company_phone"] == "555-1212"
    assert fetched["version"] == 2


@pytest.mark.asyncio
async def test_clear_field_sets_null(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-3")
    await ChartPaymentService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartPaymentPayload(
            primary_method_of_payment_code="9954001",
            insurance_company_name="Acme",
        ),
        user_id="u",
    )
    cleared = await ChartPaymentService.clear_field(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        field="insurance_company_name",
        user_id="u",
    )
    assert cleared["insurance_company_name"] is None
    assert cleared["primary_method_of_payment_code"] == "9954001"


@pytest.mark.asyncio
async def test_clear_field_refuses_required_column(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-4")
    await ChartPaymentService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartPaymentPayload(primary_method_of_payment_code="9954001"),
        user_id="u",
    )
    with pytest.raises(ChartPaymentError) as exc:
        await ChartPaymentService.clear_field(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            field="primary_method_of_payment_code",
            user_id="u",
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_clear_field_unknown_raises(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-5")
    await ChartPaymentService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartPaymentPayload(primary_method_of_payment_code="9954001"),
        user_id="u",
    )
    with pytest.raises(ChartPaymentError) as exc:
        await ChartPaymentService.clear_field(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            field="not_a_real_column",
            user_id="u",
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_tenant_scoping_returns_none_for_wrong_tenant(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-A", "C-A")
    await ChartPaymentService.upsert(
        session,
        tenant_id="t-A",
        chart_id=chart.id,
        payload=ChartPaymentPayload(primary_method_of_payment_code="9954001"),
        user_id="u",
    )
    leaked = await ChartPaymentService.get(
        session, tenant_id="t-B", chart_id=chart.id
    )
    assert leaked is None


@pytest.mark.asyncio
async def test_get_returns_none_when_absent(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-empty")
    result = await ChartPaymentService.get(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert result is None


@pytest.mark.asyncio
async def test_upsert_requires_tenant_and_chart(session: AsyncSession) -> None:
    with pytest.raises(ChartPaymentError):
        await ChartPaymentService.upsert(
            session,
            tenant_id="",
            chart_id="x",
            payload=ChartPaymentPayload(primary_method_of_payment_code="9954001"),
            user_id=None,
        )
    with pytest.raises(ChartPaymentError):
        await ChartPaymentService.upsert(
            session,
            tenant_id="t",
            chart_id="",
            payload=ChartPaymentPayload(primary_method_of_payment_code="9954001"),
            user_id=None,
        )


# ---- Supply Used 1:M ---------------------------------------------------


@pytest.mark.asyncio
async def test_add_supply_assigns_next_sequence(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-sup-1")
    await ChartPaymentService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartPaymentPayload(primary_method_of_payment_code="9954001"),
        user_id="u",
    )
    a = await ChartPaymentService.add_supply(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        supply_item_name="IV Catheter 18g",
        supply_item_quantity=2,
    )
    b = await ChartPaymentService.add_supply(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        supply_item_name="Saline 1000ml",
        supply_item_quantity=1,
    )
    assert a["sequence_index"] == 0
    assert b["sequence_index"] == 1

    supplies = await ChartPaymentService.list_supplies(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert [s["supply_item_name"] for s in supplies] == [
        "IV Catheter 18g",
        "Saline 1000ml",
    ]


@pytest.mark.asyncio
async def test_add_supply_rejects_duplicate_name(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-sup-2")
    await ChartPaymentService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartPaymentPayload(primary_method_of_payment_code="9954001"),
        user_id="u",
    )
    await ChartPaymentService.add_supply(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        supply_item_name="Bandage",
        supply_item_quantity=1,
    )
    with pytest.raises(ChartPaymentError) as exc:
        await ChartPaymentService.add_supply(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            supply_item_name="Bandage",
            supply_item_quantity=2,
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_add_supply_rejects_invalid_quantity(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-sup-3")
    await ChartPaymentService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartPaymentPayload(primary_method_of_payment_code="9954001"),
        user_id="u",
    )
    with pytest.raises(ChartPaymentError):
        await ChartPaymentService.add_supply(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            supply_item_name="Bandage",
            supply_item_quantity=-1,
        )
    with pytest.raises(ChartPaymentError):
        await ChartPaymentService.add_supply(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            supply_item_name="",
            supply_item_quantity=1,
        )


@pytest.mark.asyncio
async def test_delete_supply_soft_deletes(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-sup-4")
    await ChartPaymentService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartPaymentPayload(primary_method_of_payment_code="9954001"),
        user_id="u",
    )
    supply = await ChartPaymentService.add_supply(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        supply_item_name="Bandage",
        supply_item_quantity=1,
    )
    deleted = await ChartPaymentService.delete_supply(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        supply_id=supply["id"],
    )
    assert deleted["deleted_at"] is not None

    # list_supplies must omit soft-deleted rows.
    supplies = await ChartPaymentService.list_supplies(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert supplies == []


@pytest.mark.asyncio
async def test_delete_supply_404_when_unknown(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-sup-5")
    await ChartPaymentService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartPaymentPayload(primary_method_of_payment_code="9954001"),
        user_id="u",
    )
    with pytest.raises(ChartPaymentError) as exc:
        await ChartPaymentService.delete_supply(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            supply_id="does-not-exist",
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_includes_supply_items(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-sup-6")
    await ChartPaymentService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartPaymentPayload(primary_method_of_payment_code="9954001"),
        user_id="u",
    )
    await ChartPaymentService.add_supply(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        supply_item_name="IV",
        supply_item_quantity=1,
    )
    await ChartPaymentService.add_supply(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        supply_item_name="Saline",
        supply_item_quantity=2,
    )
    fetched = await ChartPaymentService.get(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert fetched is not None
    assert len(fetched["supply_items"]) == 2
    names = [s["supply_item_name"] for s in fetched["supply_items"]]
    assert names == ["IV", "Saline"]


@pytest.mark.asyncio
async def test_supply_tenant_isolation(session: AsyncSession) -> None:
    chart_a = await _seed_chart(session, "t-A", "C-A")
    chart_b = await _seed_chart(session, "t-B", "C-B")
    for tenant, chart in (("t-A", chart_a), ("t-B", chart_b)):
        await ChartPaymentService.upsert(
            session,
            tenant_id=tenant,
            chart_id=chart.id,
            payload=ChartPaymentPayload(primary_method_of_payment_code="9954001"),
            user_id="u",
        )
        await ChartPaymentService.add_supply(
            session,
            tenant_id=tenant,
            chart_id=chart.id,
            supply_item_name="Bandage",
            supply_item_quantity=1,
        )
    supplies_a = await ChartPaymentService.list_supplies(
        session, tenant_id="t-A", chart_id=chart_a.id
    )
    leaked = await ChartPaymentService.list_supplies(
        session, tenant_id="t-B", chart_id=chart_a.id
    )
    assert len(supplies_a) == 1
    assert leaked == []
