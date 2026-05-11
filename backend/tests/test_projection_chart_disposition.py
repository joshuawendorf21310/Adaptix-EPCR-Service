"""Projection tests: :class:`ChartDisposition` -> NemsisFieldValue ledger.

Verifies that populated scalar columns produce one ledger row per
eDisposition.NN with the canonical element_number / element_name, that
None / empty-list columns are NOT projected, and that 1:M JSON list
columns expand into one ledger row per list entry with a unique
occurrence_id and sequence_index.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart
from epcr_app.models_chart_disposition import ChartDisposition  # noqa: F401
from epcr_app.models_nemsis_field_values import NemsisFieldValue
from epcr_app.projection_chart_disposition import (
    SECTION,
    _ELEMENT_BINDING,
    _LIST_BINDING,
    _SCALAR_BINDING,
    project_chart_disposition,
)
from epcr_app.services_chart_disposition import (
    ChartDispositionPayload,
    ChartDispositionService,
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
async def test_projection_emits_one_row_per_populated_scalar(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-1", "C-1")
    await ChartDispositionService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartDispositionPayload(
            destination_name="St. Example",
            destination_city="Springfield",
            destination_state="IL",
            incident_patient_disposition_code="4212001",
            transport_disposition_code="4227005",
            level_of_care_provided_code="4218015",
        ),
        user_id="u",
    )

    rows = await project_chart_disposition(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert len(rows) == 6

    by_element = {r["element_number"]: r for r in rows}
    assert set(by_element.keys()) == {
        "eDisposition.01",
        "eDisposition.04",
        "eDisposition.06",
        "eDisposition.12",
        "eDisposition.16",
        "eDisposition.18",
    }
    for row in rows:
        assert row["section"] == SECTION
        assert row["value"] is not None
        # Scalar rows use empty occurrence_id
        assert row["occurrence_id"] == ""


@pytest.mark.asyncio
async def test_projection_skips_none_columns(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-2")
    await ChartDispositionService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartDispositionPayload(
            incident_patient_disposition_code="4212001"
        ),
        user_id="u",
    )
    rows = await project_chart_disposition(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert len(rows) == 1
    assert rows[0]["element_number"] == "eDisposition.12"


@pytest.mark.asyncio
async def test_projection_expands_json_lists(session: AsyncSession) -> None:
    """One ledger row per JSON list entry; occurrence_id is unique per entry."""
    chart = await _seed_chart(session, "t-1", "C-list")
    await ChartDispositionService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartDispositionPayload(
            hospital_capability_codes_json=["4209007", "4209013", "4209019"],
            crew_disposition_codes_json=["4234007"],
        ),
        user_id="u",
    )
    rows = await project_chart_disposition(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    # 3 (hospital_capability) + 1 (crew_disposition)
    assert len(rows) == 4

    cap_rows = [r for r in rows if r["element_number"] == "eDisposition.09"]
    crew_rows = [r for r in rows if r["element_number"] == "eDisposition.27"]
    assert len(cap_rows) == 3
    assert len(crew_rows) == 1

    # Unique occurrence_id per list entry
    occ_ids = {r["occurrence_id"] for r in cap_rows}
    assert len(occ_ids) == 3
    # sequence_index matches list index
    seq = sorted(r["sequence_index"] for r in cap_rows)
    assert seq == [0, 1, 2]
    # values preserved in list order
    cap_by_seq = {r["sequence_index"]: r["value"] for r in cap_rows}
    assert cap_by_seq == {0: "4209007", 1: "4209013", 2: "4209019"}


@pytest.mark.asyncio
async def test_projection_skips_empty_lists(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-empty-list")
    await ChartDispositionService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartDispositionPayload(
            incident_patient_disposition_code="4212001",
            hospital_capability_codes_json=[],
        ),
        user_id="u",
    )
    rows = await project_chart_disposition(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert len(rows) == 1
    assert rows[0]["element_number"] == "eDisposition.12"


@pytest.mark.asyncio
async def test_projection_is_idempotent_upserting_same_element(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-1", "C-3")
    await ChartDispositionService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartDispositionPayload(
            transport_disposition_code="4227005",
            hospital_capability_codes_json=["4209007", "4209013"],
        ),
        user_id="u",
    )
    rows1 = await project_chart_disposition(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    rows2 = await project_chart_disposition(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert len(rows1) == len(rows2) == 3

    ledger = (
        await session.execute(
            select(NemsisFieldValue).where(
                NemsisFieldValue.chart_id == chart.id,
                NemsisFieldValue.section == SECTION,
            )
        )
    ).scalars().all()
    # Same upsert keys -> no duplicate rows.
    assert len(ledger) == 3


@pytest.mark.asyncio
async def test_projection_returns_empty_when_no_row(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-empty")
    rows = await project_chart_disposition(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert rows == []


@pytest.mark.asyncio
async def test_projection_binding_covers_every_column() -> None:
    """The binding tables must cover every column on the model."""
    model_cols = {
        c.name
        for c in __import__(
            "epcr_app.models_chart_disposition", fromlist=["ChartDisposition"]
        ).ChartDisposition.__table__.columns
        if c.name
        not in {
            "id",
            "tenant_id",
            "chart_id",
            "created_by_user_id",
            "updated_by_user_id",
            "created_at",
            "updated_at",
            "deleted_at",
            "version",
        }
    }
    binding_cols = {col for col, _e, _n in _ELEMENT_BINDING}
    assert model_cols == binding_cols, (
        f"projection binding drift: missing={model_cols - binding_cols}, "
        f"extra={binding_cols - model_cols}"
    )


@pytest.mark.asyncio
async def test_projection_element_names_match_dictionary() -> None:
    """The NEMSIS element names in the binding must match v3.5.1 data dictionary."""
    name_for_element = {elem: name for _col, elem, name in _ELEMENT_BINDING}
    assert (
        name_for_element["eDisposition.01"] == "Destination/Transferred To, Name"
    )
    assert name_for_element["eDisposition.12"] == "Incident/Patient Disposition"
    assert name_for_element["eDisposition.16"] == "Transport Disposition"
    assert name_for_element["eDisposition.18"] == "Level of Care Provided"
    assert name_for_element["eDisposition.09"] == "Hospital Capability"
    assert name_for_element["eDisposition.27"] == "Crew Disposition"
    assert (
        name_for_element["eDisposition.30"] == "EMS Transport Method, Additional"
    )


@pytest.mark.asyncio
async def test_projection_skips_eDisposition_26() -> None:
    """eDisposition.26 is intentionally undefined in NEMSIS v3.5.1."""
    elements = {elem for _col, elem, _name in _ELEMENT_BINDING}
    assert "eDisposition.26" not in elements
