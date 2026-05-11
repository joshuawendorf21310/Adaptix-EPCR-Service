"""Projection tests: eResponse models -> NemsisFieldValue ledger.

Verifies that populated scalar columns produce one ledger row per
eResponse.NN, that the vehicle-dispatch-location bundle is grouped
under the correct group_path, that the eResponse.24 list expands into
one row per descriptor, and that 1:M delay rows produce one ledger row
each with the right element_number / occurrence_id.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart
from epcr_app.models_chart_response import (  # noqa: F401
    ChartResponse,
    ChartResponseDelay,
)
from epcr_app.models_nemsis_field_values import NemsisFieldValue
from epcr_app.projection_chart_response import (
    SECTION,
    VEHICLE_DISPATCH_GROUP,
    _DELAY_ELEMENT_BINDING,
    _SCALAR_ELEMENT_BINDING,
    _VEHICLE_DISPATCH_BINDING,
    project_chart_response,
)
from epcr_app.services_chart_response import (
    ChartResponseDelayPayload,
    ChartResponsePayload,
    ChartResponseService,
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
async def test_projection_emits_scalar_rows_for_populated_columns(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-1", "C-1")
    await ChartResponseService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartResponsePayload(
            agency_number="A123",
            agency_name="Adaptix EMS",
            type_of_service_requested_code="2205001",
            unit_transport_capability_code="2208005",
            unit_vehicle_number="MEDIC-7",
            unit_call_sign="M7",
            response_mode_to_scene_code="2235003",
        ),
        user_id="u",
    )
    rows = await project_chart_response(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    by_element = {r["element_number"]: r for r in rows}
    assert {
        "eResponse.01",
        "eResponse.02",
        "eResponse.05",
        "eResponse.07",
        "eResponse.13",
        "eResponse.14",
        "eResponse.23",
    } <= set(by_element.keys())
    for r in rows:
        assert r["section"] == SECTION
        assert r["value"] is not None


@pytest.mark.asyncio
async def test_projection_groups_vehicle_dispatch_location(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-2")
    await ChartResponseService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartResponsePayload(
            vehicle_dispatch_address="200 Main St",
            vehicle_dispatch_lat=37.7749,
            vehicle_dispatch_long=-122.4194,
            vehicle_dispatch_usng="10SEG1234567890",
        ),
        user_id="u",
    )
    rows = await project_chart_response(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    # All four vehicle-dispatch rows must share the group_path.
    grouped = [r for r in rows if r["group_path"] == VEHICLE_DISPATCH_GROUP]
    assert len(grouped) == 4
    element_numbers = {r["element_number"] for r in grouped}
    assert {"eResponse.16", "eResponse.17", "eResponse.18"} <= element_numbers
    # The scalar (non-grouped) rows must NOT carry the group_path.
    for r in rows:
        if r["element_number"] not in {"eResponse.16", "eResponse.17", "eResponse.18"}:
            assert r["group_path"] == ""


@pytest.mark.asyncio
async def test_projection_expands_additional_descriptors_list(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-1", "C-3")
    await ChartResponseService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartResponsePayload(
            additional_response_descriptors_json=["2210001", "2210003", "2210007"],
        ),
        user_id="u",
    )
    rows = await project_chart_response(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    descriptor_rows = [r for r in rows if r["element_number"] == "eResponse.24"]
    assert len(descriptor_rows) == 3
    # Each descriptor gets its own occurrence_id and sequence_index.
    by_seq = {r["sequence_index"]: r for r in descriptor_rows}
    assert by_seq[0]["value"] == "2210001"
    assert by_seq[1]["value"] == "2210003"
    assert by_seq[2]["value"] == "2210007"
    occurrence_ids = {r["occurrence_id"] for r in descriptor_rows}
    assert len(occurrence_ids) == 3


@pytest.mark.asyncio
async def test_projection_emits_one_row_per_delay(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-4")
    await ChartResponseService.add_delay(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartResponseDelayPayload(delay_kind="dispatch", delay_code="D1"),
        user_id="u",
    )
    await ChartResponseService.add_delay(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartResponseDelayPayload(delay_kind="response", delay_code="R1"),
        user_id="u",
    )
    await ChartResponseService.add_delay(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartResponseDelayPayload(delay_kind="scene", delay_code="S1"),
        user_id="u",
    )
    await ChartResponseService.add_delay(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartResponseDelayPayload(delay_kind="transport", delay_code="T1"),
        user_id="u",
    )
    await ChartResponseService.add_delay(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartResponseDelayPayload(delay_kind="turn_around", delay_code="TA1"),
        user_id="u",
    )
    rows = await project_chart_response(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    elements = {r["element_number"] for r in rows}
    assert {
        "eResponse.08",
        "eResponse.09",
        "eResponse.10",
        "eResponse.11",
        "eResponse.12",
    } <= elements
    # Each delay row must carry a non-empty occurrence_id (= delay row id).
    delay_rows = [r for r in rows if r["element_number"] in {
        "eResponse.08", "eResponse.09", "eResponse.10",
        "eResponse.11", "eResponse.12",
    }]
    for r in delay_rows:
        assert r["occurrence_id"]


@pytest.mark.asyncio
async def test_projection_skips_none_columns(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-5")
    await ChartResponseService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartResponsePayload(agency_number="A1"),
        user_id="u",
    )
    rows = await project_chart_response(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert len(rows) == 1
    assert rows[0]["element_number"] == "eResponse.01"


@pytest.mark.asyncio
async def test_projection_returns_empty_when_no_meta_or_delays(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-1", "C-empty")
    rows = await project_chart_response(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert rows == []


@pytest.mark.asyncio
async def test_projection_is_idempotent(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-idem")
    await ChartResponseService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartResponsePayload(agency_number="A1", unit_call_sign="M7"),
        user_id="u",
    )
    await ChartResponseService.add_delay(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartResponseDelayPayload(delay_kind="dispatch", delay_code="D1"),
        user_id="u",
    )
    rows1 = await project_chart_response(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    rows2 = await project_chart_response(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert len(rows1) == len(rows2)
    ledger = (
        await session.execute(
            select(NemsisFieldValue).where(
                NemsisFieldValue.chart_id == chart.id,
                NemsisFieldValue.section == SECTION,
            )
        )
    ).scalars().all()
    assert len(ledger) == len(rows1)


@pytest.mark.asyncio
async def test_scalar_binding_columns_exist_on_model() -> None:
    from epcr_app.models_chart_response import ChartResponse
    cols = {c.name for c in ChartResponse.__table__.columns}
    for col, _, _ in _SCALAR_ELEMENT_BINDING:
        assert col in cols, f"scalar binding refers to missing column: {col}"
    for col, _, _ in _VEHICLE_DISPATCH_BINDING:
        assert col in cols, f"vehicle dispatch binding refers to missing column: {col}"


@pytest.mark.asyncio
async def test_delay_element_binding_covers_all_kinds() -> None:
    assert set(_DELAY_ELEMENT_BINDING.keys()) == {
        "dispatch",
        "response",
        "scene",
        "transport",
        "turn_around",
    }
    elements = {e for e, _n in _DELAY_ELEMENT_BINDING.values()}
    assert elements == {
        "eResponse.08",
        "eResponse.09",
        "eResponse.10",
        "eResponse.11",
        "eResponse.12",
    }
