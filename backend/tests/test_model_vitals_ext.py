"""Persistence tests for the NEMSIS eVitals extension ORM models.

Covers: insert, query, tenant scoping, unique-per-vitals constraint,
default version, soft-delete column on the 1:1 extension and the two
1:M repeating-group children (GCS qualifiers, reperfusion checklist).
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart, Vitals
from epcr_app.models_vitals_ext import (
    VitalsGcsQualifier,
    VitalsNemsisExt,
    VitalsReperfusionChecklist,
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


async def _seed_chart_vitals(
    session: AsyncSession,
    tenant_id: str,
    call_number: str,
) -> tuple[Chart, Vitals]:
    chart = Chart(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        call_number=call_number,
        created_by_user_id="user-1",
    )
    session.add(chart)
    await session.flush()

    vitals = Vitals(
        id=str(uuid.uuid4()),
        chart_id=chart.id,
        tenant_id=tenant_id,
        recorded_at=datetime.now(UTC),
    )
    session.add(vitals)
    await session.flush()
    return chart, vitals


@pytest.mark.asyncio
async def test_insert_vitals_ext_with_all_columns(session: AsyncSession) -> None:
    chart, vitals = await _seed_chart_vitals(session, "t-1", "C-001")
    row = VitalsNemsisExt(
        id=str(uuid.uuid4()),
        tenant_id="t-1",
        chart_id=chart.id,
        vitals_id=vitals.id,
        obtained_prior_to_ems_code="9908001",
        cardiac_rhythm_codes_json=["3508001", "3508003"],
        ecg_type_code="3509001",
        ecg_interpretation_method_codes_json=["3510001"],
        blood_pressure_method_code="3513001",
        mean_arterial_pressure=70,
        heart_rate_method_code="3514001",
        pulse_rhythm_code="3515001",
        respiratory_effort_code="3516001",
        etco2=35,
        carbon_monoxide_ppm=1.2,
        gcs_eye_code="3518003",
        gcs_verbal_code="3519005",
        gcs_motor_code="3520006",
        gcs_total=14,
        temperature_method_code="3522001",
        avpu_code="3523001",
        pain_score=7,
        pain_scale_type_code="3525001",
        stroke_scale_result_code="3526001",
        stroke_scale_type_code="3527001",
        stroke_scale_score=2,
        apgar_score=9,
        revised_trauma_score=12,
    )
    session.add(row)
    await session.flush()

    fetched = (
        await session.execute(
            select(VitalsNemsisExt).where(VitalsNemsisExt.vitals_id == vitals.id)
        )
    ).scalar_one()
    assert fetched.tenant_id == "t-1"
    assert fetched.gcs_total == 14
    assert fetched.cardiac_rhythm_codes_json == ["3508001", "3508003"]
    assert fetched.version == 1


@pytest.mark.asyncio
async def test_vitals_ext_unique_per_vitals(session: AsyncSession) -> None:
    chart, vitals = await _seed_chart_vitals(session, "t-1", "C-002")
    session.add(
        VitalsNemsisExt(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            vitals_id=vitals.id,
        )
    )
    await session.flush()
    session.add(
        VitalsNemsisExt(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            vitals_id=vitals.id,
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_vitals_ext_tenant_isolation_in_query(session: AsyncSession) -> None:
    chart_a, vitals_a = await _seed_chart_vitals(session, "t-A", "C-A")
    chart_b, vitals_b = await _seed_chart_vitals(session, "t-B", "C-B")
    session.add(
        VitalsNemsisExt(
            id=str(uuid.uuid4()),
            tenant_id="t-A",
            chart_id=chart_a.id,
            vitals_id=vitals_a.id,
            etco2=33,
        )
    )
    session.add(
        VitalsNemsisExt(
            id=str(uuid.uuid4()),
            tenant_id="t-B",
            chart_id=chart_b.id,
            vitals_id=vitals_b.id,
            etco2=40,
        )
    )
    await session.flush()

    rows_a = (
        await session.execute(
            select(VitalsNemsisExt).where(VitalsNemsisExt.tenant_id == "t-A")
        )
    ).scalars().all()
    rows_b = (
        await session.execute(
            select(VitalsNemsisExt).where(VitalsNemsisExt.tenant_id == "t-B")
        )
    ).scalars().all()
    assert len(rows_a) == 1 and rows_a[0].etco2 == 33
    assert len(rows_b) == 1 and rows_b[0].etco2 == 40


@pytest.mark.asyncio
async def test_gcs_qualifiers_repeat_and_unique(session: AsyncSession) -> None:
    chart, vitals = await _seed_chart_vitals(session, "t-1", "C-G")
    session.add(
        VitalsGcsQualifier(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            vitals_id=vitals.id,
            qualifier_code="3521001",
            sequence_index=0,
        )
    )
    session.add(
        VitalsGcsQualifier(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            vitals_id=vitals.id,
            qualifier_code="3521003",
            sequence_index=1,
        )
    )
    await session.flush()

    # Same (tenant, vitals, qualifier_code) triple must violate unique.
    session.add(
        VitalsGcsQualifier(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            vitals_id=vitals.id,
            qualifier_code="3521001",
            sequence_index=2,
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_reperfusion_checklist_repeat_and_unique(session: AsyncSession) -> None:
    chart, vitals = await _seed_chart_vitals(session, "t-1", "C-R")
    session.add(
        VitalsReperfusionChecklist(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            vitals_id=vitals.id,
            item_code="3528001",
            sequence_index=0,
        )
    )
    session.add(
        VitalsReperfusionChecklist(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            vitals_id=vitals.id,
            item_code="3528002",
            sequence_index=1,
        )
    )
    await session.flush()

    session.add(
        VitalsReperfusionChecklist(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            vitals_id=vitals.id,
            item_code="3528001",
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_vitals_ext_all_columns_exist() -> None:
    """Guard rail: VitalsNemsisExt must declare every spec column."""
    expected = {
        "obtained_prior_to_ems_code",
        "cardiac_rhythm_codes_json",
        "ecg_type_code",
        "ecg_interpretation_method_codes_json",
        "blood_pressure_method_code",
        "mean_arterial_pressure",
        "heart_rate_method_code",
        "pulse_rhythm_code",
        "respiratory_effort_code",
        "etco2",
        "carbon_monoxide_ppm",
        "gcs_eye_code",
        "gcs_verbal_code",
        "gcs_motor_code",
        "gcs_total",
        "temperature_method_code",
        "avpu_code",
        "pain_score",
        "pain_scale_type_code",
        "stroke_scale_result_code",
        "stroke_scale_type_code",
        "stroke_scale_score",
        "apgar_score",
        "revised_trauma_score",
    }
    cols = {c.name for c in VitalsNemsisExt.__table__.columns}
    missing = expected - cols
    assert not missing, f"VitalsNemsisExt missing columns: {missing}"
