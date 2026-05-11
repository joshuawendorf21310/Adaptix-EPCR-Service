"""Projection tests: eHistory aggregate -> NemsisFieldValue ledger.

Verifies that:

* meta scalars project to one ledger row each with empty group_path and
  empty occurrence_id;
* meta JSON list columns (eHistory.01/.05/.09/.17) project to one row
  per list entry with occurrence_id=f"{meta.id}-{element}-{idx}";
* allergies project to eHistory.06 / eHistory.07 with the right
  group_path and occurrence_id=row.id;
* surgical conditions project to eHistory.08;
* current medications project under eHistory.CurrentMedicationGroup,
  one ledger row per populated field per occurrence;
* immunizations project to eHistory.10 / eHistory.11 with
  occurrence_id=row.id;
* the projection is idempotent on repeat invocation;
* absent inputs project to an empty list.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart
from epcr_app.models_chart_history import (  # noqa: F401 - register tables
    ChartHistoryAllergy,
    ChartHistoryCurrentMedication,
    ChartHistoryImmunization,
    ChartHistoryMeta,
    ChartHistorySurgical,
)
from epcr_app.models_nemsis_field_values import NemsisFieldValue
from epcr_app.projection_chart_history import (
    SECTION,
    _ALLERGY_KIND_BINDING,
    _CURRENT_MED_GROUP,
    _MEDICATION_BINDING,
    _META_LIST_BINDING,
    _META_SCALAR_BINDING,
    project_chart_history,
)
from epcr_app.services_chart_history import (
    AllergyPayload,
    ChartHistoryAllergyService,
    ChartHistoryCurrentMedicationService,
    ChartHistoryImmunizationService,
    ChartHistoryMetaPayload,
    ChartHistoryMetaService,
    ChartHistorySurgicalService,
    CurrentMedicationPayload,
    ImmunizationPayload,
    SurgicalPayload,
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
async def test_projection_empty_when_no_data(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-empty")
    rows = await project_chart_history(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert rows == []


@pytest.mark.asyncio
async def test_projection_meta_scalars(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-scalars")
    t0 = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
    await ChartHistoryMetaService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartHistoryMetaPayload(
            practitioner_last_name="Doe",
            practitioner_first_name="Jane",
            practitioner_middle_name="A",
            pregnancy_code="3535005",
            last_oral_intake_at=t0,
            emergency_information_form_code="3508001",
        ),
        user_id="u",
    )
    rows = await project_chart_history(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    by_elem = {r["element_number"]: r for r in rows}
    assert "eHistory.02" in by_elem
    assert by_elem["eHistory.02"]["value"] == "Doe"
    assert by_elem["eHistory.02"]["element_name"] == "Practitioner Last Name"
    assert by_elem["eHistory.03"]["value"] == "Jane"
    assert by_elem["eHistory.04"]["value"] == "A"
    assert by_elem["eHistory.16"]["value"] == "3508001"
    assert by_elem["eHistory.18"]["value"] == "3535005"
    assert by_elem["eHistory.19"]["value"].startswith("2026-05-10T12:00:00")
    # Scalars have no group_path / occurrence_id
    for r in rows:
        assert r["section"] == SECTION
        if r["element_number"] in {"eHistory.02", "eHistory.03", "eHistory.04",
                                   "eHistory.16", "eHistory.18", "eHistory.19"}:
            assert r["group_path"] == ""
            assert r["occurrence_id"] == ""


@pytest.mark.asyncio
async def test_projection_meta_lists_one_row_per_entry(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-1", "C-lists")
    await ChartHistoryMetaService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartHistoryMetaPayload(
            barriers_to_care_codes_json=["8801001", "8801003"],
            advance_directives_codes_json=["3501001"],
            medical_history_obtained_from_codes_json=["8807001", "8807002", "8807003"],
            alcohol_drug_use_codes_json=["3525001"],
        ),
        user_id="u",
    )
    rows = await project_chart_history(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    by_elem: dict[str, list[dict]] = {}
    for r in rows:
        by_elem.setdefault(r["element_number"], []).append(r)
    assert len(by_elem["eHistory.01"]) == 2
    assert len(by_elem["eHistory.05"]) == 1
    assert len(by_elem["eHistory.09"]) == 3
    assert len(by_elem["eHistory.17"]) == 1
    # Each list entry has a distinct occurrence_id with element + idx suffix
    occ_ids = {r["occurrence_id"] for r in by_elem["eHistory.09"]}
    assert len(occ_ids) == 3
    for oid in occ_ids:
        assert "-eHistory.09-" in oid


@pytest.mark.asyncio
async def test_projection_allergies_split_by_kind(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-allergy")
    med = await ChartHistoryAllergyService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=AllergyPayload(allergy_kind="medication", allergy_code="RX-1"),
        user_id="u",
    )
    env = await ChartHistoryAllergyService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=AllergyPayload(allergy_kind="environmental_food", allergy_code="ENV-1"),
        user_id="u",
    )
    rows = await project_chart_history(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    by_elem = {r["element_number"]: r for r in rows}
    assert by_elem["eHistory.06"]["value"] == "RX-1"
    assert by_elem["eHistory.06"]["group_path"] == "eHistory.MedicationAllergyGroup"
    assert by_elem["eHistory.06"]["occurrence_id"] == med["id"]
    assert by_elem["eHistory.07"]["value"] == "ENV-1"
    assert (
        by_elem["eHistory.07"]["group_path"] == "eHistory.EnvironmentalFoodAllergyGroup"
    )
    assert by_elem["eHistory.07"]["occurrence_id"] == env["id"]


@pytest.mark.asyncio
async def test_projection_surgical(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-surg")
    r1 = await ChartHistorySurgicalService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=SurgicalPayload(condition_code="I10"),
        user_id="u",
    )
    rows = await project_chart_history(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert len(rows) == 1
    assert rows[0]["element_number"] == "eHistory.08"
    assert rows[0]["element_name"] == "Medical/Surgical History"
    assert rows[0]["value"] == "I10"
    assert rows[0]["occurrence_id"] == r1["id"]


@pytest.mark.asyncio
async def test_projection_current_meds_grouped(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-meds")
    med = await ChartHistoryCurrentMedicationService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=CurrentMedicationPayload(
            drug_code="RXN-1",
            dose_value="10",
            dose_unit_code="mg",
            route_code="PO",
            frequency_code="BID",
        ),
        user_id="u",
    )
    rows = await project_chart_history(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    # All five medication-related elements should project for this row
    elements = {r["element_number"] for r in rows}
    assert {
        "eHistory.12",
        "eHistory.13",
        "eHistory.14",
        "eHistory.15",
        "eHistory.20",
    } == elements
    for r in rows:
        assert r["group_path"] == _CURRENT_MED_GROUP
        assert r["occurrence_id"] == med["id"]


@pytest.mark.asyncio
async def test_projection_meds_skips_none_fields(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-meds-min")
    await ChartHistoryCurrentMedicationService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=CurrentMedicationPayload(drug_code="RXN-min"),
        user_id="u",
    )
    rows = await project_chart_history(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    elements = {r["element_number"] for r in rows}
    assert elements == {"eHistory.12"}


@pytest.mark.asyncio
async def test_projection_immunizations(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-imm")
    imm = await ChartHistoryImmunizationService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ImmunizationPayload(
            immunization_type_code="COVID19",
            immunization_year=2024,
        ),
        user_id="u",
    )
    rows = await project_chart_history(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    by_elem = {r["element_number"]: r for r in rows}
    assert by_elem["eHistory.10"]["value"] == "COVID19"
    assert by_elem["eHistory.10"]["occurrence_id"] == imm["id"]
    assert by_elem["eHistory.11"]["value"] == "2024"
    assert by_elem["eHistory.11"]["occurrence_id"] == imm["id"]


@pytest.mark.asyncio
async def test_projection_idempotent(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-idem")
    await ChartHistorySurgicalService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=SurgicalPayload(condition_code="I10"),
        user_id="u",
    )
    rows1 = await project_chart_history(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    rows2 = await project_chart_history(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert len(rows1) == 1 == len(rows2)
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
async def test_projection_element_names_match_dictionary() -> None:
    """NEMSIS element names must match v3.5.1 data dictionary verbatim."""
    name_for_element: dict[str, str] = {}
    for _col, elem, name in _META_SCALAR_BINDING:
        name_for_element[elem] = name
    for _col, elem, name in _META_LIST_BINDING:
        name_for_element[elem] = name
    for _col, elem, name in _MEDICATION_BINDING:
        name_for_element[elem] = name
    for kind, (elem, name, _gp) in _ALLERGY_KIND_BINDING.items():
        name_for_element[elem] = name

    assert name_for_element["eHistory.01"] == "Barriers to Care"
    assert name_for_element["eHistory.02"] == "Practitioner Last Name"
    assert name_for_element["eHistory.05"] == "Advance Directives"
    assert name_for_element["eHistory.06"] == "Medication Allergies"
    assert name_for_element["eHistory.07"] == "Environmental/Food Allergies"
    assert name_for_element["eHistory.09"] == "Medical History Obtained From"
    assert name_for_element["eHistory.12"] == "Current Medications"
    assert name_for_element["eHistory.13"] == "Current Medication Dose"
    assert name_for_element["eHistory.14"] == "Current Medication Dosage Units"
    assert name_for_element["eHistory.15"] == "Current Medication Administration Route"
    assert name_for_element["eHistory.17"] == "Alcohol/Drug Use Indicators"
    assert name_for_element["eHistory.20"] == (
        "Current Medication Administered Frequency"
    )
