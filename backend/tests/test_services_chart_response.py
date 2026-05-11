"""Service tests for :class:`ChartResponseService`.

Covers upsert (with create + partial-update semantics), get, list/add/
delete delay rows, tenant isolation, kind validation, duplicate
rejection, and error contracts.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart
from epcr_app.models_chart_response import (  # noqa: F401 - registers tables
    ChartResponse,
    ChartResponseDelay,
)
from epcr_app.services_chart_response import (
    ChartResponseDelayPayload,
    ChartResponseError,
    ChartResponsePayload,
    ChartResponseService,
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


# ---- Metadata (1:1) tests ----


@pytest.mark.asyncio
async def test_upsert_creates_then_reads(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-1")
    payload = ChartResponsePayload(
        agency_number="A123",
        agency_name="Adaptix EMS",
        type_of_service_requested_code="2205001",
        unit_transport_capability_code="2208005",
        unit_vehicle_number="MEDIC-7",
        unit_call_sign="M7",
        response_mode_to_scene_code="2235003",
        additional_response_descriptors_json=["X1", "X2"],
    )
    result = await ChartResponseService.upsert(
        session, tenant_id="t-1", chart_id=chart.id, payload=payload, user_id="user-1"
    )
    assert result["agency_number"] == "A123"
    assert result["unit_call_sign"] == "M7"
    assert result["additional_response_descriptors_json"] == ["X1", "X2"]

    fetched = await ChartResponseService.get(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert fetched is not None
    assert fetched["agency_name"] == "Adaptix EMS"


@pytest.mark.asyncio
async def test_partial_update_preserves_existing(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-2")
    await ChartResponseService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartResponsePayload(
            agency_number="A123",
            unit_call_sign="M7",
        ),
        user_id="user-1",
    )
    # Second upsert only changes response_mode_to_scene_code.
    await ChartResponseService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartResponsePayload(response_mode_to_scene_code="2235003"),
        user_id="user-2",
    )

    fetched = await ChartResponseService.get(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert fetched["agency_number"] == "A123"
    assert fetched["unit_call_sign"] == "M7"
    assert fetched["response_mode_to_scene_code"] == "2235003"


@pytest.mark.asyncio
async def test_partial_update_can_clear_descriptors_list(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-3")
    await ChartResponseService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartResponsePayload(
            agency_number="A123",
            additional_response_descriptors_json=["X1", "X2"],
        ),
        user_id="u",
    )
    await ChartResponseService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartResponsePayload(additional_response_descriptors_json=[]),
        user_id="u",
    )
    fetched = await ChartResponseService.get(
        session, tenant_id="t-1", chart_id=chart.id
    )
    # Empty list -> cleared. None would have meant "no change".
    assert fetched["additional_response_descriptors_json"] == []
    # Other fields still intact.
    assert fetched["agency_number"] == "A123"


@pytest.mark.asyncio
async def test_get_returns_none_when_absent(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-empty")
    result = await ChartResponseService.get(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert result is None


@pytest.mark.asyncio
async def test_tenant_scoping_returns_none_for_wrong_tenant(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-A", "C-A")
    await ChartResponseService.upsert(
        session,
        tenant_id="t-A",
        chart_id=chart.id,
        payload=ChartResponsePayload(agency_number="A1"),
        user_id="u",
    )
    leaked = await ChartResponseService.get(
        session, tenant_id="t-B", chart_id=chart.id
    )
    assert leaked is None


@pytest.mark.asyncio
async def test_upsert_requires_tenant_and_chart(session: AsyncSession) -> None:
    with pytest.raises(ChartResponseError):
        await ChartResponseService.upsert(
            session,
            tenant_id="",
            chart_id="x",
            payload=ChartResponsePayload(),
            user_id=None,
        )
    with pytest.raises(ChartResponseError):
        await ChartResponseService.upsert(
            session,
            tenant_id="t",
            chart_id="",
            payload=ChartResponsePayload(),
            user_id=None,
        )


# ---- Delay (1:M) tests ----


@pytest.mark.asyncio
async def test_add_and_list_delays(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-D-1")
    await ChartResponseService.add_delay(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartResponseDelayPayload(delay_kind="dispatch", delay_code="D1"),
        user_id="u",
    )
    await ChartResponseService.add_delay(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartResponseDelayPayload(delay_kind="scene", delay_code="S1"),
        user_id="u",
    )
    rows = await ChartResponseService.list_delays(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert len(rows) == 2
    kinds = {r["delay_kind"] for r in rows}
    assert kinds == {"dispatch", "scene"}


@pytest.mark.asyncio
async def test_add_delay_rejects_unknown_kind(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-D-2")
    with pytest.raises(ChartResponseError) as exc:
        await ChartResponseService.add_delay(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            payload=ChartResponseDelayPayload(
                delay_kind="not_a_real_kind", delay_code="X"
            ),
            user_id="u",
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_add_delay_rejects_duplicate_kind_code(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-D-3")
    await ChartResponseService.add_delay(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartResponseDelayPayload(delay_kind="response", delay_code="R1"),
        user_id="u",
    )
    with pytest.raises(ChartResponseError) as exc:
        await ChartResponseService.add_delay(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            payload=ChartResponseDelayPayload(delay_kind="response", delay_code="R1"),
            user_id="u",
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_delete_delay_soft_deletes(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-D-4")
    added = await ChartResponseService.add_delay(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartResponseDelayPayload(delay_kind="transport", delay_code="T1"),
        user_id="u",
    )
    deleted = await ChartResponseService.delete_delay(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        delay_id=added["id"],
        user_id="u",
    )
    assert deleted["deleted_at"] is not None

    visible = await ChartResponseService.list_delays(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert visible == []
    all_rows = await ChartResponseService.list_delays(
        session, tenant_id="t-1", chart_id=chart.id, include_deleted=True
    )
    assert len(all_rows) == 1


@pytest.mark.asyncio
async def test_delete_delay_not_found(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-D-5")
    with pytest.raises(ChartResponseError) as exc:
        await ChartResponseService.delete_delay(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            delay_id="not-a-real-id",
            user_id="u",
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_add_delay_reuses_soft_deleted_row(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-D-6")
    first = await ChartResponseService.add_delay(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartResponseDelayPayload(delay_kind="turn_around", delay_code="TA1"),
        user_id="u",
    )
    await ChartResponseService.delete_delay(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        delay_id=first["id"],
        user_id="u",
    )
    revived = await ChartResponseService.add_delay(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartResponseDelayPayload(delay_kind="turn_around", delay_code="TA1"),
        user_id="u",
    )
    assert revived["id"] == first["id"]
    assert revived["deleted_at"] is None


@pytest.mark.asyncio
async def test_list_delays_tenant_scoped(session: AsyncSession) -> None:
    chart_a = await _seed_chart(session, "t-A", "C-A")
    chart_b = await _seed_chart(session, "t-B", "C-B")
    await ChartResponseService.add_delay(
        session,
        tenant_id="t-A",
        chart_id=chart_a.id,
        payload=ChartResponseDelayPayload(delay_kind="dispatch", delay_code="D"),
        user_id="u",
    )
    await ChartResponseService.add_delay(
        session,
        tenant_id="t-B",
        chart_id=chart_b.id,
        payload=ChartResponseDelayPayload(delay_kind="dispatch", delay_code="D"),
        user_id="u",
    )
    a_rows = await ChartResponseService.list_delays(
        session, tenant_id="t-A", chart_id=chart_a.id
    )
    cross = await ChartResponseService.list_delays(
        session, tenant_id="t-A", chart_id=chart_b.id
    )
    assert len(a_rows) == 1
    assert cross == []
