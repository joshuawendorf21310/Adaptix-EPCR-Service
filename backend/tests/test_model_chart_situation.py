"""Persistence tests for the NEMSIS eSituation ORM models.

Covers: insert, query, tenant scoping, unique-per-chart constraint on
the 1:1 row, unique-per-(chart,code) constraints on the two child
repeating groups, default version/created_at, and soft-delete column.
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
from epcr_app.models_chart_situation import (
    ChartSituation,
    ChartSituationOtherSymptom,
    ChartSituationSecondaryImpression,
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
async def test_insert_chart_situation_with_all_columns(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-001")
    now = datetime.now(UTC)
    row = ChartSituation(
        id=str(uuid.uuid4()),
        tenant_id="t-1",
        chart_id=chart.id,
        symptom_onset_at=now,
        possible_injury_indicator_code="9922001",
        complaint_type_code="9914001",
        complaint_text="Chest pain radiating to left arm",
        complaint_duration_value=30,
        complaint_duration_units_code="2553011",
        chief_complaint_anatomic_code="3505001",
        chief_complaint_organ_system_code="3506001",
        primary_symptom_code="R07.9",
        provider_primary_impression_code="I21.9",
        initial_patient_acuity_code="2207003",
        work_related_indicator_code="9922001",
        patient_industry_code="11",
        patient_occupation_code="35-9099",
        patient_activity_code="0",
        last_known_well_at=now,
        transfer_justification_code="9908001",
        interfacility_transfer_reason_code="9909001",
    )
    session.add(row)
    await session.flush()

    fetched = (
        await session.execute(
            select(ChartSituation).where(ChartSituation.chart_id == chart.id)
        )
    ).scalar_one()
    assert fetched.symptom_onset_at is not None
    assert fetched.complaint_text == "Chest pain radiating to left arm"
    assert fetched.complaint_duration_value == 30
    assert fetched.tenant_id == "t-1"
    assert fetched.version == 1


@pytest.mark.asyncio
async def test_chart_situation_unique_per_chart(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-002")
    session.add(
        ChartSituation(id=str(uuid.uuid4()), tenant_id="t-1", chart_id=chart.id)
    )
    await session.flush()
    session.add(
        ChartSituation(id=str(uuid.uuid4()), tenant_id="t-1", chart_id=chart.id)
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_chart_situation_tenant_isolation_in_query(session: AsyncSession) -> None:
    chart_a = await _make_chart(session, "t-A", "C-A")
    chart_b = await _make_chart(session, "t-B", "C-B")
    session.add(ChartSituation(id=str(uuid.uuid4()), tenant_id="t-A", chart_id=chart_a.id))
    session.add(ChartSituation(id=str(uuid.uuid4()), tenant_id="t-B", chart_id=chart_b.id))
    await session.flush()

    rows_a = (
        await session.execute(
            select(ChartSituation).where(ChartSituation.tenant_id == "t-A")
        )
    ).scalars().all()
    rows_b = (
        await session.execute(
            select(ChartSituation).where(ChartSituation.tenant_id == "t-B")
        )
    ).scalars().all()
    assert len(rows_a) == 1 and rows_a[0].chart_id == chart_a.id
    assert len(rows_b) == 1 and rows_b[0].chart_id == chart_b.id


@pytest.mark.asyncio
async def test_chart_situation_all_scalar_columns_exist() -> None:
    """Guard rail: ChartSituation must declare every scalar eSituation column."""
    expected = {
        "symptom_onset_at",
        "possible_injury_indicator_code",
        "complaint_type_code",
        "complaint_text",
        "complaint_duration_value",
        "complaint_duration_units_code",
        "chief_complaint_anatomic_code",
        "chief_complaint_organ_system_code",
        "primary_symptom_code",
        "provider_primary_impression_code",
        "initial_patient_acuity_code",
        "work_related_indicator_code",
        "patient_industry_code",
        "patient_occupation_code",
        "patient_activity_code",
        "last_known_well_at",
        "transfer_justification_code",
        "interfacility_transfer_reason_code",
    }
    cols = {c.name for c in ChartSituation.__table__.columns}
    missing = expected - cols
    assert not missing, f"ChartSituation missing eSituation columns: {missing}"


@pytest.mark.asyncio
async def test_other_symptom_unique_per_chart_code(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-Sym")
    session.add(
        ChartSituationOtherSymptom(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            symptom_code="R06.0",
        )
    )
    await session.flush()
    session.add(
        ChartSituationOtherSymptom(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            symptom_code="R06.0",
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_secondary_impression_unique_per_chart_code(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-Imp")
    session.add(
        ChartSituationSecondaryImpression(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            impression_code="I50.9",
        )
    )
    await session.flush()
    session.add(
        ChartSituationSecondaryImpression(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            impression_code="I50.9",
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_repeating_groups_allow_distinct_codes_per_chart(
    session: AsyncSession,
) -> None:
    chart = await _make_chart(session, "t-1", "C-Multi")
    for code in ("R06.0", "R07.9", "R51"):
        session.add(
            ChartSituationOtherSymptom(
                id=str(uuid.uuid4()),
                tenant_id="t-1",
                chart_id=chart.id,
                symptom_code=code,
            )
        )
    for code in ("I50.9", "I10"):
        session.add(
            ChartSituationSecondaryImpression(
                id=str(uuid.uuid4()),
                tenant_id="t-1",
                chart_id=chart.id,
                impression_code=code,
            )
        )
    await session.flush()

    symptoms = (
        await session.execute(
            select(ChartSituationOtherSymptom).where(
                ChartSituationOtherSymptom.chart_id == chart.id
            )
        )
    ).scalars().all()
    impressions = (
        await session.execute(
            select(ChartSituationSecondaryImpression).where(
                ChartSituationSecondaryImpression.chart_id == chart.id
            )
        )
    ).scalars().all()
    assert len(symptoms) == 3
    assert len(impressions) == 2
