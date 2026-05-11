"""Projection tests: :class:`ChartScene` + :class:`ChartSceneOtherAgency`
-> NemsisFieldValue ledger.

Verifies that populated scene columns and other-agency rows produce one
ledger row each with the canonical element_number / element_name, that
None columns are NOT projected (preserving NEMSIS absence semantics),
that the lat/long pair lands under the eScene.SceneGPSGroup group_path
with distinct occurrence_ids, and that agency rows share their UUID as
occurrence_id so the dataset XML builder can fold them back into one
repeating-group occurrence each.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart
from epcr_app.models_chart_scene import (  # noqa: F401
    ChartScene,
    ChartSceneOtherAgency,
)
from epcr_app.models_nemsis_field_values import NemsisFieldValue
from epcr_app.projection_chart_scene import (
    SCENE_GPS_GROUP_PATH,
    SECTION,
    _AGENCY_ELEMENT_BINDING,
    _SCENE_ELEMENT_BINDING,
    project_chart_scene,
)
from epcr_app.services_chart_scene import (
    ChartSceneOtherAgencyPayload,
    ChartSceneOtherAgencyService,
    ChartScenePayload,
    ChartSceneService,
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
async def test_projection_emits_one_row_per_populated_scalar(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-1", "C-1")
    arrived = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
    await ChartSceneService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartScenePayload(
            first_ems_unit_indicator_code="Yes",
            initial_responder_arrived_at=arrived,
            number_of_patients=1,
            mci_indicator_code="No",
            incident_location_type_code="2204001",
            incident_street_address="123 Elm",
            incident_city="Boise",
            incident_state="ID",
            incident_zip="83702",
        ),
        user_id="u",
    )

    rows = await project_chart_scene(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    by_element_occ = {(r["element_number"], r["occurrence_id"]): r for r in rows}
    # 9 explicitly set + eScene.22 (country defaulted to "US") = 10 rows.
    assert len(rows) == 10
    expected_elements = {
        "eScene.01",
        "eScene.05",
        "eScene.06",
        "eScene.07",
        "eScene.09",
        "eScene.15",
        "eScene.17",
        "eScene.18",
        "eScene.19",
        "eScene.22",
    }
    assert {key[0] for key in by_element_occ.keys()} == expected_elements
    for row in rows:
        assert row["section"] == SECTION
        assert row["value"] is not None
        # Non-GPS scalar bindings land at group_path="".
        assert row["group_path"] == ""


@pytest.mark.asyncio
async def test_projection_emits_gps_group_for_lat_long(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-1", "C-gps")
    await ChartSceneService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartScenePayload(scene_lat=43.61, scene_long=-116.20),
        user_id="u",
    )
    rows = await project_chart_scene(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    gps = [r for r in rows if r["element_number"] == "eScene.11"]
    # eScene.22 defaulted to "US" so an extra non-GPS row is present too.
    assert len(gps) == 2
    occurrences = {r["occurrence_id"] for r in gps}
    assert occurrences == {"lat", "long"}
    for r in gps:
        assert r["group_path"] == SCENE_GPS_GROUP_PATH


@pytest.mark.asyncio
async def test_projection_skips_none_columns(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-2")
    await ChartSceneService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartScenePayload(incident_city="Boise"),
        user_id="u",
    )
    rows = await project_chart_scene(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    # incident_city set + incident_country defaulted to "US" => 2 rows.
    assert len(rows) == 2
    elements = {r["element_number"] for r in rows}
    assert elements == {"eScene.17", "eScene.22"}


@pytest.mark.asyncio
async def test_projection_emits_agency_rows_with_shared_occurrence_id(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-1", "C-OA")
    agency = await ChartSceneOtherAgencyService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartSceneOtherAgencyPayload(
            agency_id="AG-1",
            other_service_type_code="2208001",
            first_to_provide_patient_care_indicator="Yes",
            patient_care_handoff_code="2210003",
            sequence_index=0,
        ),
        user_id="u",
    )

    rows = await project_chart_scene(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    agency_rows = [r for r in rows if r["occurrence_id"] == agency["id"]]
    assert len(agency_rows) == 4
    assert {r["element_number"] for r in agency_rows} == {
        "eScene.03",
        "eScene.04",
        "eScene.24",
        "eScene.25",
    }
    for r in agency_rows:
        assert r["sequence_index"] == 0
        assert r["section"] == SECTION


@pytest.mark.asyncio
async def test_projection_is_idempotent_upserting_same_element(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-1", "C-3")
    await ChartSceneService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartScenePayload(incident_state="ID"),
        user_id="u",
    )
    rows1 = await project_chart_scene(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    rows2 = await project_chart_scene(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    # eScene.18 + eScene.22 defaulted to "US" => 2 rows each pass.
    assert len(rows1) == len(rows2) == 2
    ledger = (
        await session.execute(
            select(NemsisFieldValue).where(
                NemsisFieldValue.chart_id == chart.id,
                NemsisFieldValue.section == SECTION,
            )
        )
    ).scalars().all()
    assert len(ledger) == 2


@pytest.mark.asyncio
async def test_projection_returns_empty_when_no_row(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-empty")
    rows = await project_chart_scene(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert rows == []


@pytest.mark.asyncio
async def test_projection_binding_covers_every_column() -> None:
    """The binding tables must cover every NEMSIS-bound model column."""
    from epcr_app.services_chart_scene import _AGENCY_FIELDS, _SCENE_FIELDS

    scene_binding_cols = {col for col, _e, _n, _g, _o in _SCENE_ELEMENT_BINDING}
    assert scene_binding_cols == set(_SCENE_FIELDS), (
        f"scene binding drift: missing={set(_SCENE_FIELDS) - scene_binding_cols}, "
        f"extra={scene_binding_cols - set(_SCENE_FIELDS)}"
    )
    agency_binding_cols = {col for col, _e, _n in _AGENCY_ELEMENT_BINDING}
    assert agency_binding_cols == set(_AGENCY_FIELDS), (
        f"agency binding drift: missing={set(_AGENCY_FIELDS) - agency_binding_cols}, "
        f"extra={agency_binding_cols - set(_AGENCY_FIELDS)}"
    )


@pytest.mark.asyncio
async def test_projection_element_names_match_dictionary() -> None:
    """The NEMSIS element names must match the v3.5.1 data dictionary."""
    scene_names = {elem: name for _c, elem, name, _g, _o in _SCENE_ELEMENT_BINDING}
    assert scene_names["eScene.01"] == "First EMS Unit on Scene"
    assert scene_names["eScene.06"] == "Number of Patients at Scene"
    assert scene_names["eScene.09"] == "Incident Location Type"
    assert scene_names["eScene.15"] == "Incident Street Address"
    assert scene_names["eScene.23"] == "Incident Census Tract"

    agency_names = {elem: name for _c, elem, name in _AGENCY_ELEMENT_BINDING}
    assert (
        agency_names["eScene.03"]
        == "Other EMS or Public Safety Agency ID Number"
    )
    assert agency_names["eScene.04"] == "Type of Other Service at Scene"
    assert agency_names["eScene.24"] == (
        "First Other EMS or Public Safety Agency at Scene to Provide Patient Care"
    )
    assert (
        agency_names["eScene.25"]
        == "Transferred Patient/Care To/From Agency"
    )
