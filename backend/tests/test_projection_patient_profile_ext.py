"""Projection tests: ePatient extension aggregates -> NemsisFieldValue ledger."""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart
from epcr_app.models_nemsis_field_values import NemsisFieldValue
from epcr_app.models_patient_profile_ext import (  # noqa: F401 - register tables
    PatientHomeAddress,
    PatientLanguage,
    PatientPhoneNumber,
    PatientProfileNemsisExt,
    PatientRace,
)
from epcr_app.projection_patient_profile_ext import (
    HOME_ADDRESS_GROUP,
    LANGUAGE_ELEMENT_NUMBER,
    PHONE_ELEMENT_NUMBER,
    RACE_ELEMENT_NUMBER,
    SECTION,
    _ADDRESS_BINDING,
    _SCALAR_BINDING,
    project_patient_profile_ext,
)
from epcr_app.services_patient_profile_ext import (
    PatientHomeAddressPayload,
    PatientHomeAddressService,
    PatientLanguagePayload,
    PatientLanguageService,
    PatientPhoneNumberPayload,
    PatientPhoneNumberService,
    PatientProfileExtPayload,
    PatientProfileExtService,
    PatientRacePayload,
    PatientRaceService,
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
    await PatientProfileExtService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=PatientProfileExtPayload(
            ems_patient_id="EMS-1",
            sex_nemsis_code="9906001",
            name_suffix="JR",
        ),
        user_id="u",
    )
    rows = await project_patient_profile_ext(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    by_element = {(r["element_number"], r["group_path"]): r for r in rows}
    assert ("ePatient.01", "") in by_element
    assert by_element[("ePatient.01", "")]["value"] == "EMS-1"
    assert ("ePatient.25", "") in by_element
    assert by_element[("ePatient.25", "")]["value"] == "9906001"
    assert ("ePatient.23", "") in by_element
    assert by_element[("ePatient.23", "")]["value"] == "JR"
    for r in rows:
        assert r["section"] == SECTION


@pytest.mark.asyncio
async def test_projection_emits_home_address_with_group_path(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-1", "C-2")
    await PatientHomeAddressService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=PatientHomeAddressPayload(
            home_street_address="123 Main St",
            home_city="Anytown",
            home_state="WA",
            home_zip="98101",
        ),
        user_id="u",
    )
    rows = await project_patient_profile_ext(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    addr_rows = [r for r in rows if r["group_path"] == HOME_ADDRESS_GROUP]
    assert len(addr_rows) == 4
    by_elem = {r["element_number"]: r for r in addr_rows}
    assert by_elem["ePatient.05"]["value"] == "123 Main St"
    assert by_elem["ePatient.06"]["value"] == "Anytown"
    assert by_elem["ePatient.08"]["value"] == "WA"
    assert by_elem["ePatient.09"]["value"] == "98101"


@pytest.mark.asyncio
async def test_projection_emits_race_rows_with_occurrence_id(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-1", "C-3")
    r1 = await PatientRaceService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=PatientRacePayload(race_code="2106-3", sequence_index=0),
        user_id="u",
    )
    r2 = await PatientRaceService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=PatientRacePayload(race_code="2054-5", sequence_index=1),
        user_id="u",
    )
    rows = await project_patient_profile_ext(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    race_rows = [r for r in rows if r["element_number"] == RACE_ELEMENT_NUMBER]
    assert len(race_rows) == 2
    by_occ = {r["occurrence_id"]: r for r in race_rows}
    assert by_occ[r1["id"]]["value"] == "2106-3"
    assert by_occ[r1["id"]]["sequence_index"] == 0
    assert by_occ[r2["id"]]["value"] == "2054-5"
    assert by_occ[r2["id"]]["sequence_index"] == 1


@pytest.mark.asyncio
async def test_projection_emits_language_rows(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-4")
    l1 = await PatientLanguageService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=PatientLanguagePayload(language_code="eng", sequence_index=0),
        user_id="u",
    )
    rows = await project_patient_profile_ext(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    lang_rows = [r for r in rows if r["element_number"] == LANGUAGE_ELEMENT_NUMBER]
    assert len(lang_rows) == 1
    assert lang_rows[0]["value"] == "eng"
    assert lang_rows[0]["occurrence_id"] == l1["id"]


@pytest.mark.asyncio
async def test_projection_emits_phone_rows_with_type_attribute(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-1", "C-5")
    p_with_type = await PatientPhoneNumberService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=PatientPhoneNumberPayload(
            phone_number="555-0100", phone_type_code="9913003"
        ),
        user_id="u",
    )
    p_without_type = await PatientPhoneNumberService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=PatientPhoneNumberPayload(phone_number="555-0101"),
        user_id="u",
    )
    rows = await project_patient_profile_ext(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    phone_rows = [r for r in rows if r["element_number"] == PHONE_ELEMENT_NUMBER]
    assert len(phone_rows) == 2
    by_occ = {r["occurrence_id"]: r for r in phone_rows}
    assert by_occ[p_with_type["id"]]["attributes"] == {"type": "9913003"}
    # phone without type should have no type attribute
    assert "type" not in (by_occ[p_without_type["id"]]["attributes"] or {})


@pytest.mark.asyncio
async def test_projection_skips_none_columns(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-6")
    await PatientProfileExtService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=PatientProfileExtPayload(ems_patient_id="EMS-X"),
        user_id="u",
    )
    rows = await project_patient_profile_ext(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    scalar_rows = [r for r in rows if r["group_path"] == ""]
    elements = {r["element_number"] for r in scalar_rows}
    assert "ePatient.01" in elements
    # other scalar elements not set should NOT be emitted
    assert "ePatient.25" not in elements
    assert "ePatient.23" not in elements


@pytest.mark.asyncio
async def test_projection_returns_empty_when_nothing_recorded(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-1", "C-empty")
    rows = await project_patient_profile_ext(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert rows == []


@pytest.mark.asyncio
async def test_projection_is_idempotent(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-idem")
    await PatientProfileExtService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=PatientProfileExtPayload(ems_patient_id="EMS-IDEM"),
        user_id="u",
    )
    await PatientRaceService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=PatientRacePayload(race_code="2106-3"),
        user_id="u",
    )
    rows1 = await project_patient_profile_ext(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    rows2 = await project_patient_profile_ext(
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
    # Same number of distinct (element_number, group_path, occurrence_id) tuples.
    assert len(ledger) == len(rows1)


@pytest.mark.asyncio
async def test_projection_binding_uses_nemsis_canonical_names() -> None:
    scalar_names = {elem: name for _col, elem, name in _SCALAR_BINDING}
    assert scalar_names["ePatient.01"] == "EMS Patient ID"
    assert scalar_names["ePatient.25"] == "Sex"
    assert scalar_names["ePatient.23"] == "Name Suffix"
    addr_names = {elem: name for _col, elem, name in _ADDRESS_BINDING}
    assert addr_names["ePatient.05"] == "Patient's Home Address"
    assert addr_names["ePatient.06"] == "Patient's Home City"
    assert addr_names["ePatient.07"] == "Patient's Home County"
    assert addr_names["ePatient.08"] == "Patient's Home State"
    assert addr_names["ePatient.09"] == "Patient's Home ZIP Code"
