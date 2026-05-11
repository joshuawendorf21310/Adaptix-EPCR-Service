"""Service tests for :class:`ChartDispatchService`.

Covers upsert, partial-update semantics, get, clear_field, tenant
isolation, and error contracts.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart
from epcr_app.models_chart_dispatch import ChartDispatch  # noqa: F401 - registers table
from epcr_app.services_chart_dispatch import (
    ChartDispatchError,
    ChartDispatchPayload,
    ChartDispatchService,
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
    payload = ChartDispatchPayload(
        dispatch_reason_code="2301001",
        emd_performed_code="2302003",
        dispatch_center_id="DC-1",
    )
    result = await ChartDispatchService.upsert(
        session, tenant_id="t-1", chart_id=chart.id, payload=payload, user_id="user-1"
    )
    assert result["dispatch_reason_code"] == "2301001"
    assert result["emd_performed_code"] == "2302003"
    assert result["dispatch_center_id"] == "DC-1"
    assert result["chart_id"] == chart.id

    fetched = await ChartDispatchService.get(session, tenant_id="t-1", chart_id=chart.id)
    assert fetched is not None
    assert fetched["dispatch_reason_code"] == "2301001"


@pytest.mark.asyncio
async def test_partial_update_preserves_existing(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-2")

    await ChartDispatchService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartDispatchPayload(
            dispatch_reason_code="2301001",
            emd_performed_code="2302003",
        ),
        user_id="user-1",
    )
    # second upsert only sets dispatch_priority_code; others must remain
    await ChartDispatchService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartDispatchPayload(dispatch_priority_code="2305003"),
        user_id="user-2",
    )

    fetched = await ChartDispatchService.get(session, tenant_id="t-1", chart_id=chart.id)
    assert fetched["dispatch_reason_code"] == "2301001"
    assert fetched["emd_performed_code"] == "2302003"
    assert fetched["dispatch_priority_code"] == "2305003"


@pytest.mark.asyncio
async def test_clear_field_sets_null(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-3")
    await ChartDispatchService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartDispatchPayload(dispatch_reason_code="2301001"),
        user_id="user-1",
    )
    cleared = await ChartDispatchService.clear_field(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        field="dispatch_reason_code",
        user_id="user-1",
    )
    assert cleared["dispatch_reason_code"] is None


@pytest.mark.asyncio
async def test_clear_field_unknown_raises(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-4")
    await ChartDispatchService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartDispatchPayload(),
        user_id="user-1",
    )
    with pytest.raises(ChartDispatchError) as exc:
        await ChartDispatchService.clear_field(
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
    await ChartDispatchService.upsert(
        session,
        tenant_id="t-A",
        chart_id=chart.id,
        payload=ChartDispatchPayload(dispatch_reason_code="2301001"),
        user_id="user-1",
    )
    leaked = await ChartDispatchService.get(session, tenant_id="t-B", chart_id=chart.id)
    assert leaked is None


@pytest.mark.asyncio
async def test_get_returns_none_when_absent(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-empty")
    result = await ChartDispatchService.get(session, tenant_id="t-1", chart_id=chart.id)
    assert result is None


@pytest.mark.asyncio
async def test_upsert_requires_tenant_and_chart(session: AsyncSession) -> None:
    with pytest.raises(ChartDispatchError):
        await ChartDispatchService.upsert(
            session,
            tenant_id="",
            chart_id="x",
            payload=ChartDispatchPayload(),
            user_id=None,
        )
    with pytest.raises(ChartDispatchError):
        await ChartDispatchService.upsert(
            session,
            tenant_id="t",
            chart_id="",
            payload=ChartDispatchPayload(),
            user_id=None,
        )
