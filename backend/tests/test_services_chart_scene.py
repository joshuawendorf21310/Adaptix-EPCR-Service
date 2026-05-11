"""Service tests for :class:`ChartSceneService` and
:class:`ChartSceneOtherAgencyService`.

Covers upsert, partial-update semantics, get, clear_field, list/add/
soft_delete on the 1:M group, tenant isolation, and error contracts.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart
from epcr_app.models_chart_scene import (  # noqa: F401 - registers tables
    ChartScene,
    ChartSceneOtherAgency,
)
from epcr_app.services_chart_scene import (
    ChartSceneError,
    ChartSceneOtherAgencyPayload,
    ChartSceneOtherAgencyService,
    ChartScenePayload,
    ChartSceneService,
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
# 1:1 ChartSceneService
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_creates_then_reads(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-1")
    payload = ChartScenePayload(
        first_ems_unit_indicator_code="Yes",
        incident_location_type_code="2204001",
        incident_street_address="100 Main",
        incident_city="Boise",
        incident_state="ID",
        incident_zip="83702",
        number_of_patients=2,
    )
    result = await ChartSceneService.upsert(
        session, tenant_id="t-1", chart_id=chart.id, payload=payload, user_id="user-1"
    )
    assert result["first_ems_unit_indicator_code"] == "Yes"
    assert result["incident_city"] == "Boise"
    assert result["number_of_patients"] == 2
    # eScene.22 defaults to "US" on first insert when not supplied.
    assert result["incident_country"] == "US"

    fetched = await ChartSceneService.get(session, tenant_id="t-1", chart_id=chart.id)
    assert fetched is not None
    assert fetched["incident_state"] == "ID"


@pytest.mark.asyncio
async def test_partial_update_preserves_existing(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-2")
    await ChartSceneService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartScenePayload(
            first_ems_unit_indicator_code="Yes",
            incident_city="Boise",
            incident_state="ID",
        ),
        user_id="user-1",
    )
    # second upsert only changes city; first_ems and state must remain
    await ChartSceneService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartScenePayload(incident_city="Meridian"),
        user_id="user-2",
    )

    fetched = await ChartSceneService.get(session, tenant_id="t-1", chart_id=chart.id)
    assert fetched["first_ems_unit_indicator_code"] == "Yes"
    assert fetched["incident_city"] == "Meridian"
    assert fetched["incident_state"] == "ID"


@pytest.mark.asyncio
async def test_clear_field_sets_null(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-3")
    await ChartSceneService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartScenePayload(incident_apartment="Apt 4B"),
        user_id="user-1",
    )
    cleared = await ChartSceneService.clear_field(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        field="incident_apartment",
        user_id="user-1",
    )
    assert cleared["incident_apartment"] is None


@pytest.mark.asyncio
async def test_clear_field_unknown_raises(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-4")
    await ChartSceneService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartScenePayload(),
        user_id="user-1",
    )
    with pytest.raises(ChartSceneError) as exc:
        await ChartSceneService.clear_field(
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
    await ChartSceneService.upsert(
        session,
        tenant_id="t-A",
        chart_id=chart.id,
        payload=ChartScenePayload(incident_city="Boise"),
        user_id="user-1",
    )
    leaked = await ChartSceneService.get(session, tenant_id="t-B", chart_id=chart.id)
    assert leaked is None


@pytest.mark.asyncio
async def test_get_returns_none_when_absent(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-empty")
    result = await ChartSceneService.get(session, tenant_id="t-1", chart_id=chart.id)
    assert result is None


@pytest.mark.asyncio
async def test_upsert_requires_tenant_and_chart(session: AsyncSession) -> None:
    with pytest.raises(ChartSceneError):
        await ChartSceneService.upsert(
            session,
            tenant_id="",
            chart_id="x",
            payload=ChartScenePayload(),
            user_id=None,
        )
    with pytest.raises(ChartSceneError):
        await ChartSceneService.upsert(
            session,
            tenant_id="t",
            chart_id="",
            payload=ChartScenePayload(),
            user_id=None,
        )


@pytest.mark.asyncio
async def test_upsert_preserves_datetime_isoformat(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-dt")
    arrived = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
    result = await ChartSceneService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartScenePayload(initial_responder_arrived_at=arrived),
        user_id="u",
    )
    assert result["initial_responder_arrived_at"].startswith("2026-05-10T12:00:00")


# ---------------------------------------------------------------------------
# 1:M ChartSceneOtherAgencyService
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_other_agency_add_and_list(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-OA1")
    await ChartSceneOtherAgencyService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartSceneOtherAgencyPayload(
            agency_id="AG-1",
            other_service_type_code="2208001",
            sequence_index=0,
        ),
        user_id="u",
    )
    await ChartSceneOtherAgencyService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartSceneOtherAgencyPayload(
            agency_id="AG-2",
            other_service_type_code="2208003",
            first_to_provide_patient_care_indicator="Yes",
            sequence_index=1,
        ),
        user_id="u",
    )

    rows = await ChartSceneOtherAgencyService.list_for_chart(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert len(rows) == 2
    assert [r["agency_id"] for r in rows] == ["AG-1", "AG-2"]
    assert rows[1]["first_to_provide_patient_care_indicator"] == "Yes"


@pytest.mark.asyncio
async def test_other_agency_duplicate_rejected(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-OA2")
    await ChartSceneOtherAgencyService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartSceneOtherAgencyPayload(
            agency_id="AG-DUP",
            other_service_type_code="2208001",
        ),
        user_id="u",
    )
    with pytest.raises(ChartSceneError) as exc:
        await ChartSceneOtherAgencyService.add(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            payload=ChartSceneOtherAgencyPayload(
                agency_id="AG-DUP",
                other_service_type_code="2208002",
            ),
            user_id="u",
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_other_agency_add_requires_fields(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-OA3")
    with pytest.raises(ChartSceneError):
        await ChartSceneOtherAgencyService.add(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            payload=ChartSceneOtherAgencyPayload(
                agency_id="", other_service_type_code="2208001"
            ),
            user_id="u",
        )
    with pytest.raises(ChartSceneError):
        await ChartSceneOtherAgencyService.add(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            payload=ChartSceneOtherAgencyPayload(
                agency_id="AG-1", other_service_type_code=""
            ),
            user_id="u",
        )


@pytest.mark.asyncio
async def test_other_agency_soft_delete(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-OA4")
    created = await ChartSceneOtherAgencyService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartSceneOtherAgencyPayload(
            agency_id="AG-X", other_service_type_code="2208001"
        ),
        user_id="u",
    )
    deleted = await ChartSceneOtherAgencyService.soft_delete(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        row_id=created["id"],
        user_id="u",
    )
    assert deleted["deleted_at"] is not None

    remaining = await ChartSceneOtherAgencyService.list_for_chart(
        session, tenant_id="t-1", chart_id=chart.id
    )
    assert remaining == []


@pytest.mark.asyncio
async def test_other_agency_soft_delete_404_on_missing(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-OA5")
    with pytest.raises(ChartSceneError) as exc:
        await ChartSceneOtherAgencyService.soft_delete(
            session,
            tenant_id="t-1",
            chart_id=chart.id,
            row_id="does-not-exist",
            user_id="u",
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_other_agency_tenant_scoping(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-A", "C-OA6")
    await ChartSceneOtherAgencyService.add(
        session,
        tenant_id="t-A",
        chart_id=chart.id,
        payload=ChartSceneOtherAgencyPayload(
            agency_id="AG-1", other_service_type_code="2208001"
        ),
        user_id="u",
    )
    rows_other = await ChartSceneOtherAgencyService.list_for_chart(
        session, tenant_id="t-B", chart_id=chart.id
    )
    assert rows_other == []


@pytest.mark.asyncio
async def test_other_agency_re_add_after_soft_delete_reuses_row(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-1", "C-OA7")
    first = await ChartSceneOtherAgencyService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartSceneOtherAgencyPayload(
            agency_id="AG-RE", other_service_type_code="2208001"
        ),
        user_id="u",
    )
    await ChartSceneOtherAgencyService.soft_delete(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        row_id=first["id"],
        user_id="u",
    )
    revived = await ChartSceneOtherAgencyService.add(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartSceneOtherAgencyPayload(
            agency_id="AG-RE", other_service_type_code="2208002"
        ),
        user_id="u",
    )
    assert revived["id"] == first["id"]
    assert revived["deleted_at"] is None
    assert revived["other_service_type_code"] == "2208002"
