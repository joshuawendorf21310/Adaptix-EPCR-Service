"""Projection tests: :class:`ChartDispatch` -> NemsisFieldValue ledger.

Verifies that populated dispatch columns produce one ledger row per
eDispatch.NN with the canonical element_number / element_name, and that
None columns are NOT projected (preserving NEMSIS absence semantics).
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart
from epcr_app.models_chart_dispatch import ChartDispatch  # noqa: F401
from epcr_app.models_nemsis_field_values import NemsisFieldValue
from epcr_app.projection_chart_dispatch import (
    SECTION,
    _ELEMENT_BINDING,
    project_chart_dispatch,
)
from epcr_app.services_chart_dispatch import ChartDispatchPayload, ChartDispatchService


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
async def test_projection_emits_one_row_per_populated_field(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-1")
    payload = ChartDispatchPayload(
        dispatch_reason_code="2301001",
        emd_performed_code="2302003",
        emd_determinant_code="26-D-1",
        dispatch_center_id="DC-001",
        dispatch_priority_code="2305003",
    )
    await ChartDispatchService.upsert(
        session, tenant_id="t-1", chart_id=chart.id, payload=payload, user_id="u"
    )

    rows = await project_chart_dispatch(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert len(rows) == 5

    by_element = {r["element_number"]: r for r in rows}
    assert set(by_element.keys()) == {
        "eDispatch.01",
        "eDispatch.02",
        "eDispatch.03",
        "eDispatch.04",
        "eDispatch.05",
    }
    for row in rows:
        assert row["section"] == SECTION
        assert row["value"] is not None
        assert row["group_path"] == ""


@pytest.mark.asyncio
async def test_projection_skips_none_columns(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-2")
    await ChartDispatchService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartDispatchPayload(dispatch_reason_code="2301001"),
        user_id="u",
    )
    rows = await project_chart_dispatch(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert len(rows) == 1
    assert rows[0]["element_number"] == "eDispatch.01"


@pytest.mark.asyncio
async def test_projection_is_idempotent_upserting_same_element(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-3")
    await ChartDispatchService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartDispatchPayload(dispatch_center_id="DC-001"),
        user_id="u",
    )
    rows1 = await project_chart_dispatch(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    rows2 = await project_chart_dispatch(
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
    rows = await project_chart_dispatch(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert rows == []


@pytest.mark.asyncio
async def test_projection_binding_covers_every_column() -> None:
    """The binding table must cover every column on the model."""
    excluded = {
        "id",
        "tenant_id",
        "chart_id",
        "created_by_user_id",
        "updated_by_user_id",
        "created_at",
        "updated_at",
        "deleted_at",
        "version",
    }
    model_cols = {
        c.name
        for c in __import__(
            "epcr_app.models_chart_dispatch", fromlist=["ChartDispatch"]
        ).ChartDispatch.__table__.columns
        if c.name not in excluded
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
    assert name_for_element["eDispatch.01"] == "Dispatch Reason"
    assert name_for_element["eDispatch.02"] == "EMD Performed"
    assert name_for_element["eDispatch.03"] == "EMD Determinant Code"
    assert name_for_element["eDispatch.04"] == "Dispatch Center Name or ID"
    assert name_for_element["eDispatch.05"] == "Dispatch Priority (Patient Acuity)"
    assert name_for_element["eDispatch.06"] == "Unit Dispatched CAD Record ID"
