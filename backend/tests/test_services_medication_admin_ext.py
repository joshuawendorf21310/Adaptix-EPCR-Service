"""Service tests for :class:`MedicationAdminExtService`.

Covers upsert, partial-update semantics, get with complications,
add/delete complication, tenant isolation, and error contracts.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart, MedicationAdministration
from epcr_app.models_medication_admin_ext import (  # noqa: F401 - registers tables
    MedicationAdminExt,
    MedicationComplication,
)
from epcr_app.services_medication_admin_ext import (
    MedicationAdminExtError,
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
async def test_upsert_creates_then_reads(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-1")
    med = await _seed_med(session, tenant_id="t-1", chart_id=chart.id)
    payload = MedicationAdminExtPayload(
        prior_to_ems_indicator_code="9923001",
        ems_professional_type_code="9924007",
    )
    result = await MedicationAdminExtService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        medication_admin_id=med.id,
        payload=payload,
        user_id="user-1",
    )
    assert result["prior_to_ems_indicator_code"] == "9923001"
    assert result["ems_professional_type_code"] == "9924007"
    assert result["medication_admin_id"] == med.id

    fetched = await MedicationAdminExtService.get(
        session, tenant_id="t-1", chart_id=chart.id, medication_admin_id=med.id
    )
    assert fetched is not None
    assert fetched["ext"]["prior_to_ems_indicator_code"] == "9923001"
    assert fetched["complications"] == []


@pytest.mark.asyncio
async def test_partial_update_preserves_existing(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-2")
    med = await _seed_med(session, tenant_id="t-1", chart_id=chart.id)

    await MedicationAdminExtService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        medication_admin_id=med.id,
        payload=MedicationAdminExtPayload(
            prior_to_ems_indicator_code="9923001",
            ems_professional_type_code="9924007",
        ),
        user_id="user-1",
    )
    # Second upsert only sets authorization_code; others must remain.
    await MedicationAdminExtService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        medication_admin_id=med.id,
        payload=MedicationAdminExtPayload(authorization_code="9908001"),
        user_id="user-2",
    )

    fetched = await MedicationAdminExtService.get(
        session, tenant_id="t-1", chart_id=chart.id, medication_admin_id=med.id
    )
    assert fetched["ext"]["prior_to_ems_indicator_code"] == "9923001"
    assert fetched["ext"]["ems_professional_type_code"] == "9924007"
    assert fetched["ext"]["authorization_code"] == "9908001"


@pytest.mark.asyncio
async def test_add_then_delete_complication(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-3")
    med = await _seed_med(session, tenant_id="t-1", chart_id=chart.id)

    added = await MedicationAdminExtService.add_complication(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        medication_admin_id=med.id,
        payload=MedicationComplicationPayload(
            complication_code="9925003", sequence_index=0
        ),
        user_id="user-1",
    )
    assert added["complication_code"] == "9925003"

    fetched = await MedicationAdminExtService.get(
        session, tenant_id="t-1", chart_id=chart.id, medication_admin_id=med.id
    )
    assert len(fetched["complications"]) == 1

    removed = await MedicationAdminExtService.delete_complication(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        medication_admin_id=med.id,
        complication_id=added["id"],
        user_id="user-1",
    )
    assert removed is True

    fetched_after = await MedicationAdminExtService.get(
        session, tenant_id="t-1", chart_id=chart.id, medication_admin_id=med.id
    )
    # ext-only record (no complications) may still exist as None when
    # we never wrote ext. Service returns None if neither ext nor
    # complications exist.
    assert fetched_after is None or fetched_after["complications"] == []


@pytest.mark.asyncio
async def test_add_complication_idempotent_on_same_code(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-4")
    med = await _seed_med(session, tenant_id="t-1", chart_id=chart.id)

    a = await MedicationAdminExtService.add_complication(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        medication_admin_id=med.id,
        payload=MedicationComplicationPayload(
            complication_code="9925003", sequence_index=0
        ),
        user_id="user-1",
    )
    b = await MedicationAdminExtService.add_complication(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        medication_admin_id=med.id,
        payload=MedicationComplicationPayload(
            complication_code="9925003", sequence_index=1
        ),
        user_id="user-1",
    )
    assert a["id"] == b["id"]
    assert b["sequence_index"] == 1


@pytest.mark.asyncio
async def test_add_complication_requires_code(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-5")
    med = await _seed_med(session, tenant_id="t-1", chart_id=chart.id)
    with pytest.raises(MedicationAdminExtError) as exc:
        await MedicationAdminExtService.add_complication(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            medication_admin_id=med.id,
            payload=MedicationComplicationPayload(complication_code=""),
            user_id="user-1",
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_tenant_scoping_returns_none_for_wrong_tenant(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-A", "C-A")
    med = await _seed_med(session, tenant_id="t-A", chart_id=chart.id)
    await MedicationAdminExtService.upsert(
        session,
        tenant_id="t-A",
        chart_id=chart.id,
        medication_admin_id=med.id,
        payload=MedicationAdminExtPayload(ems_professional_type_code="9924007"),
        user_id="user-1",
    )
    leaked = await MedicationAdminExtService.get(
        session, tenant_id="t-B", chart_id=chart.id, medication_admin_id=med.id
    )
    assert leaked is None


@pytest.mark.asyncio
async def test_get_returns_none_when_absent(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-empty")
    med = await _seed_med(session, tenant_id="t-1", chart_id=chart.id)
    result = await MedicationAdminExtService.get(
        session, tenant_id="t-1", chart_id=chart.id, medication_admin_id=med.id
    )
    assert result is None


@pytest.mark.asyncio
async def test_upsert_requires_tenant_and_chart_and_med(session: AsyncSession) -> None:
    with pytest.raises(MedicationAdminExtError):
        await MedicationAdminExtService.upsert(
            session,
            tenant_id="",
            chart_id="x",
            medication_admin_id="m",
            payload=MedicationAdminExtPayload(),
            user_id=None,
        )
    with pytest.raises(MedicationAdminExtError):
        await MedicationAdminExtService.upsert(
            session,
            tenant_id="t",
            chart_id="",
            medication_admin_id="m",
            payload=MedicationAdminExtPayload(),
            user_id=None,
        )
    with pytest.raises(MedicationAdminExtError):
        await MedicationAdminExtService.upsert(
            session,
            tenant_id="t",
            chart_id="c",
            medication_admin_id="",
            payload=MedicationAdminExtPayload(),
            user_id=None,
        )
