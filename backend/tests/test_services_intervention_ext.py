"""Service tests for :class:`InterventionExtService`.

Covers upsert, partial-update semantics, get, complications add/remove,
tenant isolation, and error contracts.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import (
    Base,
    Chart,
    ClinicalIntervention,
    InterventionExportState,
    ProtocolFamily,
)
from epcr_app.models_intervention_ext import (  # noqa: F401 - registers tables
    InterventionComplication,
    InterventionNemsisExt,
)
from epcr_app.services_intervention_ext import (
    InterventionExtError,
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
async def test_upsert_creates_then_reads(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-1")
    iv = await _seed_intervention(session, tenant_id="t-1", chart_id=chart.id)
    payload = InterventionExtPayload(
        prior_to_ems_indicator_code="9923003",
        number_of_attempts=3,
        procedure_successful_code="9923001",
        ems_professional_type_code="2710001",
    )
    result = await InterventionExtService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        intervention_id=iv.id,
        payload=payload,
        user_id="user-1",
    )
    assert result["number_of_attempts"] == 3
    assert result["procedure_successful_code"] == "9923001"
    assert result["intervention_id"] == iv.id

    fetched = await InterventionExtService.get(
        session, tenant_id="t-1", intervention_id=iv.id
    )
    assert fetched is not None
    assert fetched["number_of_attempts"] == 3


@pytest.mark.asyncio
async def test_partial_update_preserves_existing(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-2")
    iv = await _seed_intervention(session, tenant_id="t-1", chart_id=chart.id)

    await InterventionExtService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        intervention_id=iv.id,
        payload=InterventionExtPayload(
            number_of_attempts=1,
            procedure_successful_code="9923001",
        ),
        user_id="user-1",
    )
    # Second upsert only changes attempts; procedure_successful_code must remain
    await InterventionExtService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        intervention_id=iv.id,
        payload=InterventionExtPayload(number_of_attempts=2),
        user_id="user-2",
    )

    fetched = await InterventionExtService.get(
        session, tenant_id="t-1", intervention_id=iv.id
    )
    assert fetched["number_of_attempts"] == 2
    assert fetched["procedure_successful_code"] == "9923001"


@pytest.mark.asyncio
async def test_add_complication_assigns_sequence(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-3")
    iv = await _seed_intervention(session, tenant_id="t-1", chart_id=chart.id)
    a = await InterventionExtService.add_complication(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        intervention_id=iv.id,
        complication_code="9908001",
        user_id="user-1",
    )
    b = await InterventionExtService.add_complication(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        intervention_id=iv.id,
        complication_code="9908002",
        user_id="user-1",
    )
    assert a["sequence_index"] == 0
    assert b["sequence_index"] == 1

    listed = await InterventionExtService.list_complications(
        session, tenant_id="t-1", intervention_id=iv.id
    )
    assert [c["complication_code"] for c in listed] == ["9908001", "9908002"]


@pytest.mark.asyncio
async def test_add_complication_dedupes_by_code(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-4")
    iv = await _seed_intervention(session, tenant_id="t-1", chart_id=chart.id)
    a = await InterventionExtService.add_complication(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        intervention_id=iv.id,
        complication_code="9908001",
        user_id="user-1",
    )
    b = await InterventionExtService.add_complication(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        intervention_id=iv.id,
        complication_code="9908001",
        user_id="user-1",
    )
    assert a["id"] == b["id"]


@pytest.mark.asyncio
async def test_remove_complication_soft_deletes(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-5")
    iv = await _seed_intervention(session, tenant_id="t-1", chart_id=chart.id)
    created = await InterventionExtService.add_complication(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        intervention_id=iv.id,
        complication_code="9908001",
        user_id="user-1",
    )
    removed = await InterventionExtService.remove_complication(
        session,
        tenant_id="t-1",
        intervention_id=iv.id,
        complication_id=created["id"],
        user_id="user-1",
    )
    assert removed["deleted_at"] is not None
    listed = await InterventionExtService.list_complications(
        session, tenant_id="t-1", intervention_id=iv.id
    )
    assert listed == []


@pytest.mark.asyncio
async def test_remove_complication_unknown_raises(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-6")
    iv = await _seed_intervention(session, tenant_id="t-1", chart_id=chart.id)
    with pytest.raises(InterventionExtError) as exc:
        await InterventionExtService.remove_complication(
            session,
            tenant_id="t-1",
            intervention_id=iv.id,
            complication_id="does-not-exist",
            user_id="user-1",
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_tenant_scoping_returns_none_for_wrong_tenant(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-A", "C-A")
    iv = await _seed_intervention(session, tenant_id="t-A", chart_id=chart.id)
    await InterventionExtService.upsert(
        session,
        tenant_id="t-A",
        chart_id=chart.id,
        intervention_id=iv.id,
        payload=InterventionExtPayload(number_of_attempts=1),
        user_id="user-1",
    )
    leaked = await InterventionExtService.get(
        session, tenant_id="t-B", intervention_id=iv.id
    )
    assert leaked is None


@pytest.mark.asyncio
async def test_get_returns_none_when_absent(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-empty")
    iv = await _seed_intervention(session, tenant_id="t-1", chart_id=chart.id)
    result = await InterventionExtService.get(
        session, tenant_id="t-1", intervention_id=iv.id
    )
    assert result is None


@pytest.mark.asyncio
async def test_upsert_requires_tenant_chart_intervention(session: AsyncSession) -> None:
    with pytest.raises(InterventionExtError):
        await InterventionExtService.upsert(
            session,
            tenant_id="",
            chart_id="c",
            intervention_id="i",
            payload=InterventionExtPayload(),
            user_id=None,
        )
    with pytest.raises(InterventionExtError):
        await InterventionExtService.upsert(
            session,
            tenant_id="t",
            chart_id="",
            intervention_id="i",
            payload=InterventionExtPayload(),
            user_id=None,
        )
    with pytest.raises(InterventionExtError):
        await InterventionExtService.upsert(
            session,
            tenant_id="t",
            chart_id="c",
            intervention_id="",
            payload=InterventionExtPayload(),
            user_id=None,
        )
