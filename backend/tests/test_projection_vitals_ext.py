"""Projection tests: eVitals extension -> NemsisFieldValue ledger.

Verifies populated scalar columns produce ledger rows keyed on
``occurrence_id=vitals_id``, JSON list columns produce one row per
entry with element-suffixed occurrence_id, GCS qualifiers and
reperfusion items each produce ledger rows with the proper group path,
and ``None``/empty values are NOT projected.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart, Vitals
from epcr_app.models_nemsis_field_values import NemsisFieldValue
from epcr_app.models_vitals_ext import (  # noqa: F401
    VitalsGcsQualifier,
    VitalsNemsisExt,
    VitalsReperfusionChecklist,
)
from epcr_app.projection_vitals_ext import (
    GCS_GROUP_PATH,
    SECTION,
    VITAL_GROUP_PATH,
    _GCS_GROUP_COLUMNS,
    _LIST_ELEMENT_BINDING,
    _SCALAR_ELEMENT_BINDING,
    project_vitals_ext,
)
from epcr_app.services_vitals_ext import (
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
async def test_projection_emits_scalars_with_vitals_occurrence(
    session: AsyncSession,
) -> None:
    chart, vitals = await _seed_chart_vitals(session, "t-1", "C-1")
    await VitalsExtService.upsert_ext(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        vitals_id=vitals.id,
        payload=VitalsExtPayload(
            obtained_prior_to_ems_code="9908001",
            respiratory_effort_code="3516001",
            etco2=35,
            gcs_eye_code="3518003",
            gcs_verbal_code="3519005",
            gcs_motor_code="3520006",
            gcs_total=14,
            avpu_code="3523001",
            stroke_scale_result_code="3526001",
            stroke_scale_type_code="3527001",
        ),
        user_id="u",
    )

    rows = await project_vitals_ext(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        vitals_id=vitals.id,
        user_id="u",
    )
    assert len(rows) == 10
    for row in rows:
        assert row["section"] == SECTION
        assert row["occurrence_id"] == vitals.id
        assert row["value"] is not None

    by_element = {r["element_number"]: r for r in rows}
    # GCS-component columns must route to the GCS sub-group.
    assert by_element["eVitals.19"]["group_path"] == GCS_GROUP_PATH
    assert by_element["eVitals.20"]["group_path"] == GCS_GROUP_PATH
    assert by_element["eVitals.21"]["group_path"] == GCS_GROUP_PATH
    assert by_element["eVitals.23"]["group_path"] == GCS_GROUP_PATH
    # Non-GCS scalar columns must use the VitalGroup path.
    assert by_element["eVitals.16"]["group_path"] == VITAL_GROUP_PATH
    assert by_element["eVitals.26"]["group_path"] == VITAL_GROUP_PATH


@pytest.mark.asyncio
async def test_projection_json_list_columns_one_row_per_entry(
    session: AsyncSession,
) -> None:
    chart, vitals = await _seed_chart_vitals(session, "t-1", "C-2")
    await VitalsExtService.upsert_ext(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        vitals_id=vitals.id,
        payload=VitalsExtPayload(
            cardiac_rhythm_codes_json=["3508001", "3508003", "3508005"],
            ecg_interpretation_method_codes_json=["3510001"],
        ),
        user_id="u",
    )
    rows = await project_vitals_ext(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        vitals_id=vitals.id,
        user_id="u",
    )

    rhythm_rows = [r for r in rows if r["element_number"] == "eVitals.03"]
    assert len(rhythm_rows) == 3
    assert {r["sequence_index"] for r in rhythm_rows} == {0, 1, 2}
    for r in rhythm_rows:
        assert r["occurrence_id"].startswith(f"{vitals.id}-eVitals.03-")

    interp_rows = [r for r in rows if r["element_number"] == "eVitals.05"]
    assert len(interp_rows) == 1
    assert interp_rows[0]["occurrence_id"] == f"{vitals.id}-eVitals.05-0"


@pytest.mark.asyncio
async def test_projection_gcs_qualifiers_and_reperfusion(
    session: AsyncSession,
) -> None:
    chart, vitals = await _seed_chart_vitals(session, "t-1", "C-3")
    await VitalsExtService.add_gcs_qualifier(
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
    await VitalsExtService.add_reperfusion_item(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        vitals_id=vitals.id,
        item_code="3528001",
        sequence_index=0,
        user_id="u",
    )

    rows = await project_vitals_ext(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        vitals_id=vitals.id,
        user_id="u",
    )
    gcs_rows = [r for r in rows if r["element_number"] == "eVitals.22"]
    assert len(gcs_rows) == 2
    for r in gcs_rows:
        assert r["group_path"] == GCS_GROUP_PATH
        assert r["occurrence_id"] == vitals.id
    assert {r["value"] for r in gcs_rows} == {"3521001", "3521003"}

    rc_rows = [r for r in rows if r["element_number"] == "eVitals.31"]
    assert len(rc_rows) == 1
    assert rc_rows[0]["occurrence_id"] == f"{vitals.id}-rc-0"
    assert rc_rows[0]["value"] == "3528001"


@pytest.mark.asyncio
async def test_projection_skips_none_and_empty(session: AsyncSession) -> None:
    chart, vitals = await _seed_chart_vitals(session, "t-1", "C-4")
    await VitalsExtService.upsert_ext(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        vitals_id=vitals.id,
        payload=VitalsExtPayload(
            etco2=30,
            cardiac_rhythm_codes_json=[],
        ),
        user_id="u",
    )
    rows = await project_vitals_ext(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        vitals_id=vitals.id,
        user_id="u",
    )
    elements = {r["element_number"] for r in rows}
    assert elements == {"eVitals.16"}


@pytest.mark.asyncio
async def test_projection_is_idempotent(session: AsyncSession) -> None:
    chart, vitals = await _seed_chart_vitals(session, "t-1", "C-5")
    await VitalsExtService.upsert_ext(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        vitals_id=vitals.id,
        payload=VitalsExtPayload(gcs_eye_code="3518003", gcs_total=15),
        user_id="u",
    )
    rows1 = await project_vitals_ext(
        session, tenant_id="t-1", chart_id=chart.id, vitals_id=vitals.id, user_id="u"
    )
    rows2 = await project_vitals_ext(
        session, tenant_id="t-1", chart_id=chart.id, vitals_id=vitals.id, user_id="u"
    )
    assert len(rows1) == len(rows2) == 2
    ledger = (
        await session.execute(
            select(NemsisFieldValue).where(
                NemsisFieldValue.chart_id == chart.id,
                NemsisFieldValue.section == SECTION,
            )
        )
    ).scalars().all()
    assert len(ledger) == 2


@pytest.mark.asyncio
async def test_projection_returns_empty_when_absent(session: AsyncSession) -> None:
    chart, vitals = await _seed_chart_vitals(session, "t-1", "C-empty")
    rows = await project_vitals_ext(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        vitals_id=vitals.id,
        user_id="u",
    )
    assert rows == []


@pytest.mark.asyncio
async def test_projection_binding_covers_every_scalar_and_list() -> None:
    """Sanity guards: the binding tables must enumerate every column."""
    from epcr_app.services_vitals_ext import _EXT_LIST_FIELDS, _EXT_SCALAR_FIELDS

    scalar_cols = {c for c, _e, _n in _SCALAR_ELEMENT_BINDING}
    list_cols = {c for c, _e, _n in _LIST_ELEMENT_BINDING}
    assert scalar_cols == set(_EXT_SCALAR_FIELDS)
    assert list_cols == set(_EXT_LIST_FIELDS)
    # GCS subgroup columns must all be valid scalar binding columns.
    assert _GCS_GROUP_COLUMNS <= scalar_cols


@pytest.mark.asyncio
async def test_projection_element_names_match_dictionary() -> None:
    name_for_element = {elem: name for _c, elem, name in _SCALAR_ELEMENT_BINDING}
    assert name_for_element["eVitals.02"] == "Obtained Prior to EMS Care"
    assert name_for_element["eVitals.26"] == "Level of Responsiveness (AVPU)"
    list_name = {elem: name for _c, elem, name in _LIST_ELEMENT_BINDING}
    assert list_name["eVitals.03"].startswith("Cardiac Rhythm")
