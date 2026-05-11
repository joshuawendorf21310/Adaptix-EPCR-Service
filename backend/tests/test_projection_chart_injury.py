"""Projection tests: :class:`ChartInjury` (+ ACN) -> NemsisFieldValue ledger.

Verifies that scalar columns produce one ledger row per eInjury.NN,
JSON-list columns produce one row per list entry (with deterministic
occurrence_id), ACN columns are emitted under the
``eInjury.AutomatedCrashNotificationGroup`` group_path, and None
columns are NOT projected.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart
from epcr_app.models_chart_injury import ChartInjury, ChartInjuryAcn  # noqa: F401
from epcr_app.models_nemsis_field_values import NemsisFieldValue
from epcr_app.projection_chart_injury import (
    ACN_GROUP_PATH,
    SECTION,
    _ACN_BINDING,
    _INJURY_BINDING,
    project_chart_injury,
)
from epcr_app.services_chart_injury import (
    ChartInjuryAcnPayload,
    ChartInjuryPayload,
    ChartInjuryService,
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
async def test_projection_scalar_columns_emit_one_row_each(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-1", "C-1")
    await ChartInjuryService.upsert_injury(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartInjuryPayload(
            mechanism_of_injury_code="3040001",
            vehicle_impact_area_code="3060001",
            patient_location_in_vehicle_code="3060002",
            airbag_deployment_code="3070001",
            height_of_fall_feet=12.5,
        ),
        user_id="u",
    )
    rows = await project_chart_injury(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    by_element = {r["element_number"]: r for r in rows}
    assert {"eInjury.02", "eInjury.05", "eInjury.06", "eInjury.08", "eInjury.09"} <= set(by_element.keys())
    for row in rows:
        assert row["section"] == SECTION
        assert row["group_path"] == ""
        assert row["occurrence_id"] == ""
    # Numeric stringification for eInjury.09
    assert by_element["eInjury.09"]["value"] == "12.5"


@pytest.mark.asyncio
async def test_projection_json_list_emits_one_row_per_entry(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-1", "C-2")
    record = await ChartInjuryService.upsert_injury(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartInjuryPayload(
            cause_of_injury_codes_json=["3030001", "3030003", "3030007"],
            trauma_triage_high_codes_json=["3050001", "3050002"],
        ),
        user_id="u",
    )
    injury_id = record["id"]
    rows = await project_chart_injury(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    # eInjury.01 -> 3 rows, eInjury.03 -> 2 rows, plus no other populated.
    cause_rows = [r for r in rows if r["element_number"] == "eInjury.01"]
    high_rows = [r for r in rows if r["element_number"] == "eInjury.03"]
    assert len(cause_rows) == 3
    assert len(high_rows) == 2
    # occurrence_ids must be deterministic and unique per (element, idx).
    expected_cause_occ = {f"{injury_id}-eInjury.01-{i}" for i in range(3)}
    expected_high_occ = {f"{injury_id}-eInjury.03-{i}" for i in range(2)}
    assert {r["occurrence_id"] for r in cause_rows} == expected_cause_occ
    assert {r["occurrence_id"] for r in high_rows} == expected_high_occ
    # Values preserve list order via sequence_index.
    cause_by_idx = {r["sequence_index"]: r["value"] for r in cause_rows}
    assert cause_by_idx == {0: "3030001", 1: "3030003", 2: "3030007"}


@pytest.mark.asyncio
async def test_projection_acn_block_uses_group_path(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-3")
    await ChartInjuryService.upsert_injury(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartInjuryPayload(),
        user_id="u",
    )
    t0 = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
    await ChartInjuryService.upsert_acn(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartInjuryAcnPayload(
            acn_system_company="Acme Telematics",
            acn_incident_at=t0,
            acn_delta_velocity=42.5,
            acn_vehicle_model_year=2024,
            acn_pdof=90,
        ),
        user_id="u",
    )
    rows = await project_chart_injury(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    acn_rows = [r for r in rows if r["group_path"] == ACN_GROUP_PATH]
    assert len(acn_rows) == 5
    by_element = {r["element_number"]: r for r in acn_rows}
    assert by_element["eInjury.11"]["value"] == "Acme Telematics"
    assert by_element["eInjury.14"]["value"].startswith("2026-05-10T12:00:00")
    assert by_element["eInjury.22"]["value"] == "42.5"
    assert by_element["eInjury.20"]["value"] == "2024"
    assert by_element["eInjury.24"]["value"] == "90"
    for row in acn_rows:
        assert row["section"] == SECTION
        assert row["occurrence_id"] == ""


@pytest.mark.asyncio
async def test_projection_skips_none_columns(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-4")
    await ChartInjuryService.upsert_injury(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartInjuryPayload(mechanism_of_injury_code="3040001"),
        user_id="u",
    )
    rows = await project_chart_injury(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert len(rows) == 1
    assert rows[0]["element_number"] == "eInjury.02"


@pytest.mark.asyncio
async def test_projection_is_idempotent(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-5")
    await ChartInjuryService.upsert_injury(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartInjuryPayload(
            cause_of_injury_codes_json=["3030001", "3030003"],
            mechanism_of_injury_code="3040001",
        ),
        user_id="u",
    )
    rows1 = await project_chart_injury(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    rows2 = await project_chart_injury(
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
    # 2 list entries + 1 scalar = 3 unique rows; no duplicates.
    assert len(ledger) == 3


@pytest.mark.asyncio
async def test_projection_returns_empty_when_no_injury(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-empty")
    rows = await project_chart_injury(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert rows == []


@pytest.mark.asyncio
async def test_projection_binding_covers_every_column() -> None:
    """The binding tables must cover every column on the model."""
    from epcr_app.services_chart_injury import _ACN_FIELDS, _INJURY_FIELDS

    injury_cols = {col for col, _e, _n, _l in _INJURY_BINDING}
    acn_cols = {col for col, _e, _n in _ACN_BINDING}
    assert injury_cols == set(_INJURY_FIELDS)
    assert acn_cols == set(_ACN_FIELDS)


@pytest.mark.asyncio
async def test_projection_element_names_match_dictionary() -> None:
    """The NEMSIS element names in the bindings must match v3.5.1."""
    injury_names = {elem: name for _col, elem, name, _l in _INJURY_BINDING}
    acn_names = {elem: name for _col, elem, name in _ACN_BINDING}
    assert injury_names["eInjury.01"] == "Cause of Injury"
    assert injury_names["eInjury.02"] == "Mechanism of Injury"
    assert injury_names["eInjury.05"] == "Main Area of the Vehicle Impacted"
    assert injury_names["eInjury.07"] == "Use of Occupant Safety Equipment"
    assert injury_names["eInjury.10"] == "OSHA Personal Protective Equipment Used"
    assert acn_names["eInjury.11"] == "ACN System/Company"
    assert acn_names["eInjury.14"] == "Date/Time of ACN Incident"
    assert acn_names["eInjury.22"] == "ACN Incident Delta Velocity"
    assert acn_names["eInjury.27"] == "Seat Occupied"
    assert acn_names["eInjury.29"] == "ACN Incident Airbag Deployed"
