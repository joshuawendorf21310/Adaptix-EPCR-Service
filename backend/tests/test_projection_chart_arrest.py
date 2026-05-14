"""Projection tests: :class:`ChartArrest` -> NemsisFieldValue ledger.

Verifies that populated single-value columns produce one ledger row per
eArrest.NN, that populated 1:M JSON list columns produce one row per
list entry (with ``occurrence_id = "{row_id}-{idx}"`` and
``sequence_index = idx``), and that None / empty-list columns are NOT
projected.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart
from epcr_app.models_chart_arrest import ChartArrest  # noqa: F401
from epcr_app.models_nemsis_field_values import NemsisFieldValue
from epcr_app.projection_chart_arrest import (
    SECTION,
    _ELEMENT_BINDING,
    project_chart_arrest,
)
from epcr_app.services_chart_arrest import (
    _ARREST_FIELDS,
    _ARREST_LIST_FIELDS,
    ChartArrestPayload,
    ChartArrestService,
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
async def test_projection_emits_one_row_per_single_value(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-1")
    t0 = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
    await ChartArrestService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartArrestPayload(
            cardiac_arrest_code="9512001",
            etiology_code="9514001",
            first_monitored_rhythm_code="9522001",
            arrest_at=t0,
        ),
        user_id="u",
    )

    rows = await project_chart_arrest(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    by_element = {r["element_number"]: r for r in rows}
    assert "eArrest.01" in by_element
    assert by_element["eArrest.01"]["value"] == "9512001"
    assert by_element["eArrest.02"]["value"] == "9514001"
    assert by_element["eArrest.11"]["value"] == "9522001"
    assert by_element["eArrest.14"]["value"].startswith("2026-05-10T12:00:00")
    for row in rows:
        assert row["section"] == SECTION
        assert row["group_path"] == ""


@pytest.mark.asyncio
async def test_projection_expands_json_list_into_one_row_per_entry(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-1", "C-2")
    await ChartArrestService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartArrestPayload(
            cardiac_arrest_code="9512001",
            resuscitation_attempted_codes_json=["9515003", "9515005", "9515009"],
            witnessed_by_codes_json=["9516001"],
        ),
        user_id="u",
    )
    rows = await project_chart_arrest(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )

    # eArrest.03 -> 3 entries; eArrest.04 -> 1 entry; eArrest.01 -> 1 row.
    by_element: dict[str, list[dict]] = {}
    for r in rows:
        by_element.setdefault(r["element_number"], []).append(r)

    assert len(by_element["eArrest.01"]) == 1
    assert len(by_element["eArrest.03"]) == 3
    assert len(by_element["eArrest.04"]) == 1

    # Check sequence_index and occurrence_id pattern on the list entries.
    fetched = await ChartArrestService.get(
        session, tenant_id="t-1", chart_id=chart.id
    )
    row_id = fetched["id"]
    e03_sorted = sorted(by_element["eArrest.03"], key=lambda r: r["sequence_index"])
    assert [r["sequence_index"] for r in e03_sorted] == [0, 1, 2]
    assert [r["occurrence_id"] for r in e03_sorted] == [
        f"{row_id}-0",
        f"{row_id}-1",
        f"{row_id}-2",
    ]
    assert [r["value"] for r in e03_sorted] == ["9515003", "9515005", "9515009"]


@pytest.mark.asyncio
async def test_projection_skips_none_and_empty_list_columns(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-1", "C-3")
    await ChartArrestService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartArrestPayload(cardiac_arrest_code="9512001"),
        user_id="u",
    )
    rows = await project_chart_arrest(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert len(rows) == 1
    assert rows[0]["element_number"] == "eArrest.01"


@pytest.mark.asyncio
async def test_projection_is_idempotent_upserting_same_element(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-1", "C-4")
    await ChartArrestService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartArrestPayload(
            cardiac_arrest_code="9512001",
            cpr_type_codes_json=["9520001", "9520003"],
        ),
        user_id="u",
    )
    rows1 = await project_chart_arrest(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    rows2 = await project_chart_arrest(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert len(rows1) == len(rows2) == 3  # eArrest.01 + 2x eArrest.09 entries

    ledger = (
        await session.execute(
            select(NemsisFieldValue).where(
                NemsisFieldValue.chart_id == chart.id,
                NemsisFieldValue.section == SECTION,
            )
        )
    ).scalars().all()
    # Same set of (element_number, occurrence_id) -> idempotent upsert.
    assert len(ledger) == 3


@pytest.mark.asyncio
async def test_projection_returns_empty_when_no_row(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-empty")
    rows = await project_chart_arrest(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert rows == []


@pytest.mark.asyncio
async def test_projection_binding_covers_every_persisted_column() -> None:
    """The binding table must cover every persisted arrest column."""
    binding_cols = {col for col, _e, _n in _ELEMENT_BINDING}
    assert binding_cols == set(_ARREST_FIELDS), (
        f"projection binding drift: missing={set(_ARREST_FIELDS) - binding_cols}, "
        f"extra={binding_cols - set(_ARREST_FIELDS)}"
    )


@pytest.mark.asyncio
async def test_projection_element_numbers_match_nemsis() -> None:
    """The eArrest.NN numbers must match the v3.5.1 data dictionary."""
    elem_for_col = {col: elem for col, elem, _n in _ELEMENT_BINDING}
    assert elem_for_col["cardiac_arrest_code"] == "eArrest.01"
    assert elem_for_col["etiology_code"] == "eArrest.02"
    assert elem_for_col["resuscitation_attempted_codes_json"] == "eArrest.03"
    assert elem_for_col["witnessed_by_codes_json"] == "eArrest.04"
    assert elem_for_col["aed_use_prior_code"] == "eArrest.07"
    assert elem_for_col["cpr_type_codes_json"] == "eArrest.09"
    assert elem_for_col["hypothermia_indicator_code"] == "eArrest.10"
    assert elem_for_col["rosc_codes_json"] == "eArrest.12"
    assert elem_for_col["arrest_at"] == "eArrest.14"
    assert elem_for_col["who_first_defib_code"] == "eArrest.22"
    # All four 1:M list columns are flagged as list fields on the service.
    list_binding = {
        col for col, _e, _n in _ELEMENT_BINDING if col in _ARREST_LIST_FIELDS
    }
    assert list_binding == _ARREST_LIST_FIELDS
