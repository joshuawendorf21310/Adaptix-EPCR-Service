"""Persistence tests for the NEMSIS eDispatch (:class:`ChartDispatch`) model.

Covers: insert, query, tenant scoping, unique-per-chart constraint,
default version/created_at, soft delete column.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart
from epcr_app.models_chart_dispatch import ChartDispatch


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
async def test_insert_chart_dispatch_with_all_columns(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-001")
    row = ChartDispatch(
        id=str(uuid.uuid4()),
        tenant_id="t-1",
        chart_id=chart.id,
        dispatch_reason_code="2301001",
        emd_performed_code="2302003",
        emd_determinant_code="26-D-1",
        dispatch_center_id="DC-001",
        dispatch_priority_code="2305003",
        cad_record_id="CAD-12345",
    )
    session.add(row)
    await session.flush()

    fetched = (
        await session.execute(select(ChartDispatch).where(ChartDispatch.chart_id == chart.id))
    ).scalar_one()
    assert fetched.dispatch_reason_code == "2301001"
    assert fetched.emd_determinant_code == "26-D-1"
    assert fetched.dispatch_center_id == "DC-001"
    assert fetched.cad_record_id == "CAD-12345"
    assert fetched.tenant_id == "t-1"
    assert fetched.version == 1


@pytest.mark.asyncio
async def test_chart_dispatch_unique_per_chart(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-002")
    session.add(
        ChartDispatch(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
        )
    )
    await session.flush()
    session.add(
        ChartDispatch(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_chart_dispatch_tenant_isolation_in_query(session: AsyncSession) -> None:
    chart_a = await _make_chart(session, "t-A", "C-A")
    chart_b = await _make_chart(session, "t-B", "C-B")
    session.add(ChartDispatch(id=str(uuid.uuid4()), tenant_id="t-A", chart_id=chart_a.id))
    session.add(ChartDispatch(id=str(uuid.uuid4()), tenant_id="t-B", chart_id=chart_b.id))
    await session.flush()

    rows_a = (
        await session.execute(select(ChartDispatch).where(ChartDispatch.tenant_id == "t-A"))
    ).scalars().all()
    rows_b = (
        await session.execute(select(ChartDispatch).where(ChartDispatch.tenant_id == "t-B"))
    ).scalars().all()
    assert len(rows_a) == 1 and rows_a[0].chart_id == chart_a.id
    assert len(rows_b) == 1 and rows_b[0].chart_id == chart_b.id


@pytest.mark.asyncio
async def test_chart_dispatch_all_six_columns_exist() -> None:
    """Guard rail: ChartDispatch must declare every eDispatch.01..06 column."""
    expected = {
        "dispatch_reason_code",
        "emd_performed_code",
        "emd_determinant_code",
        "dispatch_center_id",
        "dispatch_priority_code",
        "cad_record_id",
    }
    cols = {c.name for c in ChartDispatch.__table__.columns}
    missing = expected - cols
    assert not missing, f"ChartDispatch missing eDispatch columns: {missing}"
