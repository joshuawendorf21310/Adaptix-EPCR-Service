"""Service tests for :class:`ChartTimesService`.

Covers upsert, partial-update semantics, get, clear_field, tenant
isolation, and error contracts.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart
from epcr_app.models_chart_times import ChartTimes  # noqa: F401 - registers table
from epcr_app.services_chart_times import (
    ChartTimesError,
    ChartTimesPayload,
    ChartTimesService,
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
async def test_upsert_creates_then_reads(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-1")
    t0 = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
    payload = ChartTimesPayload(psap_call_at=t0, unit_en_route_at=t0 + timedelta(minutes=1))
    result = await ChartTimesService.upsert(
        session, tenant_id="t-1", chart_id=chart.id, payload=payload, user_id="user-1"
    )
    assert result["psap_call_at"] is not None
    assert result["unit_en_route_at"] is not None
    assert result["chart_id"] == chart.id

    fetched = await ChartTimesService.get(session, tenant_id="t-1", chart_id=chart.id)
    assert fetched is not None
    # SQLite drops tz info; compare on the naive timestamp suffix.
    assert fetched["psap_call_at"].startswith("2026-05-10T12:00:00")


@pytest.mark.asyncio
async def test_partial_update_preserves_existing(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-2")
    t0 = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
    t1 = t0 + timedelta(minutes=5)

    await ChartTimesService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartTimesPayload(psap_call_at=t0, unit_on_scene_at=t1),
        user_id="user-1",
    )
    # second upsert only sets unit_left_scene_at; psap_call_at must remain
    t2 = t1 + timedelta(minutes=10)
    await ChartTimesService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartTimesPayload(unit_left_scene_at=t2),
        user_id="user-2",
    )

    fetched = await ChartTimesService.get(session, tenant_id="t-1", chart_id=chart.id)
    # SQLite drops tz info; compare on the naive timestamp prefix only.
    assert fetched["psap_call_at"].startswith("2026-05-10T12:00:00")
    assert fetched["unit_on_scene_at"].startswith("2026-05-10T12:05:00")
    assert fetched["unit_left_scene_at"].startswith("2026-05-10T12:15:00")


@pytest.mark.asyncio
async def test_clear_field_sets_null(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-3")
    t0 = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
    await ChartTimesService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartTimesPayload(psap_call_at=t0),
        user_id="user-1",
    )
    cleared = await ChartTimesService.clear_field(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        field="psap_call_at",
        user_id="user-1",
    )
    assert cleared["psap_call_at"] is None


@pytest.mark.asyncio
async def test_clear_field_unknown_raises(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-4")
    await ChartTimesService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartTimesPayload(),
        user_id="user-1",
    )
    with pytest.raises(ChartTimesError) as exc:
        await ChartTimesService.clear_field(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            field="not_a_real_column",
            user_id="user-1",
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_tenant_scoping_returns_none_for_wrong_tenant(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-A", "C-A")
    await ChartTimesService.upsert(
        session,
        tenant_id="t-A",
        chart_id=chart.id,
        payload=ChartTimesPayload(psap_call_at=datetime.now(UTC)),
        user_id="user-1",
    )
    leaked = await ChartTimesService.get(session, tenant_id="t-B", chart_id=chart.id)
    assert leaked is None


@pytest.mark.asyncio
async def test_get_returns_none_when_absent(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-empty")
    result = await ChartTimesService.get(session, tenant_id="t-1", chart_id=chart.id)
    assert result is None


@pytest.mark.asyncio
async def test_upsert_requires_tenant_and_chart(session: AsyncSession) -> None:
    with pytest.raises(ChartTimesError):
        await ChartTimesService.upsert(
            session,
            tenant_id="",
            chart_id="x",
            payload=ChartTimesPayload(),
            user_id=None,
        )
    with pytest.raises(ChartTimesError):
        await ChartTimesService.upsert(
            session,
            tenant_id="t",
            chart_id="",
            payload=ChartTimesPayload(),
            user_id=None,
        )
