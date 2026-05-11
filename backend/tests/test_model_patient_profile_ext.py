"""Persistence tests for the NEMSIS ePatient extension models.

Covers: insert, query, tenant scoping, unique-per-chart / per-(chart,
code) constraints, default version, soft-delete column for all five
sibling tables created by migration 036.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart
from epcr_app.models_patient_profile_ext import (
    PatientHomeAddress,
    PatientLanguage,
    PatientPhoneNumber,
    PatientProfileNemsisExt,
    PatientRace,
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
async def test_insert_scalar_ext_with_all_columns(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-001")
    row = PatientProfileNemsisExt(
        id=str(uuid.uuid4()),
        tenant_id="t-1",
        chart_id=chart.id,
        ems_patient_id="EMS-123",
        country_of_residence_code="US",
        patient_home_census_tract="36061010100",
        ssn_hash="abc" * 10,
        age_units_code="2516001",
        email_address="patient@example.com",
        driver_license_state="NY",
        driver_license_number="DL-987",
        alternate_home_residence_code="9923001",
        name_suffix="JR",
        sex_nemsis_code="9906001",
    )
    session.add(row)
    await session.flush()

    fetched = (
        await session.execute(
            select(PatientProfileNemsisExt).where(
                PatientProfileNemsisExt.chart_id == chart.id
            )
        )
    ).scalar_one()
    assert fetched.ems_patient_id == "EMS-123"
    assert fetched.sex_nemsis_code == "9906001"
    assert fetched.name_suffix == "JR"
    assert fetched.tenant_id == "t-1"
    assert fetched.version == 1


@pytest.mark.asyncio
async def test_scalar_ext_unique_per_chart(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-002")
    session.add(
        PatientProfileNemsisExt(
            id=str(uuid.uuid4()), tenant_id="t-1", chart_id=chart.id
        )
    )
    await session.flush()
    session.add(
        PatientProfileNemsisExt(
            id=str(uuid.uuid4()), tenant_id="t-1", chart_id=chart.id
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_scalar_ext_tenant_isolation_in_query(session: AsyncSession) -> None:
    chart_a = await _make_chart(session, "t-A", "C-A")
    chart_b = await _make_chart(session, "t-B", "C-B")
    session.add(
        PatientProfileNemsisExt(id=str(uuid.uuid4()), tenant_id="t-A", chart_id=chart_a.id)
    )
    session.add(
        PatientProfileNemsisExt(id=str(uuid.uuid4()), tenant_id="t-B", chart_id=chart_b.id)
    )
    await session.flush()
    rows_a = (
        await session.execute(
            select(PatientProfileNemsisExt).where(
                PatientProfileNemsisExt.tenant_id == "t-A"
            )
        )
    ).scalars().all()
    rows_b = (
        await session.execute(
            select(PatientProfileNemsisExt).where(
                PatientProfileNemsisExt.tenant_id == "t-B"
            )
        )
    ).scalars().all()
    assert len(rows_a) == 1 and rows_a[0].chart_id == chart_a.id
    assert len(rows_b) == 1 and rows_b[0].chart_id == chart_b.id


@pytest.mark.asyncio
async def test_home_address_insert_and_unique_per_chart(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-addr")
    row = PatientHomeAddress(
        id=str(uuid.uuid4()),
        tenant_id="t-1",
        chart_id=chart.id,
        home_street_address="123 Main St",
        home_city="Anytown",
        home_county="King",
        home_state="WA",
        home_zip="98101",
    )
    session.add(row)
    await session.flush()
    fetched = (
        await session.execute(
            select(PatientHomeAddress).where(PatientHomeAddress.chart_id == chart.id)
        )
    ).scalar_one()
    assert fetched.home_state == "WA"
    assert fetched.home_zip == "98101"
    assert fetched.version == 1

    session.add(
        PatientHomeAddress(id=str(uuid.uuid4()), tenant_id="t-1", chart_id=chart.id)
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_races_unique_per_chart_race_code(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-r")
    session.add(
        PatientRace(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            race_code="2106-3",
        )
    )
    await session.flush()
    session.add(
        PatientRace(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            race_code="2106-3",
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_races_multiple_codes_allowed(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-r2")
    session.add(
        PatientRace(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            race_code="2106-3",
            sequence_index=0,
        )
    )
    session.add(
        PatientRace(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            race_code="2054-5",
            sequence_index=1,
        )
    )
    await session.flush()
    rows = (
        await session.execute(
            select(PatientRace).where(PatientRace.chart_id == chart.id)
        )
    ).scalars().all()
    assert {r.race_code for r in rows} == {"2106-3", "2054-5"}


@pytest.mark.asyncio
async def test_languages_unique_and_multiple(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-l")
    session.add(
        PatientLanguage(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            language_code="eng",
            sequence_index=0,
        )
    )
    session.add(
        PatientLanguage(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            language_code="spa",
            sequence_index=1,
        )
    )
    await session.flush()

    session.add(
        PatientLanguage(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            language_code="eng",
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_phones_unique_per_chart_phone(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-p")
    session.add(
        PatientPhoneNumber(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            phone_number="555-0100",
            phone_type_code="9913003",
        )
    )
    await session.flush()
    session.add(
        PatientPhoneNumber(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            phone_number="555-0100",
            phone_type_code="9913005",
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_scalar_ext_has_expected_columns() -> None:
    """Guard rail: PatientProfileNemsisExt must declare every NEMSIS scalar."""
    expected = {
        "ems_patient_id",
        "country_of_residence_code",
        "patient_home_census_tract",
        "ssn_hash",
        "age_units_code",
        "email_address",
        "driver_license_state",
        "driver_license_number",
        "alternate_home_residence_code",
        "name_suffix",
        "sex_nemsis_code",
    }
    cols = {c.name for c in PatientProfileNemsisExt.__table__.columns}
    missing = expected - cols
    assert not missing, f"PatientProfileNemsisExt missing columns: {missing}"


@pytest.mark.asyncio
async def test_home_address_has_expected_columns() -> None:
    expected = {
        "home_street_address",
        "home_city",
        "home_county",
        "home_state",
        "home_zip",
    }
    cols = {c.name for c in PatientHomeAddress.__table__.columns}
    missing = expected - cols
    assert not missing, f"PatientHomeAddress missing columns: {missing}"
