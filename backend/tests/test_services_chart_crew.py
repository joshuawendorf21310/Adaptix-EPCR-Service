"""Service tests for :class:`ChartCrewService`.

Covers add, list, update, soft-delete, tenant isolation, error
contracts, and duplicate rejection.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart
from epcr_app.models_chart_crew import ChartCrewMember  # noqa: F401 - registers table
from epcr_app.services_chart_crew import (
    ChartCrewError,
    ChartCrewPayload,
    ChartCrewService,
    ChartCrewUpdate,
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
async def test_add_then_list(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-1")
    record = await ChartCrewService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartCrewPayload(
            crew_member_id="EMP-1",
            crew_member_level_code="Paramedic",
            crew_member_response_role_code="lead",
            sequence_index=0,
        ),
        user_id="user-1",
    )
    assert record["crew_member_id"] == "EMP-1"
    assert record["chart_id"] == chart.id

    listed = await ChartCrewService.list_for_chart(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert len(listed) == 1
    assert listed[0]["crew_member_id"] == "EMP-1"


@pytest.mark.asyncio
async def test_list_orders_by_sequence_index(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-seq")
    await ChartCrewService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartCrewPayload(
            crew_member_id="EMP-B",
            crew_member_level_code="EMT",
            crew_member_response_role_code="driver",
            sequence_index=2,
        ),
        user_id="u",
    )
    await ChartCrewService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartCrewPayload(
            crew_member_id="EMP-A",
            crew_member_level_code="Paramedic",
            crew_member_response_role_code="lead",
            sequence_index=0,
        ),
        user_id="u",
    )
    await ChartCrewService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartCrewPayload(
            crew_member_id="EMP-C",
            crew_member_level_code="AEMT",
            crew_member_response_role_code="treat",
            sequence_index=1,
        ),
        user_id="u",
    )
    listed = await ChartCrewService.list_for_chart(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert [r["crew_member_id"] for r in listed] == ["EMP-A", "EMP-C", "EMP-B"]


@pytest.mark.asyncio
async def test_add_duplicate_member_rejected(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-dup")
    await ChartCrewService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartCrewPayload(
            crew_member_id="EMP-X",
            crew_member_level_code="EMT",
            crew_member_response_role_code="driver",
        ),
        user_id="u",
    )
    with pytest.raises(ChartCrewError) as exc:
        await ChartCrewService.add(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            payload=ChartCrewPayload(
                crew_member_id="EMP-X",
                crew_member_level_code="EMT",
                crew_member_response_role_code="treat",
            ),
            user_id="u",
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_update_changes_level_and_role(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-upd")
    record = await ChartCrewService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartCrewPayload(
            crew_member_id="EMP-U",
            crew_member_level_code="EMT",
            crew_member_response_role_code="driver",
            sequence_index=0,
        ),
        user_id="u",
    )
    updated = await ChartCrewService.update(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        row_id=record["id"],
        payload=ChartCrewUpdate(
            crew_member_level_code="Paramedic",
            crew_member_response_role_code="lead",
            sequence_index=3,
        ),
        user_id="u",
    )
    assert updated["crew_member_level_code"] == "Paramedic"
    assert updated["crew_member_response_role_code"] == "lead"
    assert updated["sequence_index"] == 3
    # crew_member_id is immutable on PATCH
    assert updated["crew_member_id"] == "EMP-U"


@pytest.mark.asyncio
async def test_update_partial_preserves_other_fields(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-partial")
    record = await ChartCrewService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartCrewPayload(
            crew_member_id="EMP-P",
            crew_member_level_code="EMT",
            crew_member_response_role_code="driver",
            sequence_index=5,
        ),
        user_id="u",
    )
    updated = await ChartCrewService.update(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        row_id=record["id"],
        payload=ChartCrewUpdate(crew_member_level_code="AEMT"),
        user_id="u",
    )
    assert updated["crew_member_level_code"] == "AEMT"
    assert updated["crew_member_response_role_code"] == "driver"
    assert updated["sequence_index"] == 5


@pytest.mark.asyncio
async def test_soft_delete_hides_from_list(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-del")
    a = await ChartCrewService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartCrewPayload(
            crew_member_id="EMP-A",
            crew_member_level_code="EMT",
            crew_member_response_role_code="driver",
        ),
        user_id="u",
    )
    await ChartCrewService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartCrewPayload(
            crew_member_id="EMP-B",
            crew_member_level_code="Paramedic",
            crew_member_response_role_code="lead",
        ),
        user_id="u",
    )
    await ChartCrewService.soft_delete(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        row_id=a["id"],
        user_id="u",
    )
    listed = await ChartCrewService.list_for_chart(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert len(listed) == 1
    assert listed[0]["crew_member_id"] == "EMP-B"


@pytest.mark.asyncio
async def test_soft_delete_unknown_raises_404(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-404")
    with pytest.raises(ChartCrewError) as exc:
        await ChartCrewService.soft_delete(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            row_id="does-not-exist",
            user_id="u",
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_unknown_raises_404(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-upd-404")
    with pytest.raises(ChartCrewError) as exc:
        await ChartCrewService.update(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            row_id="does-not-exist",
            payload=ChartCrewUpdate(crew_member_level_code="EMT"),
            user_id="u",
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_tenant_scoping_returns_empty_for_wrong_tenant(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-A", "C-A")
    await ChartCrewService.add(
        session,
        tenant_id="t-A",
        chart_id=chart.id,
        payload=ChartCrewPayload(
            crew_member_id="EMP-A",
            crew_member_level_code="EMT",
            crew_member_response_role_code="driver",
        ),
        user_id="u",
    )
    leaked = await ChartCrewService.list_for_chart(
        session, tenant_id="t-B", chart_id=chart.id
    )
    assert leaked == []


@pytest.mark.asyncio
async def test_add_requires_mandatory_fields(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-req")
    with pytest.raises(ChartCrewError):
        await ChartCrewService.add(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            payload=ChartCrewPayload(
                crew_member_id="",
                crew_member_level_code="EMT",
                crew_member_response_role_code="driver",
            ),
            user_id="u",
        )
    with pytest.raises(ChartCrewError):
        await ChartCrewService.add(
            session,
            tenant_id="",
            chart_id=chart.id,
            payload=ChartCrewPayload(
                crew_member_id="EMP-A",
                crew_member_level_code="EMT",
                crew_member_response_role_code="driver",
            ),
            user_id="u",
        )
