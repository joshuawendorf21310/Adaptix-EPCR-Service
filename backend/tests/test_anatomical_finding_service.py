"""Service-level tests for :class:`AnatomicalFindingService`.

Validates the replace-for-chart diff semantics:
- Empty -> [A, B] inserts 2 rows + 2 audit entries.
- [A, B] -> [A', C] updates A, inserts C, soft-deletes B, writes 3
  audit entries.
"""

from __future__ import annotations

from uuid import uuid4

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from epcr_app.models import (
    Base,
    Chart,
    ChartStatus,
    EpcrAnatomicalFinding,
    EpcrAuditLog,
)
from epcr_app.services.anatomical_finding_service import (
    AnatomicalFindingService,
)


@pytest_asyncio.fixture
async def db_setup():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with sessionmaker() as session:
        chart = Chart(
            id=str(uuid4()),
            tenant_id="t1",
            call_number="CALL-1",
            incident_type="medical",
            status=ChartStatus.NEW,
            created_by_user_id="user-1",
        )
        session.add(chart)
        await session.commit()
        yield session, chart
    await engine.dispose()


def _finding(**overrides):
    payload = {
        "regionId": "region_head",
        "regionLabel": "Head",
        "bodyView": "front",
        "findingType": "laceration",
        "severity": "moderate",
        "laterality": "midline",
        "painScale": 5,
        "burnTbsaPercent": None,
        "cms": {
            "pulse": "present",
            "motor": "intact",
            "sensation": "intact",
            "capillaryRefill": "normal",
        },
        "pertinentNegative": False,
        "notes": None,
        "assessedAt": "2026-05-12T10:00:00Z",
        "assessedBy": "user-1",
    }
    payload.update(overrides)
    return payload


async def _audit_actions(session, chart_id) -> list[str]:
    rows = (
        await session.execute(
            select(EpcrAuditLog).where(EpcrAuditLog.chart_id == chart_id)
        )
    ).scalars().all()
    return [r.action for r in rows]


async def test_empty_to_two_inserts_two_findings_and_two_audits(db_setup) -> None:
    session, chart = db_setup
    result = await AnatomicalFindingService.replace_for_chart(
        session,
        tenant_id="t1",
        chart_id=chart.id,
        user_id="user-1",
        findings=[
            _finding(regionId="region_head", regionLabel="Head"),
            _finding(regionId="region_chest", regionLabel="Chest"),
        ],
    )
    await session.commit()
    assert len(result) == 2
    rows = (
        await session.execute(
            select(EpcrAnatomicalFinding).where(
                EpcrAnatomicalFinding.chart_id == chart.id,
                EpcrAnatomicalFinding.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    assert len(rows) == 2

    actions = await _audit_actions(session, chart.id)
    created_actions = [a for a in actions if a == "anatomical_finding.created"]
    assert len(created_actions) == 2


async def test_diff_updates_inserts_and_soft_deletes(db_setup) -> None:
    session, chart = db_setup
    first = await AnatomicalFindingService.replace_for_chart(
        session,
        tenant_id="t1",
        chart_id=chart.id,
        user_id="user-1",
        findings=[
            _finding(regionId="region_head", regionLabel="Head"),
            _finding(regionId="region_chest", regionLabel="Chest"),
        ],
    )
    await session.commit()
    # Use dict lookup by regionId — order of returned list is not guaranteed.
    by_region = {f["regionId"]: f for f in first}
    assert "region_head" in by_region and "region_chest" in by_region
    a_id = by_region["region_head"]["id"]   # A = head (will be updated)
    b_id = by_region["region_chest"]["id"]  # B = chest (will be soft-deleted)

    # Snapshot current audit count so we count only the diff actions
    before_actions = await _audit_actions(session, chart.id)
    before_count = len(before_actions)

    # [A', C]: update A (new severity), drop B, insert C
    a_prime = _finding(
        regionId="region_head",
        regionLabel="Head",
        severity="severe",
    )
    a_prime["id"] = a_id
    c_new = _finding(regionId="region_left_hand", regionLabel="Left Hand")
    result = await AnatomicalFindingService.replace_for_chart(
        session,
        tenant_id="t1",
        chart_id=chart.id,
        user_id="user-1",
        findings=[a_prime, c_new],
    )
    await session.commit()

    assert len(result) == 2
    region_ids = sorted(r["regionId"] for r in result)
    assert region_ids == ["region_head", "region_left_hand"]

    # B is soft-deleted, present in storage but hidden
    archived = (
        await session.execute(
            select(EpcrAnatomicalFinding).where(EpcrAnatomicalFinding.id == b_id)
        )
    ).scalar_one()
    assert archived.deleted_at is not None

    # A is updated
    a_row = (
        await session.execute(
            select(EpcrAnatomicalFinding).where(EpcrAnatomicalFinding.id == a_id)
        )
    ).scalar_one()
    assert a_row.severity == "severe"

    diff_actions = (await _audit_actions(session, chart.id))[before_count:]
    assert sorted(diff_actions) == sorted(
        [
            "anatomical_finding.updated",
            "anatomical_finding.created",
            "anatomical_finding.deleted",
        ]
    )
