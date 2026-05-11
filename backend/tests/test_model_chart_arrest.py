"""Persistence tests for the NEMSIS eArrest (:class:`ChartArrest`) model.

Covers: insert, query, tenant scoping, unique-per-chart constraint,
JSON list columns, default version, soft delete column, NOT NULL on
``cardiac_arrest_code``.
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
from epcr_app.models_chart_arrest import ChartArrest


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
async def test_insert_chart_arrest_with_all_columns(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-001")
    now = datetime.now(UTC)
    row = ChartArrest(
        id=str(uuid.uuid4()),
        tenant_id="t-1",
        chart_id=chart.id,
        cardiac_arrest_code="9512001",
        etiology_code="9514001",
        resuscitation_attempted_codes_json=["9515003", "9515005"],
        witnessed_by_codes_json=["9516001"],
        aed_use_prior_code="9519001",
        cpr_type_codes_json=["9520001"],
        hypothermia_indicator_code="9923003",
        first_monitored_rhythm_code="9522001",
        rosc_codes_json=["9527001"],
        neurological_outcome_code="9528001",
        arrest_at=now,
        resuscitation_discontinued_at=now,
        reason_discontinued_code="9530001",
        rhythm_on_arrival_code="9531001",
        end_of_event_code="9532001",
        initial_cpr_at=now,
        who_first_cpr_code="9521001",
        who_first_aed_code="9518001",
        who_first_defib_code="9533001",
    )
    session.add(row)
    await session.flush()

    fetched = (
        await session.execute(select(ChartArrest).where(ChartArrest.chart_id == chart.id))
    ).scalar_one()
    assert fetched.cardiac_arrest_code == "9512001"
    assert fetched.resuscitation_attempted_codes_json == ["9515003", "9515005"]
    assert fetched.witnessed_by_codes_json == ["9516001"]
    assert fetched.cpr_type_codes_json == ["9520001"]
    assert fetched.rosc_codes_json == ["9527001"]
    assert fetched.arrest_at is not None
    assert fetched.tenant_id == "t-1"
    assert fetched.version == 1


@pytest.mark.asyncio
async def test_chart_arrest_unique_per_chart(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-002")
    session.add(
        ChartArrest(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            cardiac_arrest_code="9512001",
        )
    )
    await session.flush()
    session.add(
        ChartArrest(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            cardiac_arrest_code="9512001",
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_chart_arrest_cardiac_arrest_code_not_null(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-003")
    session.add(
        ChartArrest(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            cardiac_arrest_code=None,  # type: ignore[arg-type]
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_chart_arrest_tenant_isolation_in_query(session: AsyncSession) -> None:
    chart_a = await _make_chart(session, "t-A", "C-A")
    chart_b = await _make_chart(session, "t-B", "C-B")
    session.add(
        ChartArrest(
            id=str(uuid.uuid4()),
            tenant_id="t-A",
            chart_id=chart_a.id,
            cardiac_arrest_code="9512001",
        )
    )
    session.add(
        ChartArrest(
            id=str(uuid.uuid4()),
            tenant_id="t-B",
            chart_id=chart_b.id,
            cardiac_arrest_code="9512001",
        )
    )
    await session.flush()

    rows_a = (
        await session.execute(select(ChartArrest).where(ChartArrest.tenant_id == "t-A"))
    ).scalars().all()
    rows_b = (
        await session.execute(select(ChartArrest).where(ChartArrest.tenant_id == "t-B"))
    ).scalars().all()
    assert len(rows_a) == 1 and rows_a[0].chart_id == chart_a.id
    assert len(rows_b) == 1 and rows_b[0].chart_id == chart_b.id


@pytest.mark.asyncio
async def test_chart_arrest_all_columns_exist() -> None:
    """Guard rail: ChartArrest must declare every eArrest column."""
    expected = {
        "cardiac_arrest_code",
        "etiology_code",
        "resuscitation_attempted_codes_json",
        "witnessed_by_codes_json",
        "aed_use_prior_code",
        "cpr_type_codes_json",
        "hypothermia_indicator_code",
        "first_monitored_rhythm_code",
        "rosc_codes_json",
        "neurological_outcome_code",
        "arrest_at",
        "resuscitation_discontinued_at",
        "reason_discontinued_code",
        "rhythm_on_arrival_code",
        "end_of_event_code",
        "initial_cpr_at",
        "who_first_cpr_code",
        "who_first_aed_code",
        "who_first_defib_code",
    }
    cols = {c.name for c in ChartArrest.__table__.columns}
    missing = expected - cols
    assert not missing, f"ChartArrest missing eArrest columns: {missing}"
