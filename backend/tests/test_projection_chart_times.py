"""Projection tests: :class:`ChartTimes` -> NemsisFieldValue ledger.

Verifies that populated time columns produce one ledger row per
eTimes.NN with the canonical element_number / element_name, and that
None columns are NOT projected (preserving NEMSIS absence semantics).
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart
from epcr_app.models_chart_times import ChartTimes  # noqa: F401
from epcr_app.models_nemsis_field_values import NemsisFieldValue
from epcr_app.projection_chart_times import (
    SECTION,
    _ELEMENT_BINDING,
    project_chart_times,
)
from epcr_app.services_chart_times import ChartTimesPayload, ChartTimesService


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


def _element_map() -> dict[str, str]:
    return {col: elem for col, elem, _name in _ELEMENT_BINDING}


@pytest.mark.asyncio
async def test_projection_emits_one_row_per_populated_time(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-1")
    t0 = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
    payload = ChartTimesPayload(
        psap_call_at=t0,
        unit_notified_by_dispatch_at=t0 + timedelta(seconds=10),
        unit_en_route_at=t0 + timedelta(minutes=1),
        unit_on_scene_at=t0 + timedelta(minutes=5),
        arrived_at_patient_at=t0 + timedelta(minutes=6),
        unit_left_scene_at=t0 + timedelta(minutes=15),
        patient_arrived_at_destination_at=t0 + timedelta(minutes=25),
        destination_transfer_of_care_at=t0 + timedelta(minutes=28),
    )
    await ChartTimesService.upsert(
        session, tenant_id="t-1", chart_id=chart.id, payload=payload, user_id="u"
    )

    rows = await project_chart_times(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert len(rows) == 8

    by_element = {r["element_number"]: r for r in rows}
    assert set(by_element.keys()) == {
        "eTimes.01",
        "eTimes.03",
        "eTimes.05",
        "eTimes.06",
        "eTimes.07",
        "eTimes.09",
        "eTimes.11",
        "eTimes.12",
    }
    for row in rows:
        assert row["section"] == SECTION
        assert row["value"] is not None
        assert row["group_path"] == ""


@pytest.mark.asyncio
async def test_projection_skips_none_columns(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-2")
    t0 = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
    await ChartTimesService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartTimesPayload(psap_call_at=t0),
        user_id="u",
    )
    rows = await project_chart_times(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert len(rows) == 1
    assert rows[0]["element_number"] == "eTimes.01"


@pytest.mark.asyncio
async def test_projection_is_idempotent_upserting_same_element(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-3")
    t0 = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
    await ChartTimesService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartTimesPayload(unit_on_scene_at=t0),
        user_id="u",
    )
    rows1 = await project_chart_times(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    rows2 = await project_chart_times(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert len(rows1) == 1 == len(rows2)
    # Same row id implies idempotent upsert, not duplicate insert.
    ledger = (
        await session.execute(
            select(NemsisFieldValue).where(
                NemsisFieldValue.chart_id == chart.id,
                NemsisFieldValue.section == SECTION,
            )
        )
    ).scalars().all()
    assert len(ledger) == 1


@pytest.mark.asyncio
async def test_projection_returns_empty_when_no_row(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-empty")
    rows = await project_chart_times(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert rows == []


@pytest.mark.asyncio
async def test_projection_binding_covers_every_column() -> None:
    """The binding table must cover every column on the model."""
    model_cols = {
        c.name
        for c in __import__("epcr_app.models_chart_times", fromlist=["ChartTimes"]).ChartTimes.__table__.columns
        if c.name.endswith("_at") and c.name not in {"created_at", "updated_at", "deleted_at"}
    }
    binding_cols = {col for col, _e, _n in _ELEMENT_BINDING}
    assert model_cols == binding_cols, (
        f"projection binding drift: missing={model_cols - binding_cols}, "
        f"extra={binding_cols - model_cols}"
    )


@pytest.mark.asyncio
async def test_projection_element_names_match_dictionary() -> None:
    """The NEMSIS element names in the binding must match v3.5.1 data dictionary."""
    name_for_element = {elem: name for _col, elem, name in _ELEMENT_BINDING}
    assert name_for_element["eTimes.01"] == "PSAP Call Date/Time"
    assert name_for_element["eTimes.06"] == "Unit Arrived on Scene Date/Time"
    assert name_for_element["eTimes.12"] == "Destination Patient Transfer of Care Date/Time"
    assert name_for_element["eTimes.17"] == "Unit Arrived at Staging Area Date/Time"
