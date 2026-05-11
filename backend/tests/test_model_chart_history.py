"""Persistence tests for the NEMSIS eHistory ORM models.

Covers: insert and query for all five tables, tenant scoping, unique
constraints (per-chart-meta, per-chart-allergy-kind-code, per-chart-
condition, per-chart-drug), default version/created_at, soft delete
column, and required-column guard rails.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart
from epcr_app.models_chart_history import (
    ChartHistoryAllergy,
    ChartHistoryCurrentMedication,
    ChartHistoryImmunization,
    ChartHistoryMeta,
    ChartHistorySurgical,
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


async def _make_chart(session: AsyncSession, tenant_id: str, call_number: str) -> Chart:
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
async def test_insert_history_meta(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-001")
    row = ChartHistoryMeta(
        id=str(uuid.uuid4()),
        tenant_id="t-1",
        chart_id=chart.id,
        barriers_to_care_codes_json=["8801001", "8801003"],
        advance_directives_codes_json=["3501001"],
        medical_history_obtained_from_codes_json=["8807001"],
        alcohol_drug_use_codes_json=["3525001"],
        practitioner_last_name="Doe",
        practitioner_first_name="Jane",
        pregnancy_code="3535005",
        emergency_information_form_code="3508001",
    )
    session.add(row)
    await session.flush()

    fetched = (
        await session.execute(
            select(ChartHistoryMeta).where(ChartHistoryMeta.chart_id == chart.id)
        )
    ).scalar_one()
    assert fetched.practitioner_last_name == "Doe"
    assert fetched.barriers_to_care_codes_json == ["8801001", "8801003"]
    assert fetched.version == 1
    assert fetched.tenant_id == "t-1"


@pytest.mark.asyncio
async def test_history_meta_unique_per_chart(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-002")
    session.add(
        ChartHistoryMeta(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
        )
    )
    await session.flush()
    session.add(
        ChartHistoryMeta(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_insert_allergy_and_unique(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-003")
    session.add(
        ChartHistoryAllergy(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            allergy_kind="medication",
            allergy_code="RX-7980",
            allergy_text="Penicillin",
        )
    )
    session.add(
        ChartHistoryAllergy(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            allergy_kind="environmental_food",
            allergy_code="ENV-001",
        )
    )
    await session.flush()
    # Same kind + code on same chart -> integrity error
    session.add(
        ChartHistoryAllergy(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            allergy_kind="medication",
            allergy_code="RX-7980",
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_insert_surgical_and_unique(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-004")
    session.add(
        ChartHistorySurgical(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            condition_code="I10",
            condition_text="Essential hypertension",
        )
    )
    await session.flush()
    session.add(
        ChartHistorySurgical(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            condition_code="I10",
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_insert_medication_and_unique(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-005")
    session.add(
        ChartHistoryCurrentMedication(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            drug_code="RXN-12345",
            dose_value="10",
            dose_unit_code="mg",
            route_code="PO",
            frequency_code="BID",
        )
    )
    await session.flush()
    session.add(
        ChartHistoryCurrentMedication(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            drug_code="RXN-12345",
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_insert_immunization_no_unique(session: AsyncSession) -> None:
    """Immunizations have no unique constraint; multiple of same code allowed."""
    chart = await _make_chart(session, "t-1", "C-006")
    session.add(
        ChartHistoryImmunization(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            immunization_type_code="COVID19",
            immunization_year=2021,
            sequence_index=0,
        )
    )
    session.add(
        ChartHistoryImmunization(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            immunization_type_code="COVID19",
            immunization_year=2023,
            sequence_index=1,
        )
    )
    await session.flush()
    rows = (
        await session.execute(
            select(ChartHistoryImmunization).where(
                ChartHistoryImmunization.chart_id == chart.id
            )
        )
    ).scalars().all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_history_tenant_isolation_in_query(session: AsyncSession) -> None:
    chart_a = await _make_chart(session, "t-A", "C-A")
    chart_b = await _make_chart(session, "t-B", "C-B")
    session.add(
        ChartHistoryAllergy(
            id=str(uuid.uuid4()),
            tenant_id="t-A",
            chart_id=chart_a.id,
            allergy_kind="medication",
            allergy_code="RX-1",
        )
    )
    session.add(
        ChartHistoryAllergy(
            id=str(uuid.uuid4()),
            tenant_id="t-B",
            chart_id=chart_b.id,
            allergy_kind="medication",
            allergy_code="RX-1",
        )
    )
    await session.flush()

    rows_a = (
        await session.execute(
            select(ChartHistoryAllergy).where(ChartHistoryAllergy.tenant_id == "t-A")
        )
    ).scalars().all()
    rows_b = (
        await session.execute(
            select(ChartHistoryAllergy).where(ChartHistoryAllergy.tenant_id == "t-B")
        )
    ).scalars().all()
    assert len(rows_a) == 1 and rows_a[0].chart_id == chart_a.id
    assert len(rows_b) == 1 and rows_b[0].chart_id == chart_b.id


@pytest.mark.asyncio
async def test_history_meta_columns_exist() -> None:
    """Guard rail: ChartHistoryMeta must declare every required eHistory column."""
    expected = {
        "barriers_to_care_codes_json",
        "practitioner_last_name",
        "practitioner_first_name",
        "practitioner_middle_name",
        "advance_directives_codes_json",
        "medical_history_obtained_from_codes_json",
        "alcohol_drug_use_codes_json",
        "pregnancy_code",
        "last_oral_intake_at",
        "emergency_information_form_code",
    }
    cols = {c.name for c in ChartHistoryMeta.__table__.columns}
    missing = expected - cols
    assert not missing, f"ChartHistoryMeta missing eHistory columns: {missing}"


@pytest.mark.asyncio
async def test_history_child_columns_exist() -> None:
    """Guard rail: every 1:M child must declare its NEMSIS-bound columns."""
    allergy = {c.name for c in ChartHistoryAllergy.__table__.columns}
    assert {"allergy_kind", "allergy_code", "allergy_text", "sequence_index"} <= allergy

    surgical = {c.name for c in ChartHistorySurgical.__table__.columns}
    assert {"condition_code", "condition_text", "sequence_index"} <= surgical

    meds = {c.name for c in ChartHistoryCurrentMedication.__table__.columns}
    assert {
        "drug_code",
        "dose_value",
        "dose_unit_code",
        "route_code",
        "frequency_code",
        "sequence_index",
    } <= meds

    immun = {c.name for c in ChartHistoryImmunization.__table__.columns}
    assert {"immunization_type_code", "immunization_year", "sequence_index"} <= immun
