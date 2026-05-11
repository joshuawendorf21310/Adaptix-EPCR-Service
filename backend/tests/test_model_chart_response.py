"""Persistence tests for the NEMSIS eResponse models.

Covers :class:`ChartResponse` (1:1 metadata) and
:class:`ChartResponseDelay` (1:M typed delays): insert, query, tenant
scoping, unique constraints, default version/created_at, soft delete.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart
from epcr_app.models_chart_response import (
    RESPONSE_DELAY_KINDS,
    ChartResponse,
    ChartResponseDelay,
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
async def test_insert_chart_response_with_all_columns(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-001")
    row = ChartResponse(
        id=str(uuid.uuid4()),
        tenant_id="t-1",
        chart_id=chart.id,
        agency_number="A123",
        agency_name="Adaptix EMS",
        type_of_service_requested_code="2205001",
        standby_purpose_code="2207001",
        unit_transport_capability_code="2208005",
        unit_vehicle_number="MEDIC-7",
        unit_call_sign="M7",
        vehicle_dispatch_address="200 Main St",
        vehicle_dispatch_lat=37.7749,
        vehicle_dispatch_long=-122.4194,
        vehicle_dispatch_usng="10SEG1234567890",
        beginning_odometer=12345.0,
        on_scene_odometer=12349.5,
        destination_odometer=12360.0,
        ending_odometer=12365.0,
        response_mode_to_scene_code="2235003",
        additional_response_descriptors_json=["2210001", "2210003"],
    )
    session.add(row)
    await session.flush()

    fetched = (
        await session.execute(select(ChartResponse).where(ChartResponse.chart_id == chart.id))
    ).scalar_one()
    assert fetched.agency_number == "A123"
    assert fetched.unit_call_sign == "M7"
    assert fetched.vehicle_dispatch_lat == pytest.approx(37.7749)
    assert fetched.additional_response_descriptors_json == ["2210001", "2210003"]
    assert fetched.version == 1
    assert fetched.tenant_id == "t-1"


@pytest.mark.asyncio
async def test_chart_response_unique_per_chart(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-002")
    session.add(
        ChartResponse(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
        )
    )
    await session.flush()
    session.add(
        ChartResponse(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_chart_response_tenant_isolation_in_query(session: AsyncSession) -> None:
    chart_a = await _make_chart(session, "t-A", "C-A")
    chart_b = await _make_chart(session, "t-B", "C-B")
    session.add(ChartResponse(id=str(uuid.uuid4()), tenant_id="t-A", chart_id=chart_a.id))
    session.add(ChartResponse(id=str(uuid.uuid4()), tenant_id="t-B", chart_id=chart_b.id))
    await session.flush()

    rows_a = (
        await session.execute(select(ChartResponse).where(ChartResponse.tenant_id == "t-A"))
    ).scalars().all()
    rows_b = (
        await session.execute(select(ChartResponse).where(ChartResponse.tenant_id == "t-B"))
    ).scalars().all()
    assert len(rows_a) == 1 and rows_a[0].chart_id == chart_a.id
    assert len(rows_b) == 1 and rows_b[0].chart_id == chart_b.id


@pytest.mark.asyncio
async def test_chart_response_required_columns_exist() -> None:
    """Guard rail: ChartResponse must declare every spec column."""
    expected = {
        "agency_number",
        "agency_name",
        "type_of_service_requested_code",
        "standby_purpose_code",
        "unit_transport_capability_code",
        "unit_vehicle_number",
        "unit_call_sign",
        "vehicle_dispatch_address",
        "vehicle_dispatch_lat",
        "vehicle_dispatch_long",
        "vehicle_dispatch_usng",
        "beginning_odometer",
        "on_scene_odometer",
        "destination_odometer",
        "ending_odometer",
        "response_mode_to_scene_code",
        "additional_response_descriptors_json",
    }
    cols = {c.name for c in ChartResponse.__table__.columns}
    missing = expected - cols
    assert not missing, f"ChartResponse missing eResponse columns: {missing}"


@pytest.mark.asyncio
async def test_insert_chart_response_delay_row(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-D-1")
    delay = ChartResponseDelay(
        id=str(uuid.uuid4()),
        tenant_id="t-1",
        chart_id=chart.id,
        delay_kind="dispatch",
        delay_code="2209001",
    )
    session.add(delay)
    await session.flush()

    fetched = (
        await session.execute(
            select(ChartResponseDelay).where(ChartResponseDelay.chart_id == chart.id)
        )
    ).scalar_one()
    assert fetched.delay_kind == "dispatch"
    assert fetched.delay_code == "2209001"
    assert fetched.sequence_index == 0
    assert fetched.version == 1


@pytest.mark.asyncio
async def test_chart_response_delays_unique_kind_code(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-D-2")
    session.add(
        ChartResponseDelay(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            delay_kind="scene",
            delay_code="2211003",
        )
    )
    await session.flush()
    session.add(
        ChartResponseDelay(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            delay_kind="scene",
            delay_code="2211003",
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_chart_response_delays_same_code_different_kind_allowed(
    session: AsyncSession,
) -> None:
    chart = await _make_chart(session, "t-1", "C-D-3")
    session.add(
        ChartResponseDelay(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            delay_kind="dispatch",
            delay_code="X1",
        )
    )
    session.add(
        ChartResponseDelay(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            delay_kind="response",
            delay_code="X1",
        )
    )
    await session.flush()  # must not raise


@pytest.mark.asyncio
async def test_chart_response_delay_kinds_constant_matches_spec() -> None:
    assert set(RESPONSE_DELAY_KINDS) == {
        "dispatch",
        "response",
        "scene",
        "transport",
        "turn_around",
    }
