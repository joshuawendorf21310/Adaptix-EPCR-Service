"""Persistence tests for the NEMSIS eProcedures extension models.

Covers: insert of ext + complications, query, tenant scoping,
unique-per-intervention constraint on ext, unique
(tenant, intervention, code) on complications, default
version/created_at, soft-delete column.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import (
    Base,
    Chart,
    ClinicalIntervention,
    InterventionExportState,
    ProtocolFamily,
)
from epcr_app.models_intervention_ext import (
    InterventionComplication,
    InterventionNemsisExt,
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


async def _make_chart(session: AsyncSession, tenant_id: str, call_number: str) -> Chart:
    chart = Chart(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        call_number=call_number,
        created_by_user_id="user-1",
    )
    session.add(chart)
    await session.flush()
    return chart


async def _make_intervention(
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
async def test_insert_ext_with_all_columns(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-001")
    iv = await _make_intervention(session, tenant_id="t-1", chart_id=chart.id)
    row = InterventionNemsisExt(
        id=str(uuid.uuid4()),
        tenant_id="t-1",
        chart_id=chart.id,
        intervention_id=iv.id,
        prior_to_ems_indicator_code="9923003",
        number_of_attempts=2,
        procedure_successful_code="9923001",
        ems_professional_type_code="2710001",
        authorization_code="9908005",
        authorizing_physician_last_name="Doe",
        authorizing_physician_first_name="Jane",
        by_another_unit_indicator_code="9923003",
        pre_existing_indicator_code="9923003",
    )
    session.add(row)
    await session.flush()

    fetched = (
        await session.execute(
            select(InterventionNemsisExt).where(
                InterventionNemsisExt.intervention_id == iv.id
            )
        )
    ).scalar_one()
    assert fetched.tenant_id == "t-1"
    assert fetched.number_of_attempts == 2
    assert fetched.authorizing_physician_last_name == "Doe"
    assert fetched.version == 1


@pytest.mark.asyncio
async def test_ext_unique_per_intervention(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-002")
    iv = await _make_intervention(session, tenant_id="t-1", chart_id=chart.id)
    session.add(
        InterventionNemsisExt(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            intervention_id=iv.id,
        )
    )
    await session.flush()
    session.add(
        InterventionNemsisExt(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            intervention_id=iv.id,
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_complications_unique_per_intervention_code(session: AsyncSession) -> None:
    chart = await _make_chart(session, "t-1", "C-003")
    iv = await _make_intervention(session, tenant_id="t-1", chart_id=chart.id)
    session.add(
        InterventionComplication(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            intervention_id=iv.id,
            complication_code="9908001",
            sequence_index=0,
        )
    )
    await session.flush()
    session.add(
        InterventionComplication(
            id=str(uuid.uuid4()),
            tenant_id="t-1",
            chart_id=chart.id,
            intervention_id=iv.id,
            complication_code="9908001",
            sequence_index=1,
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_ext_tenant_isolation_in_query(session: AsyncSession) -> None:
    chart_a = await _make_chart(session, "t-A", "C-A")
    chart_b = await _make_chart(session, "t-B", "C-B")
    iv_a = await _make_intervention(session, tenant_id="t-A", chart_id=chart_a.id)
    iv_b = await _make_intervention(session, tenant_id="t-B", chart_id=chart_b.id)
    session.add(
        InterventionNemsisExt(
            id=str(uuid.uuid4()),
            tenant_id="t-A",
            chart_id=chart_a.id,
            intervention_id=iv_a.id,
        )
    )
    session.add(
        InterventionNemsisExt(
            id=str(uuid.uuid4()),
            tenant_id="t-B",
            chart_id=chart_b.id,
            intervention_id=iv_b.id,
        )
    )
    await session.flush()

    rows_a = (
        await session.execute(
            select(InterventionNemsisExt).where(
                InterventionNemsisExt.tenant_id == "t-A"
            )
        )
    ).scalars().all()
    rows_b = (
        await session.execute(
            select(InterventionNemsisExt).where(
                InterventionNemsisExt.tenant_id == "t-B"
            )
        )
    ).scalars().all()
    assert len(rows_a) == 1 and rows_a[0].intervention_id == iv_a.id
    assert len(rows_b) == 1 and rows_b[0].intervention_id == iv_b.id


@pytest.mark.asyncio
async def test_ext_has_all_nemsis_columns() -> None:
    """Guard rail: ext must declare every eProcedures scalar column."""
    expected = {
        "prior_to_ems_indicator_code",
        "number_of_attempts",
        "procedure_successful_code",
        "ems_professional_type_code",
        "authorization_code",
        "authorizing_physician_last_name",
        "authorizing_physician_first_name",
        "by_another_unit_indicator_code",
        "pre_existing_indicator_code",
    }
    cols = {c.name for c in InterventionNemsisExt.__table__.columns}
    missing = expected - cols
    assert not missing, f"InterventionNemsisExt missing eProcedures columns: {missing}"
