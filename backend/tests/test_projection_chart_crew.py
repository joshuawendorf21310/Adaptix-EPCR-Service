"""Projection tests: :class:`ChartCrewMember` -> NemsisFieldValue ledger.

Verifies that each crew row produces exactly three ledger rows
(eCrew.01/02/03) that share the crew row's UUID as occurrence_id,
and that re-projection is idempotent (upsert by element/group/occurrence).
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart
from epcr_app.models_chart_crew import ChartCrewMember  # noqa: F401
from epcr_app.models_nemsis_field_values import NemsisFieldValue
from epcr_app.projection_chart_crew import (
    SECTION,
    _ELEMENT_BINDING,
    project_chart_crew,
)
from epcr_app.services_chart_crew import ChartCrewPayload, ChartCrewService


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
async def test_projection_emits_three_rows_per_crew_member(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-1", "C-1")
    record = await ChartCrewService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartCrewPayload(
            crew_member_id="EMP-1",
            crew_member_level_code="Paramedic",
            crew_member_response_role_code="lead",
            sequence_index=0,
        ),
        user_id="u",
    )
    rows = await project_chart_crew(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert len(rows) == 3
    by_element = {r["element_number"]: r for r in rows}
    assert set(by_element.keys()) == {"eCrew.01", "eCrew.02", "eCrew.03"}
    # All three share the crew row's UUID as occurrence_id.
    assert by_element["eCrew.01"]["occurrence_id"] == record["id"]
    assert by_element["eCrew.02"]["occurrence_id"] == record["id"]
    assert by_element["eCrew.03"]["occurrence_id"] == record["id"]
    assert by_element["eCrew.01"]["value"] == "EMP-1"
    assert by_element["eCrew.02"]["value"] == "Paramedic"
    assert by_element["eCrew.03"]["value"] == "lead"
    for row in rows:
        assert row["section"] == SECTION
        assert row["group_path"] == ""


@pytest.mark.asyncio
async def test_projection_multiple_crew_members(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-2")
    a = await ChartCrewService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartCrewPayload(
            crew_member_id="EMP-A",
            crew_member_level_code="Paramedic",
            crew_member_response_role_code="lead",
            sequence_index=0,
        ),
        user_id="u",
    )
    b = await ChartCrewService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartCrewPayload(
            crew_member_id="EMP-B",
            crew_member_level_code="EMT",
            crew_member_response_role_code="driver",
            sequence_index=1,
        ),
        user_id="u",
    )
    rows = await project_chart_crew(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    # 2 crew * 3 elements = 6 ledger rows.
    assert len(rows) == 6
    occurrence_ids = {r["occurrence_id"] for r in rows}
    assert occurrence_ids == {a["id"], b["id"]}
    # sequence_index propagates from the crew row to the ledger row.
    for r in rows:
        if r["occurrence_id"] == a["id"]:
            assert r["sequence_index"] == 0
        else:
            assert r["sequence_index"] == 1


@pytest.mark.asyncio
async def test_projection_is_idempotent_upserting_same_occurrence(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-1", "C-3")
    await ChartCrewService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartCrewPayload(
            crew_member_id="EMP-1",
            crew_member_level_code="Paramedic",
            crew_member_response_role_code="lead",
        ),
        user_id="u",
    )
    rows1 = await project_chart_crew(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    rows2 = await project_chart_crew(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert len(rows1) == 3 == len(rows2)
    ledger = (
        await session.execute(
            select(NemsisFieldValue).where(
                NemsisFieldValue.chart_id == chart.id,
                NemsisFieldValue.section == SECTION,
            )
        )
    ).scalars().all()
    # Three element rows per crew member, not six.
    assert len(ledger) == 3


@pytest.mark.asyncio
async def test_projection_returns_empty_when_no_crew(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-empty")
    rows = await project_chart_crew(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert rows == []


@pytest.mark.asyncio
async def test_projection_binding_covers_all_three_elements() -> None:
    """The binding must declare eCrew.01, .02, .03."""
    elements = {elem for _col, elem, _name in _ELEMENT_BINDING}
    assert elements == {"eCrew.01", "eCrew.02", "eCrew.03"}


@pytest.mark.asyncio
async def test_projection_element_names_match_dictionary() -> None:
    """The NEMSIS element names in the binding must match v3.5.1 data dictionary."""
    name_for_element = {elem: name for _col, elem, name in _ELEMENT_BINDING}
    assert name_for_element["eCrew.01"] == "Crew Member ID"
    assert name_for_element["eCrew.02"] == "Crew Member Level"
    assert name_for_element["eCrew.03"] == "Crew Member Response Role"
