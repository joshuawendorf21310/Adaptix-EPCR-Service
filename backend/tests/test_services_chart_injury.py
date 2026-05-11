"""Service tests for :class:`ChartInjuryService`.

Covers upsert (injury + acn), partial-update semantics, get, clear_field
on both blocks, tenant isolation, error contracts, ACN parent-required
constraint.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart
from epcr_app.models_chart_injury import ChartInjury, ChartInjuryAcn  # noqa: F401
from epcr_app.services_chart_injury import (
    ChartInjuryAcnPayload,
    ChartInjuryError,
    ChartInjuryPayload,
    ChartInjuryService,
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
async def test_upsert_injury_creates_then_reads(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-1")
    payload = ChartInjuryPayload(
        cause_of_injury_codes_json=["3030001"],
        mechanism_of_injury_code="3040001",
        height_of_fall_feet=10.0,
    )
    result = await ChartInjuryService.upsert_injury(
        session, tenant_id="t-1", chart_id=chart.id, payload=payload, user_id="user-1"
    )
    assert result["cause_of_injury_codes_json"] == ["3030001"]
    assert result["mechanism_of_injury_code"] == "3040001"
    assert result["height_of_fall_feet"] == 10.0
    assert result["chart_id"] == chart.id

    merged = await ChartInjuryService.get(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert merged is not None
    assert merged["injury"]["mechanism_of_injury_code"] == "3040001"
    assert merged["acn"] is None


@pytest.mark.asyncio
async def test_partial_update_preserves_existing(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-2")
    await ChartInjuryService.upsert_injury(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartInjuryPayload(
            mechanism_of_injury_code="3040001",
            height_of_fall_feet=15.0,
        ),
        user_id="user-1",
    )
    # Second upsert only sets airbag_deployment_code; others retained.
    await ChartInjuryService.upsert_injury(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartInjuryPayload(airbag_deployment_code="3070001"),
        user_id="user-2",
    )

    fetched = await ChartInjuryService.get_injury(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert fetched["mechanism_of_injury_code"] == "3040001"
    assert fetched["height_of_fall_feet"] == 15.0
    assert fetched["airbag_deployment_code"] == "3070001"


@pytest.mark.asyncio
async def test_upsert_acn_requires_parent_injury(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-3")
    with pytest.raises(ChartInjuryError) as exc:
        await ChartInjuryService.upsert_acn(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            payload=ChartInjuryAcnPayload(acn_system_company="Acme"),
            user_id="user-1",
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_upsert_acn_creates_after_injury(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-4")
    await ChartInjuryService.upsert_injury(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartInjuryPayload(mechanism_of_injury_code="3040001"),
        user_id="user-1",
    )
    t0 = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
    result = await ChartInjuryService.upsert_acn(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartInjuryAcnPayload(
            acn_system_company="Acme Telematics",
            acn_incident_at=t0,
            acn_delta_velocity=42.5,
            acn_vehicle_model_year=2024,
        ),
        user_id="user-1",
    )
    assert result["acn_system_company"] == "Acme Telematics"
    assert result["acn_delta_velocity"] == 42.5
    assert result["acn_vehicle_model_year"] == 2024
    assert result["acn_incident_at"].startswith("2026-05-10T12:00:00")

    merged = await ChartInjuryService.get(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert merged["acn"]["acn_system_company"] == "Acme Telematics"


@pytest.mark.asyncio
async def test_clear_field_injury_block(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-5")
    await ChartInjuryService.upsert_injury(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartInjuryPayload(mechanism_of_injury_code="3040001"),
        user_id="user-1",
    )
    cleared = await ChartInjuryService.clear_field(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        field="mechanism_of_injury_code",
        block="injury",
        user_id="user-1",
    )
    assert cleared["mechanism_of_injury_code"] is None


@pytest.mark.asyncio
async def test_clear_field_acn_block(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-6")
    await ChartInjuryService.upsert_injury(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartInjuryPayload(),
        user_id="user-1",
    )
    await ChartInjuryService.upsert_acn(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartInjuryAcnPayload(acn_system_company="Acme"),
        user_id="user-1",
    )
    cleared = await ChartInjuryService.clear_field(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        field="acn_system_company",
        block="acn",
        user_id="user-1",
    )
    assert cleared["acn_system_company"] is None


@pytest.mark.asyncio
async def test_clear_field_unknown_field_raises(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-7")
    await ChartInjuryService.upsert_injury(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartInjuryPayload(),
        user_id="user-1",
    )
    with pytest.raises(ChartInjuryError) as exc:
        await ChartInjuryService.clear_field(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            field="not_a_real_column",
            block="injury",
            user_id="user-1",
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_clear_field_unknown_block_raises(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-7b")
    await ChartInjuryService.upsert_injury(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartInjuryPayload(),
        user_id="user-1",
    )
    with pytest.raises(ChartInjuryError) as exc:
        await ChartInjuryService.clear_field(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            field="mechanism_of_injury_code",
            block="bogus",
            user_id="user-1",
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_tenant_scoping_returns_none_for_wrong_tenant(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-A", "C-A")
    await ChartInjuryService.upsert_injury(
        session,
        tenant_id="t-A",
        chart_id=chart.id,
        payload=ChartInjuryPayload(mechanism_of_injury_code="3040001"),
        user_id="user-1",
    )
    leaked = await ChartInjuryService.get(
        session, tenant_id="t-B", chart_id=chart.id
    )
    assert leaked is None


@pytest.mark.asyncio
async def test_get_returns_none_when_absent(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-empty")
    result = await ChartInjuryService.get(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert result is None


@pytest.mark.asyncio
async def test_upsert_requires_tenant_and_chart(session: AsyncSession) -> None:
    with pytest.raises(ChartInjuryError):
        await ChartInjuryService.upsert_injury(
            session,
            tenant_id="",
            chart_id="x",
            payload=ChartInjuryPayload(),
            user_id=None,
        )
    with pytest.raises(ChartInjuryError):
        await ChartInjuryService.upsert_injury(
            session,
            tenant_id="t",
            chart_id="",
            payload=ChartInjuryPayload(),
            user_id=None,
        )
