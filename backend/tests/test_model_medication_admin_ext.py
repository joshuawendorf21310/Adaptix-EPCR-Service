"""Persistence tests for the NEMSIS eMedications-additions models.

Covers: insert, query, tenant scoping, unique-per-medication
constraint on the 1:1 extension, unique-per-(med, code) constraint
on the 1:M complications, default version/created_at, and column
presence guard rails for every NEMSIS-additive element.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart, MedicationAdministration
from epcr_app.models_medication_admin_ext import (
    MedicationAdminExt,
    MedicationComplication,
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


async def _make_med(
    session: AsyncSession,
    *,
    tenant_id: str,
    chart_id: str,
    name: str = "Epinephrine",
) -> MedicationAdministration:
    med = MedicationAdministration(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        chart_id=chart_id,
        medication_name=name,
        route="IV",
        indication="Cardiac arrest",
        administered_at=datetime.now(UTC),
        administered_by_user_id="user-1",
    )
    session.add(med)
    await session.flush()
    return med


@pytest.mark.asyncio
async def test_insert_medication_admin_ext_with_all_columns(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-001")
    med = await _make_med(session, tenant_id="t-1", chart_id=chart.id)
    row = MedicationAdminExt(
        id=str(uuid.uuid4()),
        tenant_id="t-1",
        chart_id=chart.id,
        medication_admin_id=med.id,
        prior_to_ems_indicator_code="9923001",
        ems_professional_type_code="9924007",
        authorization_code="9908001",
        authorizing_physician_last_name="Strange",
        authorizing_physician_first_name="Stephen",
        by_another_unit_indicator_code="9923001",
    )
    session.add(row)
    await session.flush()

    fetched = (
        await session.execute(
            select(MedicationAdminExt).where(MedicationAdminExt.medication_admin_id == med.id)
        )
    ).scalar_one()
    assert fetched.prior_to_ems_indicator_code == "9923001"
    assert fetched.ems_professional_type_code == "9924007"
    assert fetched.authorization_code == "9908001"
    assert fetched.authorizing_physician_last_name == "Strange"
    assert fetched.authorizing_physician_first_name == "Stephen"
    assert fetched.by_another_unit_indicator_code == "9923001"
    assert fetched.tenant_id == "t-1"
    assert fetched.version == 1


@pytest.mark.asyncio
async def test_medication_admin_ext_unique_per_med(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-002")
    med = await _make_med(session, tenant_id="t-1", chart_id=chart.id)
    session.add(
        MedicationAdminExt(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            medication_admin_id=med.id,
        )
    )
    await session.flush()
    session.add(
        MedicationAdminExt(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            medication_admin_id=med.id,
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_medication_complications_unique_per_code(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-003")
    med = await _make_med(session, tenant_id="t-1", chart_id=chart.id)
    session.add(
        MedicationComplication(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            medication_admin_id=med.id,
            complication_code="9925003",
            sequence_index=0,
        )
    )
    await session.flush()
    session.add(
        MedicationComplication(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            medication_admin_id=med.id,
            complication_code="9925003",
            sequence_index=1,
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_medication_complications_allow_multiple_codes(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-004")
    med = await _make_med(session, tenant_id="t-1", chart_id=chart.id)
    for idx, code in enumerate(["9925003", "9925005", "9925007"]):
        session.add(
            MedicationComplication(
                id=str(uuid.uuid4()),
                tenant_id="t-1",
                chart_id=chart.id,
                medication_admin_id=med.id,
                complication_code=code,
                sequence_index=idx,
            )
        )
    await session.flush()
    rows = (
        await session.execute(
            select(MedicationComplication).where(
                MedicationComplication.medication_admin_id == med.id
            )
        )
    ).scalars().all()
    assert {r.complication_code for r in rows} == {"9925003", "9925005", "9925007"}


@pytest.mark.asyncio
async def test_tenant_isolation_in_query(session: AsyncSession) -> None:
    chart_a = await _make_chart(session, "t-A", "C-A")
    chart_b = await _make_chart(session, "t-B", "C-B")
    med_a = await _make_med(session, tenant_id="t-A", chart_id=chart_a.id)
    med_b = await _make_med(session, tenant_id="t-B", chart_id=chart_b.id)
    session.add(
        MedicationAdminExt(
            id=str(uuid.uuid4()),
            tenant_id="t-A",
            chart_id=chart_a.id,
            medication_admin_id=med_a.id,
            ems_professional_type_code="9924007",
        )
    )
    session.add(
        MedicationAdminExt(
            id=str(uuid.uuid4()),
            tenant_id="t-B",
            chart_id=chart_b.id,
            medication_admin_id=med_b.id,
            ems_professional_type_code="9924009",
        )
    )
    await session.flush()

    rows_a = (
        await session.execute(
            select(MedicationAdminExt).where(MedicationAdminExt.tenant_id == "t-A")
        )
    ).scalars().all()
    rows_b = (
        await session.execute(
            select(MedicationAdminExt).where(MedicationAdminExt.tenant_id == "t-B")
        )
    ).scalars().all()
    assert len(rows_a) == 1 and rows_a[0].medication_admin_id == med_a.id
    assert len(rows_b) == 1 and rows_b[0].medication_admin_id == med_b.id


@pytest.mark.asyncio
async def test_ext_declares_every_nemsis_additive_column() -> None:
    """Guard rail: MedicationAdminExt must declare every NEMSIS-additive column."""
    expected = {
        "prior_to_ems_indicator_code",
        "ems_professional_type_code",
        "authorization_code",
        "authorizing_physician_last_name",
        "authorizing_physician_first_name",
        "by_another_unit_indicator_code",
    }
    cols = {c.name for c in MedicationAdminExt.__table__.columns}
    missing = expected - cols
    assert not missing, f"MedicationAdminExt missing eMedications columns: {missing}"


@pytest.mark.asyncio
async def test_complication_declares_required_columns() -> None:
    cols = {c.name for c in MedicationComplication.__table__.columns}
    assert {
        "complication_code",
        "sequence_index",
        "medication_admin_id",
        "tenant_id",
        "chart_id",
    } <= cols
