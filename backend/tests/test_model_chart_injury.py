"""Persistence tests for NEMSIS eInjury (:class:`ChartInjury`,
:class:`ChartInjuryAcn`) models.

Covers: insert, query, tenant scoping, unique-per-chart constraints,
JSON list column round-trip, ACN FK to injury, default version.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart
from epcr_app.models_chart_injury import ChartInjury, ChartInjuryAcn


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
async def test_insert_chart_injury_with_json_lists(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-001")
    row = ChartInjury(
        id=str(uuid.uuid4()),
        tenant_id="t-1",
        chart_id=chart.id,
        cause_of_injury_codes_json=["3030001", "3030003"],
        mechanism_of_injury_code="3040001",
        trauma_triage_high_codes_json=["3050001"],
        height_of_fall_feet=12.5,
    )
    session.add(row)
    await session.flush()

    fetched = (
        await session.execute(
            select(ChartInjury).where(ChartInjury.chart_id == chart.id)
        )
    ).scalar_one()
    assert fetched.cause_of_injury_codes_json == ["3030001", "3030003"]
    assert fetched.mechanism_of_injury_code == "3040001"
    assert fetched.trauma_triage_high_codes_json == ["3050001"]
    assert fetched.height_of_fall_feet == 12.5
    assert fetched.tenant_id == "t-1"
    assert fetched.version == 1


@pytest.mark.asyncio
async def test_chart_injury_unique_per_chart(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-002")
    session.add(
        ChartInjury(id=str(uuid.uuid4()), tenant_id="t-1", chart_id=chart.id)
    )
    await session.flush()
    session.add(
        ChartInjury(id=str(uuid.uuid4()), tenant_id="t-1", chart_id=chart.id)
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_chart_injury_tenant_isolation_in_query(session: AsyncSession) -> None:
    chart_a = await _make_chart(session, "t-A", "C-A")
    chart_b = await _make_chart(session, "t-B", "C-B")
    session.add(ChartInjury(id=str(uuid.uuid4()), tenant_id="t-A", chart_id=chart_a.id))
    session.add(ChartInjury(id=str(uuid.uuid4()), tenant_id="t-B", chart_id=chart_b.id))
    await session.flush()

    rows_a = (
        await session.execute(select(ChartInjury).where(ChartInjury.tenant_id == "t-A"))
    ).scalars().all()
    rows_b = (
        await session.execute(select(ChartInjury).where(ChartInjury.tenant_id == "t-B"))
    ).scalars().all()
    assert len(rows_a) == 1 and rows_a[0].chart_id == chart_a.id
    assert len(rows_b) == 1 and rows_b[0].chart_id == chart_b.id


@pytest.mark.asyncio
async def test_chart_injury_acn_insert_and_fk(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-003")
    injury = ChartInjury(id=str(uuid.uuid4()), tenant_id="t-1", chart_id=chart.id)
    session.add(injury)
    await session.flush()

    acn = ChartInjuryAcn(
        id=str(uuid.uuid4()),
        tenant_id="t-1",
        chart_id=chart.id,
        injury_id=injury.id,
        acn_system_company="Acme Telematics",
        acn_incident_at=datetime.now(UTC),
        acn_delta_velocity=42.5,
        acn_vehicle_model_year=2024,
        acn_pdof=90,
    )
    session.add(acn)
    await session.flush()

    fetched = (
        await session.execute(
            select(ChartInjuryAcn).where(ChartInjuryAcn.chart_id == chart.id)
        )
    ).scalar_one()
    assert fetched.acn_system_company == "Acme Telematics"
    assert fetched.acn_delta_velocity == 42.5
    assert fetched.acn_vehicle_model_year == 2024
    assert fetched.acn_pdof == 90
    assert fetched.injury_id == injury.id


@pytest.mark.asyncio
async def test_chart_injury_acn_unique_per_chart(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-004")
    injury = ChartInjury(id=str(uuid.uuid4()), tenant_id="t-1", chart_id=chart.id)
    session.add(injury)
    await session.flush()

    session.add(
        ChartInjuryAcn(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            injury_id=injury.id,
        )
    )
    await session.flush()
    session.add(
        ChartInjuryAcn(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            injury_id=injury.id,
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_chart_injury_all_eInjury_01_10_columns_exist() -> None:
    """Guard rail: ChartInjury must declare every eInjury.01..10 column."""
    expected = {
        "cause_of_injury_codes_json",
        "mechanism_of_injury_code",
        "trauma_triage_high_codes_json",
        "trauma_triage_moderate_codes_json",
        "vehicle_impact_area_code",
        "patient_location_in_vehicle_code",
        "occupant_safety_equipment_codes_json",
        "airbag_deployment_code",
        "height_of_fall_feet",
        "osha_ppe_used_codes_json",
    }
    cols = {c.name for c in ChartInjury.__table__.columns}
    missing = expected - cols
    assert not missing, f"ChartInjury missing eInjury columns: {missing}"


@pytest.mark.asyncio
async def test_chart_injury_acn_all_eInjury_11_29_columns_exist() -> None:
    """Guard rail: ChartInjuryAcn must declare every eInjury.11..29 column."""
    expected = {
        "acn_system_company",
        "acn_incident_id",
        "acn_callback_phone",
        "acn_incident_at",
        "acn_incident_location",
        "acn_vehicle_body_type_code",
        "acn_vehicle_manufacturer",
        "acn_vehicle_make",
        "acn_vehicle_model",
        "acn_vehicle_model_year",
        "acn_multiple_impacts_code",
        "acn_delta_velocity",
        "acn_high_probability_code",
        "acn_pdof",
        "acn_rollover_code",
        "acn_seat_location_code",
        "seat_occupied_code",
        "acn_seatbelt_use_code",
        "acn_airbag_deployed_code",
    }
    cols = {c.name for c in ChartInjuryAcn.__table__.columns}
    missing = expected - cols
    assert not missing, f"ChartInjuryAcn missing eInjury columns: {missing}"
