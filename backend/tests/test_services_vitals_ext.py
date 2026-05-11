"""Service tests for :class:`VitalsExtService`.

Covers upsert ext, partial-update semantics, get (with children),
add/list/delete for GCS qualifiers, add/list/delete for reperfusion
checklist, tenant isolation, and error contracts.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart, Vitals
from epcr_app.models_vitals_ext import (  # noqa: F401 - registers tables
    VitalsGcsQualifier,
    VitalsNemsisExt,
    VitalsReperfusionChecklist,
)
from epcr_app.services_vitals_ext import (
    VitalsExtError,
    VitalsExtPayload,
    VitalsExtService,
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


async def _seed_chart_vitals(
    session: AsyncSession,
    tenant_id: str,
    call_number: str,
) -> tuple[Chart, Vitals]:
    chart = Chart(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        call_number=call_number,
        created_by_user_id="user-1",
    )
    session.add(chart)
    await session.flush()
    vitals = Vitals(
        id=str(uuid.uuid4()),
        chart_id=chart.id,
        tenant_id=tenant_id,
        recorded_at=datetime.now(UTC),
    )
    session.add(vitals)
    await session.flush()
    return chart, vitals


@pytest.mark.asyncio
async def test_upsert_ext_creates_then_get_reads(session: AsyncSession) -> None:
    chart, vitals = await _seed_chart_vitals(session, "t-1", "C-1")
    result = await VitalsExtService.upsert_ext(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        vitals_id=vitals.id,
        payload=VitalsExtPayload(
            gcs_eye_code="3518003",
            gcs_verbal_code="3519005",
            gcs_motor_code="3520006",
            gcs_total=14,
            etco2=35,
            avpu_code="3523001",
        ),
        user_id="user-1",
    )
    assert result["chart_id"] == chart.id
    assert result["vitals_id"] == vitals.id
    assert result["gcs_total"] == 14

    fetched = await VitalsExtService.get(
        session, tenant_id="t-1", chart_id=chart.id, vitals_id=vitals.id
    )
    assert fetched is not None
    assert fetched["ext"]["etco2"] == 35
    assert fetched["gcs_qualifiers"] == []
    assert fetched["reperfusion_checklist"] == []


@pytest.mark.asyncio
async def test_partial_update_preserves_existing(session: AsyncSession) -> None:
    chart, vitals = await _seed_chart_vitals(session, "t-1", "C-2")
    await VitalsExtService.upsert_ext(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        vitals_id=vitals.id,
        payload=VitalsExtPayload(etco2=35, pain_score=4),
        user_id="user-1",
    )
    await VitalsExtService.upsert_ext(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        vitals_id=vitals.id,
        payload=VitalsExtPayload(stroke_scale_score=2),
        user_id="user-2",
    )

    fetched = await VitalsExtService.get(
        session, tenant_id="t-1", chart_id=chart.id, vitals_id=vitals.id
    )
    assert fetched["ext"]["etco2"] == 35
    assert fetched["ext"]["pain_score"] == 4
    assert fetched["ext"]["stroke_scale_score"] == 2


@pytest.mark.asyncio
async def test_gcs_qualifier_add_list_delete(session: AsyncSession) -> None:
    chart, vitals = await _seed_chart_vitals(session, "t-1", "C-3")
    row1 = await VitalsExtService.add_gcs_qualifier(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        vitals_id=vitals.id,
        qualifier_code="3521001",
        sequence_index=0,
        user_id="u",
    )
    await VitalsExtService.add_gcs_qualifier(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        vitals_id=vitals.id,
        qualifier_code="3521003",
        sequence_index=1,
        user_id="u",
    )
    listed = await VitalsExtService.list_gcs_qualifiers(
        session, tenant_id="t-1", chart_id=chart.id, vitals_id=vitals.id
    )
    assert len(listed) == 2
    assert {r["qualifier_code"] for r in listed} == {"3521001", "3521003"}

    # Re-adding the same code upserts (no second row).
    again = await VitalsExtService.add_gcs_qualifier(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        vitals_id=vitals.id,
        qualifier_code="3521001",
        sequence_index=5,
        user_id="u",
    )
    assert again["id"] == row1["id"]
    assert again["sequence_index"] == 5

    removed = await VitalsExtService.delete_gcs_qualifier(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        vitals_id=vitals.id,
        row_id=row1["id"],
    )
    assert removed is True
    remaining = await VitalsExtService.list_gcs_qualifiers(
        session, tenant_id="t-1", chart_id=chart.id, vitals_id=vitals.id
    )
    assert len(remaining) == 1
    assert remaining[0]["qualifier_code"] == "3521003"


@pytest.mark.asyncio
async def test_reperfusion_add_list_delete(session: AsyncSession) -> None:
    chart, vitals = await _seed_chart_vitals(session, "t-1", "C-4")
    a = await VitalsExtService.add_reperfusion_item(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        vitals_id=vitals.id,
        item_code="3528001",
        sequence_index=0,
        user_id="u",
    )
    await VitalsExtService.add_reperfusion_item(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        vitals_id=vitals.id,
        item_code="3528002",
        sequence_index=1,
        user_id="u",
    )
    listed = await VitalsExtService.list_reperfusion_items(
        session, tenant_id="t-1", chart_id=chart.id, vitals_id=vitals.id
    )
    assert len(listed) == 2

    removed = await VitalsExtService.delete_reperfusion_item(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        vitals_id=vitals.id,
        row_id=a["id"],
    )
    assert removed is True
    remaining = await VitalsExtService.list_reperfusion_items(
        session, tenant_id="t-1", chart_id=chart.id, vitals_id=vitals.id
    )
    assert len(remaining) == 1
    assert remaining[0]["item_code"] == "3528002"


@pytest.mark.asyncio
async def test_tenant_scoping_returns_none_for_wrong_tenant(
    session: AsyncSession,
) -> None:
    chart, vitals = await _seed_chart_vitals(session, "t-A", "C-A")
    await VitalsExtService.upsert_ext(
        session,
        tenant_id="t-A",
        chart_id=chart.id,
        vitals_id=vitals.id,
        payload=VitalsExtPayload(etco2=33),
        user_id="u",
    )
    leaked = await VitalsExtService.get(
        session, tenant_id="t-B", chart_id=chart.id, vitals_id=vitals.id
    )
    assert leaked is None


@pytest.mark.asyncio
async def test_get_returns_none_when_absent(session: AsyncSession) -> None:
    chart, vitals = await _seed_chart_vitals(session, "t-1", "C-empty")
    result = await VitalsExtService.get(
        session, tenant_id="t-1", chart_id=chart.id, vitals_id=vitals.id
    )
    assert result is None


@pytest.mark.asyncio
async def test_upsert_requires_identifiers(session: AsyncSession) -> None:
    with pytest.raises(VitalsExtError):
        await VitalsExtService.upsert_ext(
            session,
            tenant_id="",
            chart_id="x",
            vitals_id="y",
            payload=VitalsExtPayload(),
            user_id=None,
        )
    with pytest.raises(VitalsExtError):
        await VitalsExtService.upsert_ext(
            session,
            tenant_id="t",
            chart_id="",
            vitals_id="y",
            payload=VitalsExtPayload(),
            user_id=None,
        )
    with pytest.raises(VitalsExtError):
        await VitalsExtService.upsert_ext(
            session,
            tenant_id="t",
            chart_id="x",
            vitals_id="",
            payload=VitalsExtPayload(),
            user_id=None,
        )


@pytest.mark.asyncio
async def test_add_gcs_qualifier_rejects_blank(session: AsyncSession) -> None:
    chart, vitals = await _seed_chart_vitals(session, "t-1", "C-bad")
    with pytest.raises(VitalsExtError) as exc:
        await VitalsExtService.add_gcs_qualifier(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            vitals_id=vitals.id,
            qualifier_code="",
            sequence_index=0,
            user_id="u",
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_delete_unknown_returns_false(session: AsyncSession) -> None:
    chart, vitals = await _seed_chart_vitals(session, "t-1", "C-d")
    removed = await VitalsExtService.delete_gcs_qualifier(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        vitals_id=vitals.id,
        row_id=str(uuid.uuid4()),
    )
    assert removed is False
