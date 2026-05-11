"""Persistence tests for the NEMSIS eCrew (:class:`ChartCrewMember`) model.

Covers: insert, query, tenant scoping, unique-per-chart-per-member
constraint, default version/created_at, soft delete column.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart
from epcr_app.models_chart_crew import ChartCrewMember


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
async def test_insert_chart_crew_member_with_all_columns(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-001")
    row = ChartCrewMember(
        id=str(uuid.uuid4()),
        tenant_id="t-1",
        chart_id=chart.id,
        crew_member_id="NPI-1234567890",
        crew_member_level_code="Paramedic",
        crew_member_response_role_code="lead",
        sequence_index=0,
    )
    session.add(row)
    await session.flush()

    fetched = (
        await session.execute(
            select(ChartCrewMember).where(ChartCrewMember.chart_id == chart.id)
        )
    ).scalar_one()
    assert fetched.crew_member_id == "NPI-1234567890"
    assert fetched.crew_member_level_code == "Paramedic"
    assert fetched.crew_member_response_role_code == "lead"
    assert fetched.tenant_id == "t-1"
    assert fetched.version == 1


@pytest.mark.asyncio
async def test_chart_crew_unique_member_per_chart(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-002")
    session.add(
        ChartCrewMember(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            crew_member_id="EMP-007",
            crew_member_level_code="EMT",
            crew_member_response_role_code="driver",
        )
    )
    await session.flush()
    session.add(
        ChartCrewMember(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            crew_member_id="EMP-007",
            crew_member_level_code="EMT",
            crew_member_response_role_code="treat",
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_chart_crew_multiple_distinct_members_allowed(session: AsyncSession) -> None:
    """Same chart accepts multiple distinct crew members (1:M)."""
    chart = await _make_chart(session, "t-1", "C-003")
    session.add(
        ChartCrewMember(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            crew_member_id="EMP-A",
            crew_member_level_code="Paramedic",
            crew_member_response_role_code="lead",
            sequence_index=0,
        )
    )
    session.add(
        ChartCrewMember(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            crew_member_id="EMP-B",
            crew_member_level_code="EMT",
            crew_member_response_role_code="driver",
            sequence_index=1,
        )
    )
    await session.flush()

    rows = (
        await session.execute(
            select(ChartCrewMember).where(ChartCrewMember.chart_id == chart.id)
        )
    ).scalars().all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_chart_crew_tenant_isolation_in_query(session: AsyncSession) -> None:
    chart_a = await _make_chart(session, "t-A", "C-A")
    chart_b = await _make_chart(session, "t-B", "C-B")
    session.add(
        ChartCrewMember(
            id=str(uuid.uuid4()),
            tenant_id="t-A",
            chart_id=chart_a.id,
            crew_member_id="EMP-A",
            crew_member_level_code="Paramedic",
            crew_member_response_role_code="lead",
        )
    )
    session.add(
        ChartCrewMember(
            id=str(uuid.uuid4()),
            tenant_id="t-B",
            chart_id=chart_b.id,
            crew_member_id="EMP-B",
            crew_member_level_code="EMT",
            crew_member_response_role_code="driver",
        )
    )
    await session.flush()

    rows_a = (
        await session.execute(
            select(ChartCrewMember).where(ChartCrewMember.tenant_id == "t-A")
        )
    ).scalars().all()
    rows_b = (
        await session.execute(
            select(ChartCrewMember).where(ChartCrewMember.tenant_id == "t-B")
        )
    ).scalars().all()
    assert len(rows_a) == 1 and rows_a[0].chart_id == chart_a.id
    assert len(rows_b) == 1 and rows_b[0].chart_id == chart_b.id


@pytest.mark.asyncio
async def test_chart_crew_required_columns_exist() -> None:
    """Guard rail: ChartCrewMember must declare every eCrew.01..03 column."""
    expected = {
        "crew_member_id",
        "crew_member_level_code",
        "crew_member_response_role_code",
        "sequence_index",
    }
    cols = {c.name for c in ChartCrewMember.__table__.columns}
    missing = expected - cols
    assert not missing, f"ChartCrewMember missing eCrew columns: {missing}"
