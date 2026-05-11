"""Persistence tests for the NEMSIS eDisposition (:class:`ChartDisposition`) model.

Covers: insert, query, tenant scoping, unique-per-chart constraint,
default version/created_at, soft delete column, and JSON list columns.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart
from epcr_app.models_chart_disposition import ChartDisposition


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
async def test_insert_chart_disposition_with_scalar_and_list_columns(
    session: AsyncSession,
) -> None:
    chart = await _make_chart(session, "t-1", "C-001")
    row = ChartDisposition(
        id=str(uuid.uuid4()),
        tenant_id="t-1",
        chart_id=chart.id,
        destination_name="St. Example Hospital",
        destination_code="HOSP-001",
        destination_city="Springfield",
        destination_state="IL",
        destination_zip="62701",
        incident_patient_disposition_code="4212001",
        transport_disposition_code="4227005",
        level_of_care_provided_code="4218015",
        hospital_capability_codes_json=["4209007", "4209013"],
        crew_disposition_codes_json=["4234007"],
    )
    session.add(row)
    await session.flush()

    fetched = (
        await session.execute(
            select(ChartDisposition).where(ChartDisposition.chart_id == chart.id)
        )
    ).scalar_one()
    assert fetched.destination_name == "St. Example Hospital"
    assert fetched.incident_patient_disposition_code == "4212001"
    assert fetched.hospital_capability_codes_json == ["4209007", "4209013"]
    assert fetched.crew_disposition_codes_json == ["4234007"]
    assert fetched.tenant_id == "t-1"
    assert fetched.version == 1


@pytest.mark.asyncio
async def test_chart_disposition_unique_per_chart(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-002")
    session.add(
        ChartDisposition(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
        )
    )
    await session.flush()
    session.add(
        ChartDisposition(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_chart_disposition_tenant_isolation_in_query(
    session: AsyncSession,
) -> None:
    chart_a = await _make_chart(session, "t-A", "C-A")
    chart_b = await _make_chart(session, "t-B", "C-B")
    session.add(
        ChartDisposition(id=str(uuid.uuid4()), tenant_id="t-A", chart_id=chart_a.id)
    )
    session.add(
        ChartDisposition(id=str(uuid.uuid4()), tenant_id="t-B", chart_id=chart_b.id)
    )
    await session.flush()

    rows_a = (
        await session.execute(
            select(ChartDisposition).where(ChartDisposition.tenant_id == "t-A")
        )
    ).scalars().all()
    rows_b = (
        await session.execute(
            select(ChartDisposition).where(ChartDisposition.tenant_id == "t-B")
        )
    ).scalars().all()
    assert len(rows_a) == 1 and rows_a[0].chart_id == chart_a.id
    assert len(rows_b) == 1 and rows_b[0].chart_id == chart_b.id


@pytest.mark.asyncio
async def test_chart_disposition_all_expected_columns_exist() -> None:
    """Guard rail: ChartDisposition must declare every eDisposition column
    (excluding eDisposition.26 which is undefined in v3.5.1)."""
    expected = {
        # eDisposition.01..08
        "destination_name",
        "destination_code",
        "destination_address",
        "destination_city",
        "destination_county",
        "destination_state",
        "destination_zip",
        "destination_country",
        # eDisposition.09..10 (1:M)
        "hospital_capability_codes_json",
        "reason_for_choosing_destination_codes_json",
        # eDisposition.11..12
        "type_of_destination_code",
        "incident_patient_disposition_code",
        # eDisposition.13..14
        "transport_mode_from_scene_code",
        "additional_transport_descriptors_codes_json",
        # eDisposition.15 (1:M)
        "hospital_incapability_codes_json",
        # eDisposition.16..18
        "transport_disposition_code",
        "reason_not_transported_code",
        "level_of_care_provided_code",
        # eDisposition.19..21
        "position_during_transport_code",
        "condition_at_destination_code",
        "transferred_care_to_code",
        # eDisposition.22..24 (1:M)
        "prearrival_activation_codes_json",
        "type_of_destination_reason_codes_json",
        "destination_team_activations_codes_json",
        # eDisposition.25
        "destination_type_when_reason_code",
        # eDisposition.27..30
        "crew_disposition_codes_json",
        "unit_disposition_code",
        "transport_method_code",
        "transport_method_additional_codes_json",
    }
    cols = {c.name for c in ChartDisposition.__table__.columns}
    missing = expected - cols
    assert not missing, f"ChartDisposition missing eDisposition columns: {missing}"


@pytest.mark.asyncio
async def test_chart_disposition_minimal_row_defaults(session: AsyncSession) -> None:
    """Inserting only the required FK fields uses sensible defaults."""
    chart = await _make_chart(session, "t-1", "C-min")
    row = ChartDisposition(
        id=str(uuid.uuid4()),
        tenant_id="t-1",
        chart_id=chart.id,
    )
    session.add(row)
    await session.flush()

    fetched = (
        await session.execute(
            select(ChartDisposition).where(ChartDisposition.chart_id == chart.id)
        )
    ).scalar_one()
    assert fetched.version == 1
    assert fetched.deleted_at is None
    assert fetched.incident_patient_disposition_code is None
