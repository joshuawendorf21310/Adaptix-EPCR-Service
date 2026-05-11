"""Service tests for the NEMSIS eSituation services.

Covers 1:1 upsert + partial-update semantics, clear_field, tenant
isolation, error contracts, and the two repeating-group services
(Other Associated Symptoms, Provider's Secondary Impressions).
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart
from epcr_app.models_chart_situation import (  # noqa: F401 - registers table
    ChartSituation,
    ChartSituationOtherSymptom,
    ChartSituationSecondaryImpression,
)
from epcr_app.services_chart_situation import (
    ChartSituationError,
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


# ---------- 1:1 scalar service ----------


@pytest.mark.asyncio
async def test_upsert_creates_then_reads(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-1")
    onset = datetime(2026, 5, 10, 11, 0, 0, tzinfo=UTC)
    payload = ChartSituationPayload(
        symptom_onset_at=onset,
        possible_injury_indicator_code="9922001",
        complaint_type_code="9914001",
        complaint_text="Severe chest pain",
        primary_symptom_code="R07.9",
        provider_primary_impression_code="I21.9",
        initial_patient_acuity_code="2207003",
        work_related_indicator_code="9922001",
    )
    result = await ChartSituationService.upsert(
        session, tenant_id="t-1", chart_id=chart.id, payload=payload, user_id="user-1"
    )
    assert result["complaint_text"] == "Severe chest pain"
    assert result["primary_symptom_code"] == "R07.9"
    assert result["chart_id"] == chart.id

    fetched = await ChartSituationService.get(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert fetched is not None
    assert fetched["provider_primary_impression_code"] == "I21.9"
    assert fetched["symptom_onset_at"].startswith("2026-05-10T11:00:00")


@pytest.mark.asyncio
async def test_partial_update_preserves_existing(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-2")
    await ChartSituationService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartSituationPayload(
            complaint_text="Initial complaint",
            primary_symptom_code="R07.9",
        ),
        user_id="user-1",
    )
    await ChartSituationService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartSituationPayload(initial_patient_acuity_code="2207003"),
        user_id="user-2",
    )

    fetched = await ChartSituationService.get(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert fetched["complaint_text"] == "Initial complaint"
    assert fetched["primary_symptom_code"] == "R07.9"
    assert fetched["initial_patient_acuity_code"] == "2207003"
    assert fetched["version"] == 2


@pytest.mark.asyncio
async def test_clear_field_sets_null(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-3")
    await ChartSituationService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartSituationPayload(complaint_text="text"),
        user_id="user-1",
    )
    cleared = await ChartSituationService.clear_field(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        field="complaint_text",
        user_id="user-1",
    )
    assert cleared["complaint_text"] is None


@pytest.mark.asyncio
async def test_clear_field_unknown_raises(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-4")
    await ChartSituationService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartSituationPayload(),
        user_id="user-1",
    )
    with pytest.raises(ChartSituationError) as exc:
        await ChartSituationService.clear_field(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            field="not_a_real_column",
            user_id="user-1",
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_tenant_scoping_returns_none_for_wrong_tenant(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-A", "C-A")
    await ChartSituationService.upsert(
        session,
        tenant_id="t-A",
        chart_id=chart.id,
        payload=ChartSituationPayload(complaint_text="x"),
        user_id="user-1",
    )
    leaked = await ChartSituationService.get(
        session, tenant_id="t-B", chart_id=chart.id
    )
    assert leaked is None


@pytest.mark.asyncio
async def test_get_returns_none_when_absent(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-empty")
    result = await ChartSituationService.get(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert result is None


@pytest.mark.asyncio
async def test_upsert_requires_tenant_and_chart(session: AsyncSession) -> None:
    with pytest.raises(ChartSituationError):
        await ChartSituationService.upsert(
            session,
            tenant_id="",
            chart_id="x",
            payload=ChartSituationPayload(),
            user_id=None,
        )
    with pytest.raises(ChartSituationError):
        await ChartSituationService.upsert(
            session,
            tenant_id="t",
            chart_id="",
            payload=ChartSituationPayload(),
            user_id=None,
        )


# ---------- eSituation.10 Other Associated Symptoms ----------


@pytest.mark.asyncio
async def test_other_symptom_add_and_list(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-Sym")
    a = await ChartSituationOtherSymptomService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartSituationOtherSymptomPayload(symptom_code="R06.0", sequence_index=0),
        user_id="user-1",
    )
    b = await ChartSituationOtherSymptomService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartSituationOtherSymptomPayload(symptom_code="R51", sequence_index=1),
        user_id="user-1",
    )
    assert a["symptom_code"] == "R06.0"
    assert b["symptom_code"] == "R51"

    rows = await ChartSituationOtherSymptomService.list_for_chart(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert [r["symptom_code"] for r in rows] == ["R06.0", "R51"]


@pytest.mark.asyncio
async def test_other_symptom_duplicate_rejected(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-Dup")
    await ChartSituationOtherSymptomService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartSituationOtherSymptomPayload(symptom_code="R06.0"),
        user_id="user-1",
    )
    with pytest.raises(ChartSituationError) as exc:
        await ChartSituationOtherSymptomService.add(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            payload=ChartSituationOtherSymptomPayload(symptom_code="R06.0"),
            user_id="user-1",
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_other_symptom_soft_delete_then_readd(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-SD")
    created = await ChartSituationOtherSymptomService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartSituationOtherSymptomPayload(symptom_code="R06.0"),
        user_id="user-1",
    )
    await ChartSituationOtherSymptomService.soft_delete(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        row_id=created["id"],
        user_id="user-1",
    )
    rows = await ChartSituationOtherSymptomService.list_for_chart(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert rows == []

    # re-add the same code: should reuse the soft-deleted row
    readded = await ChartSituationOtherSymptomService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartSituationOtherSymptomPayload(symptom_code="R06.0"),
        user_id="user-1",
    )
    assert readded["id"] == created["id"]
    assert readded["deleted_at"] is None


@pytest.mark.asyncio
async def test_other_symptom_tenant_isolation(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-A", "C-T")
    await ChartSituationOtherSymptomService.add(
        session,
        tenant_id="t-A",
        chart_id=chart.id,
        payload=ChartSituationOtherSymptomPayload(symptom_code="R06.0"),
        user_id="user-1",
    )
    leaked = await ChartSituationOtherSymptomService.list_for_chart(
        session, tenant_id="t-B", chart_id=chart.id
    )
    assert leaked == []


# ---------- eSituation.12 Provider's Secondary Impressions ----------


@pytest.mark.asyncio
async def test_secondary_impression_add_and_list(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-Imp")
    await ChartSituationSecondaryImpressionService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartSituationSecondaryImpressionPayload(
            impression_code="I50.9", sequence_index=0
        ),
        user_id="user-1",
    )
    await ChartSituationSecondaryImpressionService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartSituationSecondaryImpressionPayload(
            impression_code="I10", sequence_index=1
        ),
        user_id="user-1",
    )
    rows = await ChartSituationSecondaryImpressionService.list_for_chart(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert [r["impression_code"] for r in rows] == ["I50.9", "I10"]


@pytest.mark.asyncio
async def test_secondary_impression_duplicate_rejected(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-ImpDup")
    await ChartSituationSecondaryImpressionService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartSituationSecondaryImpressionPayload(impression_code="I50.9"),
        user_id="user-1",
    )
    with pytest.raises(ChartSituationError) as exc:
        await ChartSituationSecondaryImpressionService.add(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            payload=ChartSituationSecondaryImpressionPayload(impression_code="I50.9"),
            user_id="user-1",
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_secondary_impression_soft_delete(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-ImpSD")
    created = await ChartSituationSecondaryImpressionService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartSituationSecondaryImpressionPayload(impression_code="I10"),
        user_id="user-1",
    )
    deleted = await ChartSituationSecondaryImpressionService.soft_delete(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        row_id=created["id"],
        user_id="user-1",
    )
    assert deleted["deleted_at"] is not None
    rows = await ChartSituationSecondaryImpressionService.list_for_chart(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert rows == []


@pytest.mark.asyncio
async def test_secondary_impression_soft_delete_not_found(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-NF")
    with pytest.raises(ChartSituationError) as exc:
        await ChartSituationSecondaryImpressionService.soft_delete(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            row_id="nonexistent",
            user_id="user-1",
        )
    assert exc.value.status_code == 404
