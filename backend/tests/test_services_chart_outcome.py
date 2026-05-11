"""Service tests for :class:`ChartOutcomeService`.

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
from epcr_app.models_chart_outcome import ChartOutcome  # noqa: F401 - registers table
from epcr_app.services_chart_outcome import (
    ChartOutcomeError,
    ChartOutcomePayload,
    ChartOutcomeService,
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
    payload = ChartOutcomePayload(
        emergency_department_disposition_code="4209001",
        hospital_disposition_code="4210001",
        emergency_department_diagnosis_codes_json=["I21.4", "E11.9"],
        hospital_length_of_stay_days=5,
        emergency_department_arrival_at=t0,
        date_of_death=t0 + timedelta(days=1),
        medical_record_number="MRN-0001",
    )
    result = await ChartOutcomeService.upsert(
        session, tenant_id="t-1", chart_id=chart.id, payload=payload, user_id="user-1"
    )
    assert result["emergency_department_disposition_code"] == "4209001"
    assert result["chart_id"] == chart.id
    assert result["emergency_department_diagnosis_codes_json"] == ["I21.4", "E11.9"]
    assert result["hospital_length_of_stay_days"] == 5
    assert result["emergency_department_arrival_at"].startswith(
        "2026-05-10T12:00:00"
    )

    fetched = await ChartOutcomeService.get(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert fetched is not None
    assert fetched["medical_record_number"] == "MRN-0001"
    assert fetched["date_of_death"].startswith("2026-05-11T12:00:00")


@pytest.mark.asyncio
async def test_partial_update_preserves_existing(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-2")
    t0 = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)

    await ChartOutcomeService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartOutcomePayload(
            emergency_department_disposition_code="4209001",
            hospital_disposition_code="4210001",
            emergency_department_arrival_at=t0,
            cause_of_death_codes_json=["I46.9"],
        ),
        user_id="user-1",
    )
    # second upsert only sets new fields; existing values must remain
    await ChartOutcomeService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartOutcomePayload(
            referred_to_facility_name="St Mercy",
            icu_length_of_stay_days=2,
        ),
        user_id="user-2",
    )

    fetched = await ChartOutcomeService.get(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert fetched["emergency_department_disposition_code"] == "4209001"
    assert fetched["hospital_disposition_code"] == "4210001"
    assert fetched["cause_of_death_codes_json"] == ["I46.9"]
    assert fetched["referred_to_facility_name"] == "St Mercy"
    assert fetched["icu_length_of_stay_days"] == 2
    assert fetched["emergency_department_arrival_at"].startswith(
        "2026-05-10T12:00:00"
    )


@pytest.mark.asyncio
async def test_clear_field_sets_null(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-3")
    await ChartOutcomeService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartOutcomePayload(
            emergency_department_disposition_code="4209001",
            hospital_disposition_code="4210001",
        ),
        user_id="user-1",
    )
    cleared = await ChartOutcomeService.clear_field(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        field="emergency_department_disposition_code",
        user_id="user-1",
    )
    assert cleared["emergency_department_disposition_code"] is None
    assert cleared["hospital_disposition_code"] == "4210001"


@pytest.mark.asyncio
async def test_clear_field_can_clear_list(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-3b")
    await ChartOutcomeService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartOutcomePayload(
            emergency_department_diagnosis_codes_json=["I21.4", "E11.9"],
        ),
        user_id="user-1",
    )
    cleared = await ChartOutcomeService.clear_field(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        field="emergency_department_diagnosis_codes_json",
        user_id="user-1",
    )
    assert cleared["emergency_department_diagnosis_codes_json"] is None


@pytest.mark.asyncio
async def test_clear_field_unknown_raises(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-4")
    await ChartOutcomeService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartOutcomePayload(medical_record_number="MRN-1"),
        user_id="user-1",
    )
    with pytest.raises(ChartOutcomeError) as exc:
        await ChartOutcomeService.clear_field(
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
    await ChartOutcomeService.upsert(
        session,
        tenant_id="t-A",
        chart_id=chart.id,
        payload=ChartOutcomePayload(medical_record_number="MRN-A"),
        user_id="user-1",
    )
    leaked = await ChartOutcomeService.get(
        session, tenant_id="t-B", chart_id=chart.id
    )
    assert leaked is None


@pytest.mark.asyncio
async def test_get_returns_none_when_absent(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-empty")
    result = await ChartOutcomeService.get(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert result is None


@pytest.mark.asyncio
async def test_upsert_requires_tenant_and_chart(session: AsyncSession) -> None:
    with pytest.raises(ChartOutcomeError):
        await ChartOutcomeService.upsert(
            session,
            tenant_id="",
            chart_id="x",
            payload=ChartOutcomePayload(),
            user_id=None,
        )
    with pytest.raises(ChartOutcomeError):
        await ChartOutcomeService.upsert(
            session,
            tenant_id="t",
            chart_id="",
            payload=ChartOutcomePayload(),
            user_id=None,
        )
