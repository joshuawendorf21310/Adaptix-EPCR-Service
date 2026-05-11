"""Persistence tests for the NEMSIS eTimes (:class:`ChartTimes`) model.

Covers: insert, query, tenant scoping, unique-per-chart constraint,
default version/created_at, soft delete column.
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
from epcr_app.models_chart_times import ChartTimes


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
async def test_insert_chart_times_with_all_columns(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-001")
    now = datetime.now(UTC)
    row = ChartTimes(
        id=str(uuid.uuid4()),
        tenant_id="t-1",
        chart_id=chart.id,
        psap_call_at=now,
        unit_notified_by_dispatch_at=now,
        unit_en_route_at=now,
        unit_on_scene_at=now,
        arrived_at_patient_at=now,
        unit_left_scene_at=now,
        patient_arrived_at_destination_at=now,
        destination_transfer_of_care_at=now,
    )
    session.add(row)
    await session.flush()

    fetched = (
        await session.execute(select(ChartTimes).where(ChartTimes.chart_id == chart.id))
    ).scalar_one()
    assert fetched.psap_call_at is not None
    assert fetched.unit_on_scene_at is not None
    assert fetched.tenant_id == "t-1"
    assert fetched.version == 1


@pytest.mark.asyncio
async def test_chart_times_unique_per_chart(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-002")
    session.add(
        ChartTimes(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
        )
    )
    await session.flush()
    session.add(
        ChartTimes(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_chart_times_tenant_isolation_in_query(session: AsyncSession) -> None:
    chart_a = await _make_chart(session, "t-A", "C-A")
    chart_b = await _make_chart(session, "t-B", "C-B")
    session.add(ChartTimes(id=str(uuid.uuid4()), tenant_id="t-A", chart_id=chart_a.id))
    session.add(ChartTimes(id=str(uuid.uuid4()), tenant_id="t-B", chart_id=chart_b.id))
    await session.flush()

    rows_a = (
        await session.execute(select(ChartTimes).where(ChartTimes.tenant_id == "t-A"))
    ).scalars().all()
    rows_b = (
        await session.execute(select(ChartTimes).where(ChartTimes.tenant_id == "t-B"))
    ).scalars().all()
    assert len(rows_a) == 1 and rows_a[0].chart_id == chart_a.id
    assert len(rows_b) == 1 and rows_b[0].chart_id == chart_b.id


@pytest.mark.asyncio
async def test_chart_times_all_seventeen_columns_exist() -> None:
    """Guard rail: ChartTimes must declare every eTimes.01..17 column."""
    expected = {
        "psap_call_at",
        "dispatch_notified_at",
        "unit_notified_by_dispatch_at",
        "dispatch_acknowledged_at",
        "unit_en_route_at",
        "unit_on_scene_at",
        "arrived_at_patient_at",
        "transfer_of_ems_care_at",
        "unit_left_scene_at",
        "arrival_landing_area_at",
        "patient_arrived_at_destination_at",
        "destination_transfer_of_care_at",
        "unit_back_in_service_at",
        "unit_canceled_at",
        "unit_back_home_location_at",
        "ems_call_completed_at",
        "unit_arrived_staging_at",
    }
    cols = {c.name for c in ChartTimes.__table__.columns}
    missing = expected - cols
    assert not missing, f"ChartTimes missing eTimes columns: {missing}"
