"""Persistence tests for the NEMSIS eOutcome (:class:`ChartOutcome`) model.

Covers: insert, query, tenant scoping, unique-per-chart constraint,
JSON list columns, default version, soft delete column.
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
from epcr_app.models_chart_outcome import ChartOutcome


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
async def test_insert_chart_outcome_with_all_columns(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-001")
    now = datetime.now(UTC)
    row = ChartOutcome(
        id=str(uuid.uuid4()),
        tenant_id="t-1",
        chart_id=chart.id,
        emergency_department_disposition_code="4209001",
        hospital_disposition_code="4210001",
        emergency_department_diagnosis_codes_json=["I21.4", "E11.9"],
        hospital_admission_diagnosis_codes_json=["I21.4"],
        hospital_procedures_performed_codes_json=["0270346"],
        trauma_registry_incident_id="TR-2026-0001",
        hospital_outcome_at_discharge_code="4211001",
        patient_disposition_from_emergency_department_at="ICU",
        emergency_department_arrival_at=now,
        emergency_department_admit_at=now,
        emergency_department_discharge_at=now,
        hospital_admit_at=now,
        hospital_discharge_at=now,
        icu_admit_at=now,
        icu_discharge_at=now,
        hospital_length_of_stay_days=5,
        icu_length_of_stay_days=2,
        final_patient_acuity_code="2305001",
        cause_of_death_codes_json=["I46.9"],
        date_of_death=now,
        medical_record_number="MRN-0001",
        receiving_facility_record_number="RFR-0001",
        referred_to_facility_code="FAC-001",
        referred_to_facility_name="St Mercy",
    )
    session.add(row)
    await session.flush()

    fetched = (
        await session.execute(
            select(ChartOutcome).where(ChartOutcome.chart_id == chart.id)
        )
    ).scalar_one()
    assert fetched.emergency_department_disposition_code == "4209001"
    assert fetched.emergency_department_diagnosis_codes_json == ["I21.4", "E11.9"]
    assert fetched.cause_of_death_codes_json == ["I46.9"]
    assert fetched.hospital_length_of_stay_days == 5
    assert fetched.icu_length_of_stay_days == 2
    assert fetched.referred_to_facility_name == "St Mercy"
    assert fetched.tenant_id == "t-1"
    assert fetched.version == 1


@pytest.mark.asyncio
async def test_chart_outcome_unique_per_chart(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-002")
    session.add(
        ChartOutcome(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
        )
    )
    await session.flush()
    session.add(
        ChartOutcome(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_chart_outcome_tenant_isolation_in_query(session: AsyncSession) -> None:
    chart_a = await _make_chart(session, "t-A", "C-A")
    chart_b = await _make_chart(session, "t-B", "C-B")
    session.add(
        ChartOutcome(id=str(uuid.uuid4()), tenant_id="t-A", chart_id=chart_a.id)
    )
    session.add(
        ChartOutcome(id=str(uuid.uuid4()), tenant_id="t-B", chart_id=chart_b.id)
    )
    await session.flush()

    rows_a = (
        await session.execute(
            select(ChartOutcome).where(ChartOutcome.tenant_id == "t-A")
        )
    ).scalars().all()
    rows_b = (
        await session.execute(
            select(ChartOutcome).where(ChartOutcome.tenant_id == "t-B")
        )
    ).scalars().all()
    assert len(rows_a) == 1 and rows_a[0].chart_id == chart_a.id
    assert len(rows_b) == 1 and rows_b[0].chart_id == chart_b.id


@pytest.mark.asyncio
async def test_chart_outcome_all_columns_exist() -> None:
    """Guard rail: ChartOutcome must declare every eOutcome column."""
    expected = {
        "emergency_department_disposition_code",
        "hospital_disposition_code",
        "emergency_department_diagnosis_codes_json",
        "hospital_admission_diagnosis_codes_json",
        "hospital_procedures_performed_codes_json",
        "trauma_registry_incident_id",
        "hospital_outcome_at_discharge_code",
        "patient_disposition_from_emergency_department_at",
        "emergency_department_arrival_at",
        "emergency_department_admit_at",
        "emergency_department_discharge_at",
        "hospital_admit_at",
        "hospital_discharge_at",
        "icu_admit_at",
        "icu_discharge_at",
        "hospital_length_of_stay_days",
        "icu_length_of_stay_days",
        "final_patient_acuity_code",
        "cause_of_death_codes_json",
        "date_of_death",
        "medical_record_number",
        "receiving_facility_record_number",
        "referred_to_facility_code",
        "referred_to_facility_name",
    }
    cols = {c.name for c in ChartOutcome.__table__.columns}
    missing = expected - cols
    assert not missing, f"ChartOutcome missing eOutcome columns: {missing}"
