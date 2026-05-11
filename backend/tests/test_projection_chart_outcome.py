"""Projection tests: :class:`ChartOutcome` -> NemsisFieldValue ledger.

Verifies that populated single-value columns produce one ledger row
per eOutcome.NN, that populated 1:M JSON list columns produce one row
per list entry (with
``occurrence_id = f"{row_id}-{element_number}-{idx}"`` and
``sequence_index = idx``), and that None / empty-list columns are NOT
projected.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart
from epcr_app.models_chart_outcome import ChartOutcome  # noqa: F401
from epcr_app.models_nemsis_field_values import NemsisFieldValue
from epcr_app.projection_chart_outcome import (
    SECTION,
    _ELEMENT_BINDING,
    project_chart_outcome,
)
from epcr_app.services_chart_outcome import (
    _OUTCOME_FIELDS,
    _OUTCOME_LIST_FIELDS,
    ChartOutcomePayload,
    ChartOutcomeService,
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
async def test_projection_emits_one_row_per_single_value(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-1", "C-1")
    t0 = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
    await ChartOutcomeService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartOutcomePayload(
            emergency_department_disposition_code="4209001",
            hospital_disposition_code="4210001",
            trauma_registry_incident_id="TR-2026-0001",
            hospital_length_of_stay_days=5,
            emergency_department_arrival_at=t0,
            medical_record_number="MRN-0001",
        ),
        user_id="u",
    )

    rows = await project_chart_outcome(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    by_element = {r["element_number"]: r for r in rows}
    assert by_element["eOutcome.01"]["value"] == "4209001"
    assert by_element["eOutcome.02"]["value"] == "4210001"
    assert by_element["eOutcome.06"]["value"] == "TR-2026-0001"
    assert by_element["eOutcome.16"]["value"] == "5"
    assert by_element["eOutcome.09"]["value"].startswith("2026-05-10T12:00:00")
    assert by_element["eOutcome.21"]["value"] == "MRN-0001"
    for row in rows:
        assert row["section"] == SECTION
        assert row["group_path"] == ""


@pytest.mark.asyncio
async def test_projection_expands_json_list_into_one_row_per_entry(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-1", "C-2")
    await ChartOutcomeService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartOutcomePayload(
            emergency_department_diagnosis_codes_json=["I21.4", "E11.9", "J18.9"],
            hospital_procedures_performed_codes_json=["0270346"],
            cause_of_death_codes_json=["I46.9", "I21.0"],
        ),
        user_id="u",
    )
    rows = await project_chart_outcome(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )

    by_element: dict[str, list[dict]] = {}
    for r in rows:
        by_element.setdefault(r["element_number"], []).append(r)

    assert len(by_element["eOutcome.03"]) == 3
    assert len(by_element["eOutcome.05"]) == 1
    assert len(by_element["eOutcome.19"]) == 2

    # Check sequence_index and occurrence_id pattern on the list entries.
    fetched = await ChartOutcomeService.get(
        session, tenant_id="t-1", chart_id=chart.id
    )
    row_id = fetched["id"]
    e03_sorted = sorted(by_element["eOutcome.03"], key=lambda r: r["sequence_index"])
    assert [r["sequence_index"] for r in e03_sorted] == [0, 1, 2]
    assert [r["occurrence_id"] for r in e03_sorted] == [
        f"{row_id}-eOutcome.03-0",
        f"{row_id}-eOutcome.03-1",
        f"{row_id}-eOutcome.03-2",
    ]
    assert [r["value"] for r in e03_sorted] == ["I21.4", "E11.9", "J18.9"]

    e19_sorted = sorted(by_element["eOutcome.19"], key=lambda r: r["sequence_index"])
    assert [r["occurrence_id"] for r in e19_sorted] == [
        f"{row_id}-eOutcome.19-0",
        f"{row_id}-eOutcome.19-1",
    ]


@pytest.mark.asyncio
async def test_projection_skips_none_and_empty_list_columns(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-1", "C-3")
    await ChartOutcomeService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartOutcomePayload(
            hospital_disposition_code="4210001",
            emergency_department_diagnosis_codes_json=[],
        ),
        user_id="u",
    )
    rows = await project_chart_outcome(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert len(rows) == 1
    assert rows[0]["element_number"] == "eOutcome.02"


@pytest.mark.asyncio
async def test_projection_is_idempotent_upserting_same_element(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-1", "C-4")
    await ChartOutcomeService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartOutcomePayload(
            hospital_disposition_code="4210001",
            cause_of_death_codes_json=["I46.9", "I21.0"],
        ),
        user_id="u",
    )
    rows1 = await project_chart_outcome(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    rows2 = await project_chart_outcome(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert len(rows1) == len(rows2) == 3  # eOutcome.02 + 2x eOutcome.19 entries

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
    rows = await project_chart_outcome(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert rows == []


@pytest.mark.asyncio
async def test_projection_binding_covers_every_persisted_column() -> None:
    """The binding table must cover every persisted outcome column."""
    binding_cols = {col for col, _e, _n in _ELEMENT_BINDING}
    assert binding_cols == set(_OUTCOME_FIELDS), (
        f"projection binding drift: missing={set(_OUTCOME_FIELDS) - binding_cols}, "
        f"extra={binding_cols - set(_OUTCOME_FIELDS)}"
    )


@pytest.mark.asyncio
async def test_projection_element_numbers_match_nemsis() -> None:
    """The eOutcome.NN numbers must match the v3.5.1 data dictionary."""
    elem_for_col = {col: elem for col, elem, _n in _ELEMENT_BINDING}
    assert elem_for_col["emergency_department_disposition_code"] == "eOutcome.01"
    assert elem_for_col["hospital_disposition_code"] == "eOutcome.02"
    assert elem_for_col["emergency_department_diagnosis_codes_json"] == "eOutcome.03"
    assert elem_for_col["hospital_admission_diagnosis_codes_json"] == "eOutcome.04"
    assert elem_for_col["hospital_procedures_performed_codes_json"] == "eOutcome.05"
    assert elem_for_col["trauma_registry_incident_id"] == "eOutcome.06"
    assert elem_for_col["hospital_outcome_at_discharge_code"] == "eOutcome.07"
    assert (
        elem_for_col["patient_disposition_from_emergency_department_at"]
        == "eOutcome.08"
    )
    assert elem_for_col["emergency_department_arrival_at"] == "eOutcome.09"
    assert elem_for_col["icu_admit_at"] == "eOutcome.14"
    assert elem_for_col["hospital_length_of_stay_days"] == "eOutcome.16"
    assert elem_for_col["cause_of_death_codes_json"] == "eOutcome.19"
    assert elem_for_col["date_of_death"] == "eOutcome.20"
    assert elem_for_col["referred_to_facility_name"] == "eOutcome.24"
    # All four 1:M list columns are flagged as list fields on the service.
    list_binding = {
        col for col, _e, _n in _ELEMENT_BINDING if col in _OUTCOME_LIST_FIELDS
    }
    assert list_binding == _OUTCOME_LIST_FIELDS
