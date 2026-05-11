"""Projection tests: eSituation -> NemsisFieldValue ledger.

Verifies that populated scalar columns produce one ledger row per
eSituation.NN with the canonical element_number / element_name, that
the two repeating groups (eSituation.10, eSituation.12) produce one
ledger row per child row keyed by the child UUID, and that None
columns/empty child tables are NOT projected.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart
from epcr_app.models_chart_situation import (  # noqa: F401
    ChartSituation,
    ChartSituationOtherSymptom,
    ChartSituationSecondaryImpression,
)
from epcr_app.models_nemsis_field_values import NemsisFieldValue
from epcr_app.projection_chart_situation import (
    SECTION,
    _COMPLAINT_DURATION_GROUP,
    _SCALAR_BINDING,
    project_chart_situation,
)
from epcr_app.services_chart_situation import (
    ChartSituationOtherSymptomPayload,
    ChartSituationOtherSymptomService,
    ChartSituationPayload,
    ChartSituationSecondaryImpressionPayload,
    ChartSituationSecondaryImpressionService,
    ChartSituationService,
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
async def test_projection_emits_scalar_rows(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-1")
    onset = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
    await ChartSituationService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartSituationPayload(
            symptom_onset_at=onset,
            possible_injury_indicator_code="9922001",
            complaint_type_code="9914001",
            complaint_text="Chest pain",
            primary_symptom_code="R07.9",
            provider_primary_impression_code="I21.9",
            initial_patient_acuity_code="2207003",
            work_related_indicator_code="9922001",
        ),
        user_id="u",
    )

    rows = await project_chart_situation(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    elements = {r["element_number"] for r in rows}
    assert {
        "eSituation.01",
        "eSituation.02",
        "eSituation.03",
        "eSituation.04",
        "eSituation.09",
        "eSituation.11",
        "eSituation.13",
        "eSituation.14",
    } <= elements
    for row in rows:
        assert row["section"] == SECTION
        assert row["value"] is not None
        assert row["occurrence_id"] == ""


@pytest.mark.asyncio
async def test_projection_complaint_duration_uses_group_path(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-1", "C-Dur")
    await ChartSituationService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartSituationPayload(
            complaint_duration_value=30,
            complaint_duration_units_code="2553011",
        ),
        user_id="u",
    )
    rows = await project_chart_situation(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    by_element = {r["element_number"]: r for r in rows}
    assert by_element["eSituation.05"]["group_path"] == _COMPLAINT_DURATION_GROUP
    assert by_element["eSituation.06"]["group_path"] == _COMPLAINT_DURATION_GROUP


@pytest.mark.asyncio
async def test_projection_skips_none_scalars(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-Sparse")
    await ChartSituationService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartSituationPayload(primary_symptom_code="R07.9"),
        user_id="u",
    )
    rows = await project_chart_situation(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert len(rows) == 1
    assert rows[0]["element_number"] == "eSituation.09"


@pytest.mark.asyncio
async def test_projection_emits_other_symptoms_with_occurrence_id(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-1", "C-Sym")
    a = await ChartSituationOtherSymptomService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartSituationOtherSymptomPayload(symptom_code="R06.0", sequence_index=0),
        user_id="u",
    )
    b = await ChartSituationOtherSymptomService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartSituationOtherSymptomPayload(symptom_code="R51", sequence_index=1),
        user_id="u",
    )
    rows = await project_chart_situation(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    sym_rows = [r for r in rows if r["element_number"] == "eSituation.10"]
    assert len(sym_rows) == 2
    occ_ids = {r["occurrence_id"] for r in sym_rows}
    assert occ_ids == {a["id"], b["id"]}
    values = {r["value"] for r in sym_rows}
    assert values == {"R06.0", "R51"}


@pytest.mark.asyncio
async def test_projection_emits_secondary_impressions_with_occurrence_id(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-1", "C-Imp")
    a = await ChartSituationSecondaryImpressionService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartSituationSecondaryImpressionPayload(
            impression_code="I50.9", sequence_index=0
        ),
        user_id="u",
    )
    b = await ChartSituationSecondaryImpressionService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartSituationSecondaryImpressionPayload(
            impression_code="I10", sequence_index=1
        ),
        user_id="u",
    )
    rows = await project_chart_situation(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    imp_rows = [r for r in rows if r["element_number"] == "eSituation.12"]
    assert len(imp_rows) == 2
    occ_ids = {r["occurrence_id"] for r in imp_rows}
    assert occ_ids == {a["id"], b["id"]}


@pytest.mark.asyncio
async def test_projection_is_idempotent(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-Idem")
    await ChartSituationService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartSituationPayload(complaint_text="abc", primary_symptom_code="R07.9"),
        user_id="u",
    )
    await ChartSituationOtherSymptomService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartSituationOtherSymptomPayload(symptom_code="R06.0"),
        user_id="u",
    )

    rows1 = await project_chart_situation(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    rows2 = await project_chart_situation(
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
async def test_projection_returns_empty_when_no_data(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-empty")
    rows = await project_chart_situation(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert rows == []


@pytest.mark.asyncio
async def test_projection_binding_covers_every_scalar_column() -> None:
    """The scalar binding must cover every persisted scalar column."""
    from epcr_app.services_chart_situation import _SITUATION_FIELDS

    binding_cols = {col for col, _e, _n, _g in _SCALAR_BINDING}
    assert binding_cols == set(_SITUATION_FIELDS)


@pytest.mark.asyncio
async def test_projection_element_names_match_dictionary() -> None:
    """NEMSIS v3.5.1 Data Dictionary names verbatim."""
    name_for_element = {elem: name for _c, elem, name, _g in _SCALAR_BINDING}
    assert name_for_element["eSituation.01"] == "Date/Time of Symptom Onset"
    assert name_for_element["eSituation.02"] == "Possible Injury"
    assert name_for_element["eSituation.03"] == "Complaint Type"
    assert name_for_element["eSituation.04"] == "Complaint"
    assert name_for_element["eSituation.05"] == "Duration of Complaint"
    assert name_for_element["eSituation.06"] == "Time Units of Duration of Complaint"
    assert name_for_element["eSituation.07"] == "Chief Complaint Anatomic Location"
    assert name_for_element["eSituation.08"] == "Chief Complaint Organ System"
    assert name_for_element["eSituation.09"] == "Primary Symptom"
    assert name_for_element["eSituation.11"] == "Provider's Primary Impression"
    assert name_for_element["eSituation.13"] == "Initial Patient Acuity"
    assert name_for_element["eSituation.14"] == "Work-Related Illness/Injury"
    assert name_for_element["eSituation.15"] == "Patient's Occupational Industry"
    assert name_for_element["eSituation.16"] == "Patient's Occupation"
    assert name_for_element["eSituation.17"] == "Patient Activity"
    assert name_for_element["eSituation.18"] == "Date/Time Last Known Well"
    assert name_for_element["eSituation.19"] == "Justification for Transfer or Encounter"
    assert (
        name_for_element["eSituation.20"]
        == "Reason for Interfacility Transfer/Medical Transport"
    )
