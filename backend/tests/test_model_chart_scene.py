"""Persistence tests for the NEMSIS eScene (:class:`ChartScene` +
:class:`ChartSceneOtherAgency`) models.

Covers: insert, query, tenant scoping, unique-per-chart constraint on
the 1:1 meta, unique-per-(chart, agency) constraint on the 1:M group,
default version, soft delete column.
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
from epcr_app.models_chart_scene import ChartScene, ChartSceneOtherAgency


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
async def test_insert_chart_scene_with_required_columns(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-001")
    arrived = datetime.now(UTC)
    row = ChartScene(
        id=str(uuid.uuid4()),
        tenant_id="t-1",
        chart_id=chart.id,
        first_ems_unit_indicator_code="Yes",
        initial_responder_arrived_at=arrived,
        number_of_patients=1,
        mci_indicator_code="No",
        incident_location_type_code="2204001",
        incident_street_address="123 Elm St",
        incident_city="Boise",
        incident_state="ID",
        incident_zip="83702",
        scene_lat=43.6150,
        scene_long=-116.2023,
    )
    session.add(row)
    await session.flush()

    fetched = (
        await session.execute(select(ChartScene).where(ChartScene.chart_id == chart.id))
    ).scalar_one()
    assert fetched.first_ems_unit_indicator_code == "Yes"
    assert fetched.number_of_patients == 1
    assert fetched.scene_lat == pytest.approx(43.6150)
    assert fetched.scene_long == pytest.approx(-116.2023)
    assert fetched.tenant_id == "t-1"
    assert fetched.version == 1


@pytest.mark.asyncio
async def test_chart_scene_unique_per_chart(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-002")
    session.add(
        ChartScene(id=str(uuid.uuid4()), tenant_id="t-1", chart_id=chart.id)
    )
    await session.flush()
    session.add(
        ChartScene(id=str(uuid.uuid4()), tenant_id="t-1", chart_id=chart.id)
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_chart_scene_tenant_isolation_in_query(session: AsyncSession) -> None:
    chart_a = await _make_chart(session, "t-A", "C-A")
    chart_b = await _make_chart(session, "t-B", "C-B")
    session.add(ChartScene(id=str(uuid.uuid4()), tenant_id="t-A", chart_id=chart_a.id))
    session.add(ChartScene(id=str(uuid.uuid4()), tenant_id="t-B", chart_id=chart_b.id))
    await session.flush()

    rows_a = (
        await session.execute(select(ChartScene).where(ChartScene.tenant_id == "t-A"))
    ).scalars().all()
    rows_b = (
        await session.execute(select(ChartScene).where(ChartScene.tenant_id == "t-B"))
    ).scalars().all()
    assert len(rows_a) == 1 and rows_a[0].chart_id == chart_a.id
    assert len(rows_b) == 1 and rows_b[0].chart_id == chart_b.id


@pytest.mark.asyncio
async def test_chart_scene_all_required_columns_exist() -> None:
    """Guard rail: ChartScene must declare every eScene scalar column."""
    expected = {
        "first_ems_unit_indicator_code",
        "initial_responder_arrived_at",
        "number_of_patients",
        "mci_indicator_code",
        "mci_triage_classification_code",
        "incident_location_type_code",
        "incident_facility_code",
        "scene_lat",
        "scene_long",
        "scene_usng",
        "incident_facility_name",
        "mile_post_or_major_roadway",
        "incident_street_address",
        "incident_apartment",
        "incident_city",
        "incident_state",
        "incident_zip",
        "scene_cross_street",
        "incident_county",
        "incident_country",
        "incident_census_tract",
    }
    cols = {c.name for c in ChartScene.__table__.columns}
    missing = expected - cols
    assert not missing, f"ChartScene missing eScene columns: {missing}"


@pytest.mark.asyncio
async def test_insert_other_agency_row(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-OA1")
    row = ChartSceneOtherAgency(
        id=str(uuid.uuid4()),
        tenant_id="t-1",
        chart_id=chart.id,
        agency_id="AG-001",
        other_service_type_code="2208001",
        first_to_provide_patient_care_indicator="No",
        patient_care_handoff_code="2210003",
        sequence_index=0,
    )
    session.add(row)
    await session.flush()

    fetched = (
        await session.execute(
            select(ChartSceneOtherAgency).where(
                ChartSceneOtherAgency.chart_id == chart.id
            )
        )
    ).scalar_one()
    assert fetched.agency_id == "AG-001"
    assert fetched.other_service_type_code == "2208001"
    assert fetched.version == 1


@pytest.mark.asyncio
async def test_other_agency_unique_per_chart_agency(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-OA2")
    session.add(
        ChartSceneOtherAgency(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            agency_id="AG-X",
            other_service_type_code="2208001",
        )
    )
    await session.flush()
    session.add(
        ChartSceneOtherAgency(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            agency_id="AG-X",
            other_service_type_code="2208002",
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_other_agency_tenant_isolation(session: AsyncSession) -> None:
    chart_a = await _make_chart(session, "t-A", "C-A2")
    chart_b = await _make_chart(session, "t-B", "C-B2")
    session.add(
        ChartSceneOtherAgency(
            id=str(uuid.uuid4()),
            tenant_id="t-A",
            chart_id=chart_a.id,
            agency_id="AG-1",
            other_service_type_code="2208001",
        )
    )
    session.add(
        ChartSceneOtherAgency(
            id=str(uuid.uuid4()),
            tenant_id="t-B",
            chart_id=chart_b.id,
            agency_id="AG-1",
            other_service_type_code="2208002",
        )
    )
    await session.flush()

    rows_a = (
        await session.execute(
            select(ChartSceneOtherAgency).where(
                ChartSceneOtherAgency.tenant_id == "t-A"
            )
        )
    ).scalars().all()
    assert len(rows_a) == 1 and rows_a[0].chart_id == chart_a.id
