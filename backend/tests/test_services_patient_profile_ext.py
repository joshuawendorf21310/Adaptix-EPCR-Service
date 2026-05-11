"""Service tests for the NEMSIS ePatient extension services."""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart
from epcr_app.models_patient_profile_ext import (  # noqa: F401 - register tables
    PatientHomeAddress,
    PatientLanguage,
    PatientPhoneNumber,
    PatientProfileNemsisExt,
    PatientRace,
)
from epcr_app.services_patient_profile_ext import (
    PatientHomeAddressPayload,
    PatientHomeAddressService,
    PatientLanguagePayload,
    PatientLanguageService,
    PatientPhoneNumberPayload,
    PatientPhoneNumberService,
    PatientProfileExtError,
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


# ---------------------------------------------------------------------------
# Scalar ext
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ext_upsert_creates_then_reads(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-1")
    payload = PatientProfileExtPayload(
        ems_patient_id="EMS-1",
        sex_nemsis_code="9906001",
        name_suffix="JR",
    )
    result = await PatientProfileExtService.upsert(
        session, tenant_id="t-1", chart_id=chart.id, payload=payload, user_id="u"
    )
    assert result["ems_patient_id"] == "EMS-1"
    assert result["sex_nemsis_code"] == "9906001"
    assert result["chart_id"] == chart.id

    fetched = await PatientProfileExtService.get(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert fetched is not None
    assert fetched["name_suffix"] == "JR"


@pytest.mark.asyncio
async def test_ext_partial_update_preserves_existing(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-2")
    await PatientProfileExtService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=PatientProfileExtPayload(
            ems_patient_id="EMS-1", sex_nemsis_code="9906001"
        ),
        user_id="u",
    )
    await PatientProfileExtService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=PatientProfileExtPayload(email_address="p@example.com"),
        user_id="u",
    )
    fetched = await PatientProfileExtService.get(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert fetched["ems_patient_id"] == "EMS-1"
    assert fetched["sex_nemsis_code"] == "9906001"
    assert fetched["email_address"] == "p@example.com"


@pytest.mark.asyncio
async def test_ext_tenant_isolation(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-A", "C-A")
    await PatientProfileExtService.upsert(
        session,
        tenant_id="t-A",
        chart_id=chart.id,
        payload=PatientProfileExtPayload(ems_patient_id="X"),
        user_id="u",
    )
    leaked = await PatientProfileExtService.get(
        session, tenant_id="t-B", chart_id=chart.id
    )
    assert leaked is None


@pytest.mark.asyncio
async def test_ext_requires_ids(session: AsyncSession) -> None:
    with pytest.raises(PatientProfileExtError):
        await PatientProfileExtService.upsert(
            session,
            tenant_id="",
            chart_id="x",
            payload=PatientProfileExtPayload(),
        )
    with pytest.raises(PatientProfileExtError):
        await PatientProfileExtService.upsert(
            session,
            tenant_id="t",
            chart_id="",
            payload=PatientProfileExtPayload(),
        )


# ---------------------------------------------------------------------------
# Home address
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_home_address_upsert_creates_and_partial_update(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-1", "C-3")
    await PatientHomeAddressService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=PatientHomeAddressPayload(
            home_street_address="123 Main St",
            home_city="Anytown",
            home_state="WA",
        ),
        user_id="u",
    )
    await PatientHomeAddressService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=PatientHomeAddressPayload(home_zip="98101"),
        user_id="u",
    )
    fetched = await PatientHomeAddressService.get(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert fetched["home_street_address"] == "123 Main St"
    assert fetched["home_state"] == "WA"
    assert fetched["home_zip"] == "98101"


# ---------------------------------------------------------------------------
# Races 1:M
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_race_add_and_list(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-r")
    await PatientRaceService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=PatientRacePayload(race_code="2106-3", sequence_index=0),
        user_id="u",
    )
    await PatientRaceService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=PatientRacePayload(race_code="2054-5", sequence_index=1),
        user_id="u",
    )
    rows = await PatientRaceService.list_for_chart(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert [r["race_code"] for r in rows] == ["2106-3", "2054-5"]


@pytest.mark.asyncio
async def test_race_duplicate_rejected(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-r2")
    await PatientRaceService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=PatientRacePayload(race_code="2106-3"),
        user_id="u",
    )
    with pytest.raises(PatientProfileExtError) as exc:
        await PatientRaceService.add(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            payload=PatientRacePayload(race_code="2106-3"),
            user_id="u",
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_race_soft_delete(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-r3")
    created = await PatientRaceService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=PatientRacePayload(race_code="2106-3"),
        user_id="u",
    )
    deleted = await PatientRaceService.soft_delete(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        row_id=created["id"],
        user_id="u",
    )
    assert deleted["deleted_at"] is not None
    rows = await PatientRaceService.list_for_chart(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert rows == []


@pytest.mark.asyncio
async def test_race_soft_deleted_can_be_re_added(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-r4")
    created = await PatientRaceService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=PatientRacePayload(race_code="2106-3"),
        user_id="u",
    )
    await PatientRaceService.soft_delete(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        row_id=created["id"],
        user_id="u",
    )
    re_added = await PatientRaceService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=PatientRacePayload(race_code="2106-3"),
        user_id="u",
    )
    assert re_added["deleted_at"] is None
    assert re_added["race_code"] == "2106-3"


# ---------------------------------------------------------------------------
# Languages 1:M
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_language_add_list_delete(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-l")
    await PatientLanguageService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=PatientLanguagePayload(language_code="eng"),
        user_id="u",
    )
    second = await PatientLanguageService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=PatientLanguagePayload(language_code="spa", sequence_index=1),
        user_id="u",
    )
    rows = await PatientLanguageService.list_for_chart(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert {r["language_code"] for r in rows} == {"eng", "spa"}

    await PatientLanguageService.soft_delete(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        row_id=second["id"],
        user_id="u",
    )
    rows = await PatientLanguageService.list_for_chart(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert {r["language_code"] for r in rows} == {"eng"}


# ---------------------------------------------------------------------------
# Phones 1:M
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_phone_add_with_type_and_list(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-p")
    await PatientPhoneNumberService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=PatientPhoneNumberPayload(
            phone_number="555-0100", phone_type_code="9913003"
        ),
        user_id="u",
    )
    await PatientPhoneNumberService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=PatientPhoneNumberPayload(
            phone_number="555-0101", phone_type_code="9913005", sequence_index=1
        ),
        user_id="u",
    )
    rows = await PatientPhoneNumberService.list_for_chart(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert {r["phone_number"] for r in rows} == {"555-0100", "555-0101"}
    by_phone = {r["phone_number"]: r for r in rows}
    assert by_phone["555-0100"]["phone_type_code"] == "9913003"
    assert by_phone["555-0101"]["phone_type_code"] == "9913005"


@pytest.mark.asyncio
async def test_phone_duplicate_rejected(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-p2")
    await PatientPhoneNumberService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=PatientPhoneNumberPayload(phone_number="555-0100"),
        user_id="u",
    )
    with pytest.raises(PatientProfileExtError) as exc:
        await PatientPhoneNumberService.add(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            payload=PatientPhoneNumberPayload(phone_number="555-0100"),
            user_id="u",
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_soft_delete_unknown_id_404(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-x")
    with pytest.raises(PatientProfileExtError) as exc:
        await PatientRaceService.soft_delete(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            row_id=str(uuid.uuid4()),
            user_id="u",
        )
    assert exc.value.status_code == 404
