"""Service tests for the row-per-occurrence NEMSIS field-value ledger.

Asserts:
  * Repeating-group occurrences (same chart + element_number, different
    occurrence_id) round-trip without collision.
  * Tenant isolation: tenant A cannot read tenant B's rows.
  * Chart isolation: chart-scoped reads never leak across charts.
  * Re-upserting the same occurrence updates in place (no duplicate row).
  * NV / PN / xsi:nil attribute sidecars and validation issues persist
    losslessly on the same row.
  * Soft-delete is tenant-scoped and excludes rows from default reads.
  * Bulk save commits all payloads atomically per call.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from epcr_app.models import Base
from epcr_app.models_nemsis_field_values import NemsisFieldValue  # noqa: F401
from epcr_app.services_nemsis_field_values import (
    FieldValuePayload,
    NemsisFieldValueError,
    NemsisFieldValueService,
)


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessionmaker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield sessionmaker
    await engine.dispose()


def _vital(occurrence_id: str, value: str, sequence_index: int = 0) -> FieldValuePayload:
    return FieldValuePayload(
        section="EMS",
        element_number="eVitals.01",
        element_name="VitalSignsTakenDateTime",
        value=value,
        group_path="eVitals",
        occurrence_id=occurrence_id,
        sequence_index=sequence_index,
        attributes={},
        source="manual",
        validation_status="unvalidated",
        validation_issues=[],
        user_id="user-1",
    )


@pytest.mark.asyncio
async def test_repeating_group_occurrences_coexist(db) -> None:
    async with db() as session:
        await NemsisFieldValueService.upsert(
            session,
            tenant_id="tenant-A",
            chart_id="chart-1",
            payload=_vital("occ-1", "2026-05-09T10:00:00Z", sequence_index=0),
        )
        await NemsisFieldValueService.upsert(
            session,
            tenant_id="tenant-A",
            chart_id="chart-1",
            payload=_vital("occ-2", "2026-05-09T10:05:00Z", sequence_index=1),
        )
        await NemsisFieldValueService.upsert(
            session,
            tenant_id="tenant-A",
            chart_id="chart-1",
            payload=_vital("occ-3", "2026-05-09T10:10:00Z", sequence_index=2),
        )
        await session.commit()

        items = await NemsisFieldValueService.list_for_chart(
            session, tenant_id="tenant-A", chart_id="chart-1"
        )
        assert len(items) == 3
        occ_ids = {it["occurrence_id"] for it in items}
        assert occ_ids == {"occ-1", "occ-2", "occ-3"}
        # Element_number must be the same across all occurrences.
        assert {it["element_number"] for it in items} == {"eVitals.01"}


@pytest.mark.asyncio
async def test_upsert_same_occurrence_updates_in_place(db) -> None:
    async with db() as session:
        first = await NemsisFieldValueService.upsert(
            session,
            tenant_id="tenant-A",
            chart_id="chart-1",
            payload=_vital("occ-1", "first"),
        )
        second = await NemsisFieldValueService.upsert(
            session,
            tenant_id="tenant-A",
            chart_id="chart-1",
            payload=_vital("occ-1", "second"),
        )
        await session.commit()

        assert first["id"] == second["id"], "upsert must update in place, not create"
        items = await NemsisFieldValueService.list_for_chart(
            session, tenant_id="tenant-A", chart_id="chart-1"
        )
        assert len(items) == 1
        assert items[0]["value"] == "second"


@pytest.mark.asyncio
async def test_tenant_isolation(db) -> None:
    async with db() as session:
        await NemsisFieldValueService.upsert(
            session,
            tenant_id="tenant-A",
            chart_id="chart-1",
            payload=_vital("occ-1", "A-value"),
        )
        await NemsisFieldValueService.upsert(
            session,
            tenant_id="tenant-B",
            chart_id="chart-1",
            payload=_vital("occ-1", "B-value"),
        )
        await session.commit()

        a_items = await NemsisFieldValueService.list_for_chart(
            session, tenant_id="tenant-A", chart_id="chart-1"
        )
        b_items = await NemsisFieldValueService.list_for_chart(
            session, tenant_id="tenant-B", chart_id="chart-1"
        )
        assert len(a_items) == 1 and a_items[0]["value"] == "A-value"
        assert len(b_items) == 1 and b_items[0]["value"] == "B-value"

        # Cross-tenant read for an unknown tenant returns nothing.
        empty = await NemsisFieldValueService.list_for_chart(
            session, tenant_id="tenant-C", chart_id="chart-1"
        )
        assert empty == []


@pytest.mark.asyncio
async def test_chart_isolation(db) -> None:
    async with db() as session:
        await NemsisFieldValueService.upsert(
            session,
            tenant_id="tenant-A",
            chart_id="chart-1",
            payload=_vital("occ-1", "v1"),
        )
        await NemsisFieldValueService.upsert(
            session,
            tenant_id="tenant-A",
            chart_id="chart-2",
            payload=_vital("occ-1", "v2"),
        )
        await session.commit()

        only_chart_2 = await NemsisFieldValueService.list_for_chart(
            session, tenant_id="tenant-A", chart_id="chart-2"
        )
        assert len(only_chart_2) == 1 and only_chart_2[0]["value"] == "v2"


@pytest.mark.asyncio
async def test_attributes_and_validation_issues_round_trip(db) -> None:
    async with db() as session:
        payload = FieldValuePayload(
            section="EMS",
            element_number="eHistory.08",
            element_name="MedicationAllergies",
            value=None,
            group_path="eHistory",
            occurrence_id="occ-1",
            attributes={"NV": "7701001", "xsiNil": "true"},
            source="manual",
            validation_status="warning",
            validation_issues=[
                {
                    "ruleId": "NV-7701001",
                    "level": "warning",
                    "message": "Not Recorded sentinel applied",
                }
            ],
            user_id="user-1",
        )
        result = await NemsisFieldValueService.upsert(
            session, tenant_id="tenant-A", chart_id="chart-1", payload=payload
        )
        await session.commit()

        assert result["attributes"] == {"NV": "7701001", "xsiNil": "true"}
        assert result["validation_issues"][0]["ruleId"] == "NV-7701001"
        assert result["validation_status"] == "warning"

        items = await NemsisFieldValueService.list_for_chart(
            session, tenant_id="tenant-A", chart_id="chart-1"
        )
        assert items[0]["attributes"] == {"NV": "7701001", "xsiNil": "true"}
        assert items[0]["validation_issues"][0]["message"] == (
            "Not Recorded sentinel applied"
        )


@pytest.mark.asyncio
async def test_soft_delete_is_tenant_scoped_and_filters_default_reads(db) -> None:
    async with db() as session:
        created = await NemsisFieldValueService.upsert(
            session,
            tenant_id="tenant-A",
            chart_id="chart-1",
            payload=_vital("occ-1", "v"),
        )
        await session.commit()

        # Wrong tenant cannot soft-delete.
        wrong_tenant = await NemsisFieldValueService.soft_delete(
            session,
            tenant_id="tenant-B",
            chart_id="chart-1",
            row_id=created["id"],
        )
        assert wrong_tenant is False

        deleted = await NemsisFieldValueService.soft_delete(
            session,
            tenant_id="tenant-A",
            chart_id="chart-1",
            row_id=created["id"],
        )
        await session.commit()
        assert deleted is True

        active = await NemsisFieldValueService.list_for_chart(
            session, tenant_id="tenant-A", chart_id="chart-1"
        )
        assert active == []

        with_deleted = await NemsisFieldValueService.list_for_chart(
            session,
            tenant_id="tenant-A",
            chart_id="chart-1",
            include_deleted=True,
        )
        assert len(with_deleted) == 1
        assert with_deleted[0]["deleted_at"] is not None


@pytest.mark.asyncio
async def test_bulk_save_round_trip(db) -> None:
    async with db() as session:
        payloads = [
            _vital(f"occ-{i}", f"v-{i}", sequence_index=i) for i in range(5)
        ]
        results = await NemsisFieldValueService.bulk_save(
            session,
            tenant_id="tenant-A",
            chart_id="chart-1",
            payloads=payloads,
        )
        await session.commit()

        assert len(results) == 5
        items = await NemsisFieldValueService.list_for_chart(
            session, tenant_id="tenant-A", chart_id="chart-1"
        )
        assert len(items) == 5
        assert [it["sequence_index"] for it in items] == [0, 1, 2, 3, 4]


@pytest.mark.asyncio
async def test_validation_rejects_bad_input(db) -> None:
    async with db() as session:
        with pytest.raises(NemsisFieldValueError):
            await NemsisFieldValueService.upsert(
                session,
                tenant_id="tenant-A",
                chart_id="chart-1",
                payload=FieldValuePayload(
                    section="",
                    element_number="x",
                    element_name="y",
                ),
            )
        with pytest.raises(NemsisFieldValueError):
            await NemsisFieldValueService.upsert(
                session,
                tenant_id="tenant-A",
                chart_id="chart-1",
                payload=FieldValuePayload(
                    section="EMS",
                    element_number="x",
                    element_name="y",
                    source="bogus",
                ),
            )
        with pytest.raises(NemsisFieldValueError):
            await NemsisFieldValueService.upsert(
                session,
                tenant_id="",
                chart_id="chart-1",
                payload=FieldValuePayload(
                    section="EMS",
                    element_number="x",
                    element_name="y",
                ),
            )
