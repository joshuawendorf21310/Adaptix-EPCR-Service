"""Service tests for eHistory CRUD.

Covers the meta upsert (create, partial update, scalar retention),
each 1:M collection (add, list, soft delete, duplicate rejection,
soft-delete-then-reinsert revives the row), tenant isolation, and
error contracts.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart
from epcr_app.models_chart_history import (  # noqa: F401 - register tables
    ChartHistoryAllergy,
    ChartHistoryCurrentMedication,
    ChartHistoryImmunization,
    ChartHistoryMeta,
    ChartHistorySurgical,
)
from epcr_app.services_chart_history import (
    AllergyPayload,
    ChartHistoryAllergyService,
    ChartHistoryCurrentMedicationService,
    ChartHistoryError,
    ChartHistoryImmunizationService,
    ChartHistoryMetaPayload,
    ChartHistoryMetaService,
    ChartHistoryService,
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


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_meta_upsert_creates_then_reads(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-1")
    result = await ChartHistoryMetaService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartHistoryMetaPayload(
            practitioner_last_name="Smith",
            barriers_to_care_codes_json=["8801001"],
        ),
        user_id="user-1",
    )
    assert result["practitioner_last_name"] == "Smith"
    assert result["barriers_to_care_codes_json"] == ["8801001"]

    fetched = await ChartHistoryMetaService.get(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert fetched is not None
    assert fetched["practitioner_last_name"] == "Smith"


@pytest.mark.asyncio
async def test_meta_partial_update_preserves_existing(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-2")
    await ChartHistoryMetaService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartHistoryMetaPayload(
            practitioner_last_name="Smith",
            practitioner_first_name="Anne",
        ),
        user_id="user-1",
    )
    await ChartHistoryMetaService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartHistoryMetaPayload(pregnancy_code="3535005"),
        user_id="user-2",
    )
    fetched = await ChartHistoryMetaService.get(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert fetched["practitioner_last_name"] == "Smith"
    assert fetched["practitioner_first_name"] == "Anne"
    assert fetched["pregnancy_code"] == "3535005"


@pytest.mark.asyncio
async def test_meta_tenant_scoping(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-A", "C-A")
    await ChartHistoryMetaService.upsert(
        session,
        tenant_id="t-A",
        chart_id=chart.id,
        payload=ChartHistoryMetaPayload(practitioner_last_name="Smith"),
        user_id="u",
    )
    leaked = await ChartHistoryMetaService.get(
        session, tenant_id="t-B", chart_id=chart.id
    )
    assert leaked is None


@pytest.mark.asyncio
async def test_meta_requires_tenant_and_chart(session: AsyncSession) -> None:
    with pytest.raises(ChartHistoryError):
        await ChartHistoryMetaService.upsert(
            session,
            tenant_id="",
            chart_id="x",
            payload=ChartHistoryMetaPayload(),
            user_id=None,
        )
    with pytest.raises(ChartHistoryError):
        await ChartHistoryMetaService.upsert(
            session,
            tenant_id="t",
            chart_id="",
            payload=ChartHistoryMetaPayload(),
            user_id=None,
        )


# ---------------------------------------------------------------------------
# Allergies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_allergy_add_list_delete(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-allergy")
    a1 = await ChartHistoryAllergyService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=AllergyPayload(
            allergy_kind="medication",
            allergy_code="RX-1",
            allergy_text="Penicillin",
        ),
        user_id="u",
    )
    a2 = await ChartHistoryAllergyService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=AllergyPayload(
            allergy_kind="environmental_food",
            allergy_code="ENV-1",
        ),
        user_id="u",
    )
    listed = await ChartHistoryAllergyService.list_for_chart(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert len(listed) == 2
    assert {r["allergy_code"] for r in listed} == {"RX-1", "ENV-1"}

    await ChartHistoryAllergyService.soft_delete(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        row_id=a1["id"],
        user_id="u",
    )
    remaining = await ChartHistoryAllergyService.list_for_chart(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert {r["id"] for r in remaining} == {a2["id"]}


@pytest.mark.asyncio
async def test_allergy_duplicate_rejected(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-dup")
    await ChartHistoryAllergyService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=AllergyPayload(allergy_kind="medication", allergy_code="RX-1"),
        user_id="u",
    )
    with pytest.raises(ChartHistoryError) as exc:
        await ChartHistoryAllergyService.add(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            payload=AllergyPayload(allergy_kind="medication", allergy_code="RX-1"),
            user_id="u",
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_allergy_rejects_invalid_kind(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-kind")
    with pytest.raises(ChartHistoryError) as exc:
        await ChartHistoryAllergyService.add(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            payload=AllergyPayload(allergy_kind="not_a_kind", allergy_code="X"),
            user_id="u",
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_allergy_soft_delete_then_readd_revives(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-rev")
    row = await ChartHistoryAllergyService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=AllergyPayload(allergy_kind="medication", allergy_code="RX-1"),
        user_id="u",
    )
    await ChartHistoryAllergyService.soft_delete(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        row_id=row["id"],
        user_id="u",
    )
    revived = await ChartHistoryAllergyService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=AllergyPayload(
            allergy_kind="medication",
            allergy_code="RX-1",
            allergy_text="Penicillin",
        ),
        user_id="u",
    )
    assert revived["id"] == row["id"]
    assert revived["allergy_text"] == "Penicillin"
    assert revived["deleted_at"] is None


# ---------------------------------------------------------------------------
# Surgical
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_surgical_add_and_unique(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-surg")
    r1 = await ChartHistorySurgicalService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=SurgicalPayload(condition_code="I10"),
        user_id="u",
    )
    assert r1["condition_code"] == "I10"
    with pytest.raises(ChartHistoryError) as exc:
        await ChartHistorySurgicalService.add(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            payload=SurgicalPayload(condition_code="I10"),
            user_id="u",
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_surgical_soft_delete(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-surgdel")
    r1 = await ChartHistorySurgicalService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=SurgicalPayload(condition_code="I10"),
        user_id="u",
    )
    await ChartHistorySurgicalService.soft_delete(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        row_id=r1["id"],
        user_id="u",
    )
    remaining = await ChartHistorySurgicalService.list_for_chart(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert remaining == []


# ---------------------------------------------------------------------------
# Current medications
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_medication_add_with_all_fields(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-meds")
    row = await ChartHistoryCurrentMedicationService.add(
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
    assert row["dose_value"] == "10"
    assert row["frequency_code"] == "BID"


@pytest.mark.asyncio
async def test_medication_duplicate_rejected(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-med-dup")
    await ChartHistoryCurrentMedicationService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=CurrentMedicationPayload(drug_code="RXN-1"),
        user_id="u",
    )
    with pytest.raises(ChartHistoryError) as exc:
        await ChartHistoryCurrentMedicationService.add(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            payload=CurrentMedicationPayload(drug_code="RXN-1"),
            user_id="u",
        )
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# Immunizations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_immunization_add_multiple_same_code_allowed(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-1", "C-imm")
    await ChartHistoryImmunizationService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ImmunizationPayload(
            immunization_type_code="COVID19",
            immunization_year=2021,
            sequence_index=0,
        ),
        user_id="u",
    )
    await ChartHistoryImmunizationService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ImmunizationPayload(
            immunization_type_code="COVID19",
            immunization_year=2023,
            sequence_index=1,
        ),
        user_id="u",
    )
    listed = await ChartHistoryImmunizationService.list_for_chart(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert len(listed) == 2


@pytest.mark.asyncio
async def test_immunization_requires_type_code(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-imm-req")
    with pytest.raises(ChartHistoryError) as exc:
        await ChartHistoryImmunizationService.add(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            payload=ImmunizationPayload(immunization_type_code=""),
            user_id="u",
        )
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# Composite
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_composite_read_returns_all_collections(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-comp")
    await ChartHistoryMetaService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartHistoryMetaPayload(practitioner_last_name="X"),
        user_id="u",
    )
    await ChartHistoryAllergyService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=AllergyPayload(allergy_kind="medication", allergy_code="RX-1"),
        user_id="u",
    )
    await ChartHistorySurgicalService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=SurgicalPayload(condition_code="I10"),
        user_id="u",
    )
    await ChartHistoryCurrentMedicationService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=CurrentMedicationPayload(drug_code="RXN-1"),
        user_id="u",
    )
    await ChartHistoryImmunizationService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ImmunizationPayload(
            immunization_type_code="COVID19", immunization_year=2024
        ),
        user_id="u",
    )
    composite = await ChartHistoryService.get_composite(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert composite["meta"]["practitioner_last_name"] == "X"
    assert len(composite["allergies"]) == 1
    assert len(composite["surgical"]) == 1
    assert len(composite["current_medications"]) == 1
    assert len(composite["immunizations"]) == 1


@pytest.mark.asyncio
async def test_meta_last_oral_intake_roundtrip(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-loi")
    t0 = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
    await ChartHistoryMetaService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartHistoryMetaPayload(last_oral_intake_at=t0),
        user_id="u",
    )
    fetched = await ChartHistoryMetaService.get(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert fetched["last_oral_intake_at"].startswith("2026-05-10T12:00:00")
