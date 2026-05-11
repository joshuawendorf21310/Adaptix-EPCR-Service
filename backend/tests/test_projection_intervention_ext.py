"""Projection tests: intervention ext + complications -> NemsisFieldValue ledger.

Verifies that populated scalar columns produce one ledger row per
eProcedures.NN with the canonical element_number / element_name, the
authorizing physician composite emits as eProcedures.12 in its dedicated
group, and complications emit as eProcedures.07 occurrences with derived
occurrence_id and sequence_index.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import (
    Base,
    Chart,
    ClinicalIntervention,
    InterventionExportState,
    ProtocolFamily,
)
from epcr_app.models_intervention_ext import (  # noqa: F401
    InterventionComplication,
    InterventionNemsisExt,
)
from epcr_app.models_nemsis_field_values import NemsisFieldValue
from epcr_app.projection_intervention_ext import (
    PHYSICIAN_GROUP_PATH,
    PROCEDURE_GROUP_PATH,
    SECTION,
    _ELEMENT_BINDING,
    project_intervention_ext,
)
from epcr_app.services_intervention_ext import (
    InterventionExtPayload,
    InterventionExtService,
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


async def _seed_intervention(
    session: AsyncSession, *, tenant_id: str, chart_id: str
) -> ClinicalIntervention:
    now = datetime.now(UTC)
    iv = ClinicalIntervention(
        id=str(uuid.uuid4()),
        chart_id=chart_id,
        tenant_id=tenant_id,
        category="airway",
        name="endotracheal intubation",
        indication="respiratory failure",
        intent="secure airway",
        expected_response="adequate ventilation",
        protocol_family=ProtocolFamily.GENERAL,
        export_state=InterventionExportState.PENDING_MAPPING,
        performed_at=now,
        updated_at=now,
        provider_id="provider-1",
    )
    session.add(iv)
    await session.flush()
    return iv


@pytest.mark.asyncio
async def test_projection_emits_scalars(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-1")
    iv = await _seed_intervention(session, tenant_id="t-1", chart_id=chart.id)
    await InterventionExtService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        intervention_id=iv.id,
        payload=InterventionExtPayload(
            prior_to_ems_indicator_code="9923003",
            number_of_attempts=2,
            procedure_successful_code="9923001",
            ems_professional_type_code="2710001",
        ),
        user_id="u",
    )
    rows = await project_intervention_ext(
        session, tenant_id="t-1", chart_id=chart.id, intervention_id=iv.id, user_id="u"
    )
    by_element = {r["element_number"]: r for r in rows}
    assert "eProcedures.02" in by_element
    assert by_element["eProcedures.02"]["value"] == "9923003"
    assert by_element["eProcedures.05"]["value"] == 2
    assert by_element["eProcedures.06"]["value"] == "9923001"
    assert by_element["eProcedures.10"]["value"] == "2710001"
    for row in rows:
        assert row["section"] == SECTION
        assert row["group_path"] == PROCEDURE_GROUP_PATH
        assert row["occurrence_id"] == iv.id


@pytest.mark.asyncio
async def test_projection_physician_composite(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-2")
    iv = await _seed_intervention(session, tenant_id="t-1", chart_id=chart.id)
    await InterventionExtService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        intervention_id=iv.id,
        payload=InterventionExtPayload(
            authorizing_physician_last_name="Doe",
            authorizing_physician_first_name="Jane",
        ),
        user_id="u",
    )
    rows = await project_intervention_ext(
        session, tenant_id="t-1", chart_id=chart.id, intervention_id=iv.id, user_id="u"
    )
    e12 = [r for r in rows if r["element_number"] == "eProcedures.12"]
    assert len(e12) == 1
    assert e12[0]["group_path"] == PHYSICIAN_GROUP_PATH
    assert e12[0]["attributes"]["lastName"] == "Doe"
    assert e12[0]["attributes"]["firstName"] == "Jane"
    assert e12[0]["value"] == "Doe, Jane"


@pytest.mark.asyncio
async def test_projection_complications(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-3")
    iv = await _seed_intervention(session, tenant_id="t-1", chart_id=chart.id)
    await InterventionExtService.add_complication(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        intervention_id=iv.id,
        complication_code="9908001",
        user_id="u",
    )
    await InterventionExtService.add_complication(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        intervention_id=iv.id,
        complication_code="9908002",
        user_id="u",
    )
    rows = await project_intervention_ext(
        session, tenant_id="t-1", chart_id=chart.id, intervention_id=iv.id, user_id="u"
    )
    comps = [r for r in rows if r["element_number"] == "eProcedures.07"]
    assert len(comps) == 2
    occ_ids = {r["occurrence_id"] for r in comps}
    assert occ_ids == {f"{iv.id}-comp-0", f"{iv.id}-comp-1"}
    values = {r["value"] for r in comps}
    assert values == {"9908001", "9908002"}


@pytest.mark.asyncio
async def test_projection_skips_none_columns(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-4")
    iv = await _seed_intervention(session, tenant_id="t-1", chart_id=chart.id)
    await InterventionExtService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        intervention_id=iv.id,
        payload=InterventionExtPayload(number_of_attempts=1),
        user_id="u",
    )
    rows = await project_intervention_ext(
        session, tenant_id="t-1", chart_id=chart.id, intervention_id=iv.id, user_id="u"
    )
    assert len(rows) == 1
    assert rows[0]["element_number"] == "eProcedures.05"


@pytest.mark.asyncio
async def test_projection_is_idempotent(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-5")
    iv = await _seed_intervention(session, tenant_id="t-1", chart_id=chart.id)
    await InterventionExtService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        intervention_id=iv.id,
        payload=InterventionExtPayload(procedure_successful_code="9923001"),
        user_id="u",
    )
    r1 = await project_intervention_ext(
        session, tenant_id="t-1", chart_id=chart.id, intervention_id=iv.id, user_id="u"
    )
    r2 = await project_intervention_ext(
        session, tenant_id="t-1", chart_id=chart.id, intervention_id=iv.id, user_id="u"
    )
    assert len(r1) == 1 == len(r2)
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
async def test_projection_returns_empty_when_no_data(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-empty")
    iv = await _seed_intervention(session, tenant_id="t-1", chart_id=chart.id)
    rows = await project_intervention_ext(
        session, tenant_id="t-1", chart_id=chart.id, intervention_id=iv.id, user_id="u"
    )
    assert rows == []


@pytest.mark.asyncio
async def test_projection_element_names_match_dictionary() -> None:
    """The NEMSIS element names in the binding must match v3.5.1 data dictionary."""
    name_for_element = {elem: name for _col, elem, name in _ELEMENT_BINDING}
    assert name_for_element["eProcedures.02"] == "Prior to EMS Care Indicator"
    assert name_for_element["eProcedures.05"] == "Number of Procedure Attempts"
    assert name_for_element["eProcedures.06"] == "Procedure Successful"
    assert name_for_element["eProcedures.10"] == (
        "Type of EMS Professional Performing Procedure"
    )
    assert name_for_element["eProcedures.11"] == "Authorization for Procedure"
    assert name_for_element["eProcedures.13"] == (
        "Procedure Performed Prior to this Unit's EMS Care"
    )
    assert name_for_element["eProcedures.14"] == "Pre-Existing Procedure"
