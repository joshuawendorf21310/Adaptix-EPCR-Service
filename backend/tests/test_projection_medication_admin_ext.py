"""Projection tests: eMedications-additions -> NemsisFieldValue ledger.

Verifies that populated NEMSIS-additive scalars produce one ledger row
per eMedications.NN with canonical element_number / element_name, that
None columns are NOT projected (preserving NEMSIS absence semantics),
that eMedications.12 is emitted as a structured-name row with
lastName/firstName attributes, and that eMedications.08 complications
produce one ledger row per code with distinct occurrence_ids.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart, MedicationAdministration
from epcr_app.models_medication_admin_ext import (  # noqa: F401
    MedicationAdminExt,
    MedicationComplication,
)
from epcr_app.models_nemsis_field_values import NemsisFieldValue
from epcr_app.projection_medication_admin_ext import (
    GROUP_MED,
    GROUP_PHYSICIAN,
    SECTION,
    _SCALAR_BINDING,
    project_medication_admin_ext,
)
from epcr_app.services_medication_admin_ext import (
    MedicationAdminExtPayload,
    MedicationAdminExtService,
    MedicationComplicationPayload,
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


async def _seed_med(
    session: AsyncSession, *, tenant_id: str, chart_id: str
) -> MedicationAdministration:
    med = MedicationAdministration(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        chart_id=chart_id,
        medication_name="Epinephrine",
        route="IV",
        indication="Cardiac arrest",
        administered_at=datetime.now(UTC),
        administered_by_user_id="user-1",
    )
    session.add(med)
    await session.flush()
    return med


@pytest.mark.asyncio
async def test_projection_emits_one_row_per_scalar(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-1")
    med = await _seed_med(session, tenant_id="t-1", chart_id=chart.id)
    await MedicationAdminExtService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        medication_admin_id=med.id,
        payload=MedicationAdminExtPayload(
            prior_to_ems_indicator_code="9923001",
            ems_professional_type_code="9924007",
            authorization_code="9908001",
            by_another_unit_indicator_code="9923003",
        ),
        user_id="u",
    )

    rows = await project_medication_admin_ext(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        medication_admin_id=med.id,
        user_id="u",
    )
    elements = {r["element_number"] for r in rows}
    assert {"eMedications.02", "eMedications.10", "eMedications.11", "eMedications.13"} <= elements
    for r in rows:
        assert r["section"] == SECTION
        assert r["group_path"] == GROUP_MED
        assert r["occurrence_id"] == med.id


@pytest.mark.asyncio
async def test_projection_emits_structured_physician_name(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-2")
    med = await _seed_med(session, tenant_id="t-1", chart_id=chart.id)
    await MedicationAdminExtService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        medication_admin_id=med.id,
        payload=MedicationAdminExtPayload(
            authorizing_physician_last_name="Strange",
            authorizing_physician_first_name="Stephen",
        ),
        user_id="u",
    )
    rows = await project_medication_admin_ext(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        medication_admin_id=med.id,
        user_id="u",
    )
    phys = [r for r in rows if r["element_number"] == "eMedications.12"]
    assert len(phys) == 1
    row = phys[0]
    assert row["group_path"] == GROUP_PHYSICIAN
    assert row["occurrence_id"] == med.id
    assert row["value"] == "Strange, Stephen"
    assert row["attributes"]["lastName"] == "Strange"
    assert row["attributes"]["firstName"] == "Stephen"


@pytest.mark.asyncio
async def test_projection_emits_complications_with_distinct_occurrences(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-3")
    med = await _seed_med(session, tenant_id="t-1", chart_id=chart.id)
    for idx, code in enumerate(["9925003", "9925005"]):
        await MedicationAdminExtService.add_complication(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            medication_admin_id=med.id,
            payload=MedicationComplicationPayload(
                complication_code=code, sequence_index=idx
            ),
            user_id="u",
        )

    rows = await project_medication_admin_ext(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        medication_admin_id=med.id,
        user_id="u",
    )
    comp_rows = [r for r in rows if r["element_number"] == "eMedications.08"]
    assert len(comp_rows) == 2
    occ_ids = {r["occurrence_id"] for r in comp_rows}
    assert occ_ids == {f"{med.id}-comp-0", f"{med.id}-comp-1"}
    values = {r["value"] for r in comp_rows}
    assert values == {"9925003", "9925005"}


@pytest.mark.asyncio
async def test_projection_skips_none_columns(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-4")
    med = await _seed_med(session, tenant_id="t-1", chart_id=chart.id)
    await MedicationAdminExtService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        medication_admin_id=med.id,
        payload=MedicationAdminExtPayload(ems_professional_type_code="9924007"),
        user_id="u",
    )
    rows = await project_medication_admin_ext(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        medication_admin_id=med.id,
        user_id="u",
    )
    assert len(rows) == 1
    assert rows[0]["element_number"] == "eMedications.10"


@pytest.mark.asyncio
async def test_projection_is_idempotent(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-5")
    med = await _seed_med(session, tenant_id="t-1", chart_id=chart.id)
    await MedicationAdminExtService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        medication_admin_id=med.id,
        payload=MedicationAdminExtPayload(ems_professional_type_code="9924007"),
        user_id="u",
    )
    rows1 = await project_medication_admin_ext(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        medication_admin_id=med.id,
        user_id="u",
    )
    rows2 = await project_medication_admin_ext(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        medication_admin_id=med.id,
        user_id="u",
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
async def test_projection_returns_empty_when_no_row(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-empty")
    med = await _seed_med(session, tenant_id="t-1", chart_id=chart.id)
    rows = await project_medication_admin_ext(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        medication_admin_id=med.id,
        user_id="u",
    )
    assert rows == []


@pytest.mark.asyncio
async def test_projection_element_names_match_dictionary() -> None:
    name_for_element = {elem: name for _col, elem, name in _SCALAR_BINDING}
    assert (
        name_for_element["eMedications.02"]
        == "Medication Administered Prior to this Unit's EMS Care Indicator"
    )
    assert name_for_element["eMedications.10"] == "EMS Professional Type Providing Medication"
    assert name_for_element["eMedications.11"] == "Medication Authorization"
    assert (
        name_for_element["eMedications.13"]
        == "Medication Administered by Another Unit Indicator"
    )
