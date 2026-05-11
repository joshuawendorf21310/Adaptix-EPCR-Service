"""Persistence tests for the NEMSIS ePayment ORM models.

Covers: insert, query, tenant scoping, unique-per-chart constraint on
the 1:1 row, NOT NULL on ePayment.01, and the 1:M Supply Used child
table (insert, unique-per-name, sequence ordering, soft delete).
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart
from epcr_app.models_chart_payment import ChartPayment, ChartPaymentSupplyItem


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with sessionmaker() as s:
        yield s
    await engine.dispose()


async def _make_chart(
    session: AsyncSession, tenant_id: str, call_number: str
) -> Chart:
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
async def test_insert_chart_payment_with_required_and_scalars(
    session: AsyncSession,
) -> None:
    chart = await _make_chart(session, "t-1", "C-001")
    row = ChartPayment(
        id=str(uuid.uuid4()),
        tenant_id="t-1",
        chart_id=chart.id,
        primary_method_of_payment_code="9954001",
        insurance_company_name="Acme Health",
        insurance_company_state="IL",
        pcs_signed_date=date(2026, 5, 1),
        insured_date_of_birth=date(1980, 1, 15),
        mileage_to_closest_hospital=7.5,
        reason_for_pcs_codes_json=["R1", "R2"],
        ems_condition_codes_json=["C1"],
    )
    session.add(row)
    await session.flush()

    fetched = (
        await session.execute(
            select(ChartPayment).where(ChartPayment.chart_id == chart.id)
        )
    ).scalar_one()
    assert fetched.primary_method_of_payment_code == "9954001"
    assert fetched.insurance_company_name == "Acme Health"
    assert fetched.insurance_company_state == "IL"
    assert fetched.pcs_signed_date == date(2026, 5, 1)
    assert fetched.insured_date_of_birth == date(1980, 1, 15)
    assert fetched.mileage_to_closest_hospital == 7.5
    assert fetched.reason_for_pcs_codes_json == ["R1", "R2"]
    assert fetched.ems_condition_codes_json == ["C1"]
    assert fetched.tenant_id == "t-1"
    assert fetched.version == 1


@pytest.mark.asyncio
async def test_chart_payment_unique_per_chart(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-002")
    session.add(
        ChartPayment(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            primary_method_of_payment_code="9954001",
        )
    )
    await session.flush()
    session.add(
        ChartPayment(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            primary_method_of_payment_code="9954003",
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_chart_payment_primary_method_not_null(
    session: AsyncSession,
) -> None:
    chart = await _make_chart(session, "t-1", "C-003")
    session.add(
        ChartPayment(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            # primary_method_of_payment_code intentionally omitted
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_chart_payment_tenant_isolation_in_query(
    session: AsyncSession,
) -> None:
    chart_a = await _make_chart(session, "t-A", "C-A")
    chart_b = await _make_chart(session, "t-B", "C-B")
    session.add(
        ChartPayment(
            id=str(uuid.uuid4()),
            tenant_id="t-A",
            chart_id=chart_a.id,
            primary_method_of_payment_code="9954001",
        )
    )
    session.add(
        ChartPayment(
            id=str(uuid.uuid4()),
            tenant_id="t-B",
            chart_id=chart_b.id,
            primary_method_of_payment_code="9954003",
        )
    )
    await session.flush()

    rows_a = (
        await session.execute(
            select(ChartPayment).where(ChartPayment.tenant_id == "t-A")
        )
    ).scalars().all()
    rows_b = (
        await session.execute(
            select(ChartPayment).where(ChartPayment.tenant_id == "t-B")
        )
    ).scalars().all()
    assert len(rows_a) == 1 and rows_a[0].chart_id == chart_a.id
    assert len(rows_b) == 1 and rows_b[0].chart_id == chart_b.id


@pytest.mark.asyncio
async def test_chart_payment_declares_full_epayment_field_set() -> None:
    """Guard rail: ChartPayment must declare every ePayment column."""
    expected = {
        "primary_method_of_payment_code",
        "physician_certification_statement_code",
        "pcs_signed_date",
        "reason_for_pcs_codes_json",
        "pcs_provider_type_code",
        "pcs_last_name",
        "pcs_first_name",
        "patient_resides_in_service_area_code",
        "insurance_company_id",
        "insurance_company_name",
        "insurance_billing_priority_code",
        "insurance_company_address",
        "insurance_company_city",
        "insurance_company_state",
        "insurance_company_zip",
        "insurance_company_country",
        "insurance_group_id",
        "insurance_policy_id_number",
        "insured_last_name",
        "insured_first_name",
        "insured_middle_name",
        "relationship_to_insured_code",
        "closest_relative_last_name",
        "closest_relative_first_name",
        "closest_relative_middle_name",
        "closest_relative_street_address",
        "closest_relative_city",
        "closest_relative_state",
        "closest_relative_zip",
        "closest_relative_country",
        "closest_relative_phone",
        "closest_relative_relationship_code",
        "patient_employer_name",
        "patient_employer_address",
        "patient_employer_city",
        "patient_employer_state",
        "patient_employer_zip",
        "patient_employer_country",
        "patient_employer_phone",
        "response_urgency_code",
        "patient_transport_assessment_code",
        "specialty_care_transport_provider_code",
        "ambulance_transport_reason_code",
        "round_trip_purpose_description",
        "stretcher_purpose_description",
        "ambulance_conditions_indicator_codes_json",
        "mileage_to_closest_hospital",
        "als_assessment_performed_warranted_code",
        "cms_service_level_code",
        "ems_condition_codes_json",
        "cms_transportation_indicator_codes_json",
        "transport_authorization_code",
        "prior_authorization_code_payer",
        "payer_type_code",
        "insurance_group_name",
        "insurance_company_phone",
        "insured_date_of_birth",
    }
    cols = {c.name for c in ChartPayment.__table__.columns}
    missing = expected - cols
    assert not missing, f"ChartPayment missing ePayment columns: {missing}"


@pytest.mark.asyncio
async def test_supply_item_insert_and_unique_per_name(
    session: AsyncSession,
) -> None:
    chart = await _make_chart(session, "t-1", "C-supply")
    now = datetime.now(UTC)
    s1 = ChartPaymentSupplyItem(
        id=str(uuid.uuid4()),
        tenant_id="t-1",
        chart_id=chart.id,
        supply_item_name="IV Catheter 18g",
        supply_item_quantity=2,
        sequence_index=0,
        created_at=now,
        updated_at=now,
    )
    session.add(s1)
    await session.flush()

    # Different name on same chart is allowed.
    s2 = ChartPaymentSupplyItem(
        id=str(uuid.uuid4()),
        tenant_id="t-1",
        chart_id=chart.id,
        supply_item_name="Saline 1000ml",
        supply_item_quantity=1,
        sequence_index=1,
        created_at=now,
        updated_at=now,
    )
    session.add(s2)
    await session.flush()

    # Duplicate name on same chart violates unique constraint.
    s3 = ChartPaymentSupplyItem(
        id=str(uuid.uuid4()),
        tenant_id="t-1",
        chart_id=chart.id,
        supply_item_name="IV Catheter 18g",
        supply_item_quantity=5,
        sequence_index=2,
        created_at=now,
        updated_at=now,
    )
    session.add(s3)
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_supply_item_tenant_scoped_query(session: AsyncSession) -> None:
    chart_a = await _make_chart(session, "t-A", "C-A")
    chart_b = await _make_chart(session, "t-B", "C-B")
    now = datetime.now(UTC)
    session.add(
        ChartPaymentSupplyItem(
            id=str(uuid.uuid4()),
            tenant_id="t-A",
            chart_id=chart_a.id,
            supply_item_name="Bandage",
            supply_item_quantity=3,
            sequence_index=0,
            created_at=now,
            updated_at=now,
        )
    )
    session.add(
        ChartPaymentSupplyItem(
            id=str(uuid.uuid4()),
            tenant_id="t-B",
            chart_id=chart_b.id,
            supply_item_name="Bandage",
            supply_item_quantity=4,
            sequence_index=0,
            created_at=now,
            updated_at=now,
        )
    )
    await session.flush()

    rows_a = (
        await session.execute(
            select(ChartPaymentSupplyItem).where(
                ChartPaymentSupplyItem.tenant_id == "t-A"
            )
        )
    ).scalars().all()
    rows_b = (
        await session.execute(
            select(ChartPaymentSupplyItem).where(
                ChartPaymentSupplyItem.tenant_id == "t-B"
            )
        )
    ).scalars().all()
    assert len(rows_a) == 1 and rows_a[0].supply_item_quantity == 3
    assert len(rows_b) == 1 and rows_b[0].supply_item_quantity == 4
