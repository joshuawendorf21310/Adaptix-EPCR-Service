"""Service tests for :class:`ChartArrestService`.

Covers upsert, partial-update semantics, get, clear_field, tenant
isolation, error contracts, and JSON list column behaviour.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart
from epcr_app.models_chart_arrest import ChartArrest  # noqa: F401 - registers table
from epcr_app.services_chart_arrest import (
    ChartArrestError,
    ChartArrestPayload,
    ChartArrestService,
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
    payload = ChartArrestPayload(
        cardiac_arrest_code="9512001",
        etiology_code="9514001",
        resuscitation_attempted_codes_json=["9515003", "9515005"],
        witnessed_by_codes_json=["9516001"],
        cpr_type_codes_json=["9520001"],
        rosc_codes_json=["9527001"],
        arrest_at=t0,
        initial_cpr_at=t0 + timedelta(minutes=1),
    )
    result = await ChartArrestService.upsert(
        session, tenant_id="t-1", chart_id=chart.id, payload=payload, user_id="user-1"
    )
    assert result["cardiac_arrest_code"] == "9512001"
    assert result["chart_id"] == chart.id
    assert result["resuscitation_attempted_codes_json"] == ["9515003", "9515005"]
    assert result["arrest_at"].startswith("2026-05-10T12:00:00")

    fetched = await ChartArrestService.get(session, tenant_id="t-1", chart_id=chart.id)
    assert fetched is not None
    assert fetched["cardiac_arrest_code"] == "9512001"
    assert fetched["witnessed_by_codes_json"] == ["9516001"]


@pytest.mark.asyncio
async def test_upsert_initial_requires_cardiac_arrest_code(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-req")
    with pytest.raises(ChartArrestError) as exc:
        await ChartArrestService.upsert(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            payload=ChartArrestPayload(etiology_code="9514001"),
            user_id="user-1",
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_partial_update_preserves_existing(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-2")
    t0 = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)

    await ChartArrestService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartArrestPayload(
            cardiac_arrest_code="9512001",
            etiology_code="9514001",
            arrest_at=t0,
            cpr_type_codes_json=["9520001"],
        ),
        user_id="user-1",
    )
    # Second upsert only adds a new field; existing values must remain.
    await ChartArrestService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartArrestPayload(first_monitored_rhythm_code="9522001"),
        user_id="user-2",
    )

    fetched = await ChartArrestService.get(session, tenant_id="t-1", chart_id=chart.id)
    assert fetched["cardiac_arrest_code"] == "9512001"
    assert fetched["etiology_code"] == "9514001"
    assert fetched["first_monitored_rhythm_code"] == "9522001"
    assert fetched["cpr_type_codes_json"] == ["9520001"]
    assert fetched["arrest_at"].startswith("2026-05-10T12:00:00")


@pytest.mark.asyncio
async def test_clear_field_sets_null(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-3")
    await ChartArrestService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartArrestPayload(
            cardiac_arrest_code="9512001",
            etiology_code="9514001",
            witnessed_by_codes_json=["9516001"],
        ),
        user_id="user-1",
    )
    cleared = await ChartArrestService.clear_field(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        field="etiology_code",
        user_id="user-1",
    )
    assert cleared["etiology_code"] is None
    assert cleared["cardiac_arrest_code"] == "9512001"


@pytest.mark.asyncio
async def test_clear_field_can_clear_list(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-3b")
    await ChartArrestService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartArrestPayload(
            cardiac_arrest_code="9512001",
            witnessed_by_codes_json=["9516001", "9516003"],
        ),
        user_id="user-1",
    )
    cleared = await ChartArrestService.clear_field(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        field="witnessed_by_codes_json",
        user_id="user-1",
    )
    assert cleared["witnessed_by_codes_json"] is None


@pytest.mark.asyncio
async def test_clear_cardiac_arrest_code_forbidden(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-3c")
    await ChartArrestService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartArrestPayload(cardiac_arrest_code="9512001"),
        user_id="user-1",
    )
    with pytest.raises(ChartArrestError) as exc:
        await ChartArrestService.clear_field(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            field="cardiac_arrest_code",
            user_id="user-1",
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_clear_field_unknown_raises(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-4")
    await ChartArrestService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartArrestPayload(cardiac_arrest_code="9512001"),
        user_id="user-1",
    )
    with pytest.raises(ChartArrestError) as exc:
        await ChartArrestService.clear_field(
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
    await ChartArrestService.upsert(
        session,
        tenant_id="t-A",
        chart_id=chart.id,
        payload=ChartArrestPayload(cardiac_arrest_code="9512001"),
        user_id="user-1",
    )
    leaked = await ChartArrestService.get(session, tenant_id="t-B", chart_id=chart.id)
    assert leaked is None


@pytest.mark.asyncio
async def test_get_returns_none_when_absent(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-empty")
    result = await ChartArrestService.get(session, tenant_id="t-1", chart_id=chart.id)
    assert result is None


@pytest.mark.asyncio
async def test_upsert_requires_tenant_and_chart(session: AsyncSession) -> None:
    with pytest.raises(ChartArrestError):
        await ChartArrestService.upsert(
            session,
            tenant_id="",
            chart_id="x",
            payload=ChartArrestPayload(cardiac_arrest_code="9512001"),
            user_id=None,
        )
    with pytest.raises(ChartArrestError):
        await ChartArrestService.upsert(
            session,
            tenant_id="t",
            chart_id="",
            payload=ChartArrestPayload(cardiac_arrest_code="9512001"),
            user_id=None,
        )
