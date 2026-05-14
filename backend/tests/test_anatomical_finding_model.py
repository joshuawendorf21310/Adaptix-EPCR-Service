"""Model-level tests for :class:`EpcrAnatomicalFinding`.

Verifies the row round-trips through the ORM with the documented column
shape and that the soft-delete pattern hides rows from non-deleted reads
while preserving them in the database for audit replay.
"""

from __future__ import annotations

from datetime import UTC, datetime
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
)


@pytest_asyncio.fixture
async def db_session():
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


async def test_insert_and_query_back(db_session) -> None:
    session, chart = db_session
    now = datetime.now(UTC)
    row = EpcrAnatomicalFinding(
        id=str(uuid4()),
        chart_id=chart.id,
        tenant_id="t1",
        region_id="region_head",
        region_label="Head",
        body_view="front",
        finding_type="laceration",
        severity="moderate",
        laterality="midline",
        pain_scale=7,
        burn_tbsa_percent=None,
        cms_pulse="present",
        cms_motor="intact",
        cms_sensation="intact",
        cms_capillary_refill="normal",
        pertinent_negative=False,
        notes="3cm scalp lac",
        assessed_at=now,
        assessed_by="user-1",
    )
    session.add(row)
    await session.commit()

    fetched = (
        await session.execute(
            select(EpcrAnatomicalFinding).where(EpcrAnatomicalFinding.id == row.id)
        )
    ).scalar_one()
    assert fetched.region_id == "region_head"
    assert fetched.body_view == "front"
    assert fetched.finding_type == "laceration"
    assert fetched.pain_scale == 7
    assert fetched.cms_pulse == "present"
    assert fetched.pertinent_negative is False
    assert fetched.deleted_at is None
    assert fetched.created_at is not None
    assert fetched.updated_at is not None


async def test_soft_delete_hides_row(db_session) -> None:
    session, chart = db_session
    now = datetime.now(UTC)
    row = EpcrAnatomicalFinding(
        id=str(uuid4()),
        chart_id=chart.id,
        tenant_id="t1",
        region_id="region_chest",
        region_label="Chest",
        body_view="front",
        finding_type="contusion",
        pertinent_negative=False,
        assessed_at=now,
        assessed_by="user-1",
    )
    session.add(row)
    await session.commit()

    row.deleted_at = datetime.now(UTC)
    await session.commit()

    live = (
        await session.execute(
            select(EpcrAnatomicalFinding).where(
                EpcrAnatomicalFinding.chart_id == chart.id,
                EpcrAnatomicalFinding.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    assert live == []

    archived = (
        await session.execute(
            select(EpcrAnatomicalFinding).where(EpcrAnatomicalFinding.id == row.id)
        )
    ).scalar_one()
    assert archived.deleted_at is not None
