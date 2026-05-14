"""Projection tests: :class:`ChartPayment` (+ supply items) -> NemsisFieldValue ledger.

Verifies that populated scalar columns produce one ledger row per
ePayment.NN with the canonical element_number / element_name, that
None / empty-list columns are NOT projected, that 1:M JSON list
columns expand into one ledger row per list entry with a unique
occurrence_id and sequence_index, and that Supply Used child rows
expand into a paired (ePayment.55 + ePayment.56) group with a shared
occurrence_id.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart
from epcr_app.models_chart_payment import ChartPayment  # noqa: F401
from epcr_app.models_nemsis_field_values import NemsisFieldValue
from epcr_app.projection_chart_payment import (
    SECTION,
    SUPPLY_USED_GROUP,
    _ELEMENT_BINDING,
    project_chart_payment,
)
from epcr_app.services_chart_payment import (
    ChartPaymentPayload,
    ChartPaymentService,
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
    await ChartPaymentService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartPaymentPayload(
            primary_method_of_payment_code="9954001",
            insurance_company_name="Acme Health",
            insurance_company_city="Springfield",
            insurance_company_state="IL",
            pcs_signed_date=date(2026, 5, 1),
            mileage_to_closest_hospital=12.5,
            insured_date_of_birth=date(1980, 1, 15),
        ),
        user_id="u",
    )

    rows = await project_chart_payment(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert len(rows) == 7
    by_element = {r["element_number"]: r for r in rows}
    assert set(by_element.keys()) == {
        "ePayment.01",
        "ePayment.10",
        "ePayment.13",
        "ePayment.14",
        "ePayment.03",
        "ePayment.48",
        "ePayment.60",
    }
    for row in rows:
        assert row["section"] == SECTION
        assert row["value"] is not None
        # Scalar rows use empty occurrence_id and empty group_path.
        assert row["occurrence_id"] == ""
        assert row["group_path"] == ""
    # Date scalar projected as ISO-8601 string.
    assert by_element["ePayment.03"]["value"] == "2026-05-01"
    assert by_element["ePayment.60"]["value"] == "1980-01-15"


@pytest.mark.asyncio
async def test_projection_skips_none_columns(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-2")
    await ChartPaymentService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartPaymentPayload(primary_method_of_payment_code="9954001"),
        user_id="u",
    )
    rows = await project_chart_payment(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert len(rows) == 1
    assert rows[0]["element_number"] == "ePayment.01"
    assert rows[0]["value"] == "9954001"


@pytest.mark.asyncio
async def test_projection_expands_json_lists(session: AsyncSession) -> None:
    """One ledger row per JSON list entry; occurrence_id is unique per entry."""
    chart = await _seed_chart(session, "t-1", "C-list")
    await ChartPaymentService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartPaymentPayload(
            primary_method_of_payment_code="9954001",
            reason_for_pcs_codes_json=["RP1", "RP2", "RP3"],
            ems_condition_codes_json=["EC1"],
        ),
        user_id="u",
    )
    rows = await project_chart_payment(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    # 1 (primary method) + 3 (reason_for_pcs) + 1 (ems_condition)
    assert len(rows) == 5

    reason_rows = [r for r in rows if r["element_number"] == "ePayment.04"]
    ems_rows = [r for r in rows if r["element_number"] == "ePayment.51"]
    assert len(reason_rows) == 3
    assert len(ems_rows) == 1

    # Unique occurrence_id per list entry; sequence_index matches index.
    occ_ids = {r["occurrence_id"] for r in reason_rows}
    assert len(occ_ids) == 3
    seq = sorted(r["sequence_index"] for r in reason_rows)
    assert seq == [0, 1, 2]
    by_seq = {r["sequence_index"]: r["value"] for r in reason_rows}
    assert by_seq == {0: "RP1", 1: "RP2", 2: "RP3"}


@pytest.mark.asyncio
async def test_projection_skips_empty_lists(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-empty-list")
    await ChartPaymentService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartPaymentPayload(
            primary_method_of_payment_code="9954001",
            reason_for_pcs_codes_json=[],
        ),
        user_id="u",
    )
    rows = await project_chart_payment(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert len(rows) == 1
    assert rows[0]["element_number"] == "ePayment.01"


@pytest.mark.asyncio
async def test_projection_emits_paired_supply_used_group(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-1", "C-supply")
    await ChartPaymentService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartPaymentPayload(primary_method_of_payment_code="9954001"),
        user_id="u",
    )
    s1 = await ChartPaymentService.add_supply(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        supply_item_name="IV Catheter 18g",
        supply_item_quantity=2,
    )
    s2 = await ChartPaymentService.add_supply(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        supply_item_name="Saline 1000ml",
        supply_item_quantity=1,
    )
    rows = await project_chart_payment(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )

    # ePayment.01 + 2 supplies * 2 elements (.55 + .56) = 5
    assert len(rows) == 5
    name_rows = [r for r in rows if r["element_number"] == "ePayment.55"]
    qty_rows = [r for r in rows if r["element_number"] == "ePayment.56"]
    assert len(name_rows) == 2
    assert len(qty_rows) == 2

    for r in name_rows + qty_rows:
        assert r["group_path"] == SUPPLY_USED_GROUP
    # Paired group: each supply row's name + qty share the same occurrence_id.
    occ_for_s1_name = next(
        r["occurrence_id"]
        for r in name_rows
        if r["value"] == "IV Catheter 18g"
    )
    occ_for_s1_qty = next(
        r["occurrence_id"] for r in qty_rows if r["sequence_index"] == s1["sequence_index"]
    )
    assert occ_for_s1_name == occ_for_s1_qty == s1["id"]
    occ_for_s2_name = next(
        r["occurrence_id"] for r in name_rows if r["value"] == "Saline 1000ml"
    )
    assert occ_for_s2_name == s2["id"]
    # sequence_index propagated from the row.
    assert {r["sequence_index"] for r in name_rows} == {0, 1}


@pytest.mark.asyncio
async def test_projection_skips_soft_deleted_supplies(
    session: AsyncSession,
) -> None:
    chart = await _seed_chart(session, "t-1", "C-supply-deleted")
    await ChartPaymentService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartPaymentPayload(primary_method_of_payment_code="9954001"),
        user_id="u",
    )
    supply = await ChartPaymentService.add_supply(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        supply_item_name="Bandage",
        supply_item_quantity=1,
    )
    await ChartPaymentService.delete_supply(
        session, tenant_id="t-1", chart_id=chart.id, supply_id=supply["id"]
    )
    rows = await project_chart_payment(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    # Only ePayment.01 — no supply rows emitted.
    assert len(rows) == 1
    assert rows[0]["element_number"] == "ePayment.01"


@pytest.mark.asyncio
async def test_projection_is_idempotent(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-3")
    await ChartPaymentService.upsert(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        payload=ChartPaymentPayload(
            primary_method_of_payment_code="9954001",
            reason_for_pcs_codes_json=["R1", "R2"],
        ),
        user_id="u",
    )
    await ChartPaymentService.add_supply(
        session,
        tenant_id="t-1",
        chart_id=chart.id,
        supply_item_name="Bandage",
        supply_item_quantity=2,
    )
    rows1 = await project_chart_payment(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    rows2 = await project_chart_payment(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    # 1 (.01) + 2 (.04 list) + 2 (.55+.56 supply) = 5
    assert len(rows1) == len(rows2) == 5

    ledger = (
        await session.execute(
            select(NemsisFieldValue).where(
                NemsisFieldValue.chart_id == chart.id,
                NemsisFieldValue.section == SECTION,
            )
        )
    ).scalars().all()
    # Same upsert keys -> no duplicate rows.
    assert len(ledger) == 5


@pytest.mark.asyncio
async def test_projection_returns_empty_when_no_row(session: AsyncSession) -> None:
    chart = await _seed_chart(session, "t-1", "C-empty")
    rows = await project_chart_payment(
        session, tenant_id="t-1", chart_id=chart.id, user_id="u"
    )
    assert rows == []


@pytest.mark.asyncio
async def test_projection_binding_covers_every_column() -> None:
    """The binding tables must cover every column on the model."""
    model_cols = {
        c.name
        for c in __import__(
            "epcr_app.models_chart_payment", fromlist=["ChartPayment"]
        ).ChartPayment.__table__.columns
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
    """Spot-check that NEMSIS element names in the binding match v3.5.1."""
    name_for_element = {elem: name for _col, elem, name in _ELEMENT_BINDING}
    assert name_for_element["ePayment.01"] == "Primary Method of Payment"
    assert (
        name_for_element["ePayment.02"]
        == "Physician Certification Statement"
    )
    assert name_for_element["ePayment.10"] == "Insurance Company Name"
    assert name_for_element["ePayment.22"] == "Relationship to the Insured"
    assert (
        name_for_element["ePayment.48"]
        == "Mileage to Closest Appropriate Hospital"
    )
    assert name_for_element["ePayment.57"] == "Payer Type"
    assert name_for_element["ePayment.60"] == "Insured's Date of Birth"


@pytest.mark.asyncio
async def test_projection_skips_epayment_43_and_55_56_from_scalar_binding() -> None:
    """ePayment.43 is undefined in the spec; .55/.56 are emitted from the
    Supply Used child table, not from a scalar/list binding."""
    elements = {elem for _col, elem, _name in _ELEMENT_BINDING}
    assert "ePayment.43" not in elements
    assert "ePayment.55" not in elements
    assert "ePayment.56" not in elements
