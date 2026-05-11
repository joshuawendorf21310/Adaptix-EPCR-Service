"""Service tests for :class:`ChartDispositionService`.

Covers upsert, partial-update semantics, get, clear_field, tenant
isolation, JSON list columns, and error contracts.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart
from epcr_app.models_chart_disposition import ChartDisposition  # noqa: F401
from epcr_app.services_chart_disposition import (
    ChartDispositionError,
    ChartDispositionPayload,
    ChartDispositionService,
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
    payload = ChartDispositionPayload(
        destination_name="Memorial Hospital",
        incident_patient_disposition_code="4212001",
        transport_disposition_code="4227005",
        level_of_care_provided_code="4218015",
        hospital_capability_codes_json=["4209007", "4209013"],
    )
    result = await ChartDispositionService.upsert(
        session, tenant_id="t-1", chart_id=chart.id, payload=payload, user_id="user-1"
    )
    assert result["destination_name"] == "Memorial Hospital"
    assert result["incident_patient_disposition_code"] == "4212001"
    assert result["hospital_capability_codes_json"] == ["4209007", "4209013"]
    assert result["chart_id"] == chart.id

    fetched = await ChartDispositionService.get(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert fetched is not None
    assert fetched["destination_name"] == "Memorial Hospital"


@pytest.mark.asyncio
async def test_partial_update_preserves_existing(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-2")

    await ChartDispositionService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartDispositionPayload(
            destination_name="First Hospital",
            transport_disposition_code="4227005",
        ),
        user_id="user-1",
    )
    # Second upsert only sets level_of_care_provided_code;
    # destination_name and transport_disposition_code must remain.
    await ChartDispositionService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartDispositionPayload(level_of_care_provided_code="4218015"),
        user_id="user-2",
    )

    fetched = await ChartDispositionService.get(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert fetched["destination_name"] == "First Hospital"
    assert fetched["transport_disposition_code"] == "4227005"
    assert fetched["level_of_care_provided_code"] == "4218015"


@pytest.mark.asyncio
async def test_upsert_replaces_json_list(session: AsyncSession) -> None:
    """JSON list columns are replaced wholesale on subsequent upserts."""
    chart = await _seed_chart(session, "t-1", "C-json")
    await ChartDispositionService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartDispositionPayload(
            hospital_capability_codes_json=["4209007"]
        ),
        user_id="u",
    )
    await ChartDispositionService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartDispositionPayload(
            hospital_capability_codes_json=["4209013", "4209019"]
        ),
        user_id="u",
    )
    fetched = await ChartDispositionService.get(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert fetched["hospital_capability_codes_json"] == ["4209013", "4209019"]


@pytest.mark.asyncio
async def test_clear_field_sets_null(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-3")
    await ChartDispositionService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartDispositionPayload(destination_name="Mercy"),
        user_id="user-1",
    )
    cleared = await ChartDispositionService.clear_field(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        field="destination_name",
        user_id="user-1",
    )
    assert cleared["destination_name"] is None


@pytest.mark.asyncio
async def test_clear_field_unknown_raises(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-4")
    await ChartDispositionService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartDispositionPayload(),
        user_id="user-1",
    )
    with pytest.raises(ChartDispositionError) as exc:
        await ChartDispositionService.clear_field(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            field="not_a_real_column",
            user_id="user-1",
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_tenant_scoping_returns_none_for_wrong_tenant(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-A", "C-A")
    await ChartDispositionService.upsert(
        session,
        tenant_id="t-A",
        chart_id=chart.id,
        payload=ChartDispositionPayload(destination_name="Tenant-A Hospital"),
        user_id="user-1",
    )
    leaked = await ChartDispositionService.get(
        session, tenant_id="t-B", chart_id=chart.id
    )
    assert leaked is None


@pytest.mark.asyncio
async def test_get_returns_none_when_absent(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-empty")
    result = await ChartDispositionService.get(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert result is None


@pytest.mark.asyncio
async def test_upsert_requires_tenant_and_chart(session: AsyncSession) -> None:
    with pytest.raises(ChartDispositionError):
        await ChartDispositionService.upsert(
            session,
            tenant_id="",
            chart_id="x",
            payload=ChartDispositionPayload(),
            user_id=None,
        )
    with pytest.raises(ChartDispositionError):
        await ChartDispositionService.upsert(
            session,
            tenant_id="t",
            chart_id="",
            payload=ChartDispositionPayload(),
            user_id=None,
        )
