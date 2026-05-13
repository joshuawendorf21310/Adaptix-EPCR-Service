"""Model-level tests for :class:`EpcrProtocolContext`.

Verifies the row round-trips through the ORM with the documented column
shape, that the active-context invariant (``disengaged_at IS NULL``) can
be queried cleanly, and that the soft-disengage pattern preserves
historical rows for audit replay.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest_asyncio
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from epcr_app.models import (
    Base,
    Chart,
    ChartStatus,
    EpcrProtocolContext,
)


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessionmaker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with sessionmaker() as session:
        chart = Chart(
            id=str(uuid4()),
            tenant_id="t1",
            call_number="CALL-PROTO-1",
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
    snapshot = {
        "score": 0.5,
        "blockers": [],
        "warnings": [],
        "advisories": [],
        "generated_at": now.isoformat(),
        "active_pack": "ACLS",
        "pack_known": True,
        "satisfied_fields": ["eVitals.03"],
        "missing_fields": ["eVitals.10"],
        "required_total": 2,
        "required_present": 1,
    }
    row = EpcrProtocolContext(
        id=str(uuid4()),
        tenant_id="t1",
        chart_id=chart.id,
        active_pack="ACLS",
        engaged_at=now,
        engaged_by="user-1",
        disengaged_at=None,
        required_field_satisfaction_json=json.dumps(snapshot),
        pack_version="engine:test:1",
    )
    session.add(row)
    await session.commit()

    fetched = (
        await session.execute(
            select(EpcrProtocolContext).where(
                EpcrProtocolContext.id == row.id
            )
        )
    ).scalar_one()
    assert fetched.tenant_id == "t1"
    assert fetched.chart_id == chart.id
    assert fetched.active_pack == "ACLS"
    assert fetched.engaged_by == "user-1"
    assert fetched.disengaged_at is None
    assert fetched.pack_version == "engine:test:1"
    assert fetched.created_at is not None
    assert fetched.updated_at is not None
    payload = json.loads(fetched.required_field_satisfaction_json)
    assert payload["active_pack"] == "ACLS"
    assert payload["satisfied_fields"] == ["eVitals.03"]


async def test_disengage_preserves_row_and_allows_new_active(db_session) -> None:
    session, chart = db_session
    now = datetime.now(UTC)
    first = EpcrProtocolContext(
        id=str(uuid4()),
        tenant_id="t1",
        chart_id=chart.id,
        active_pack="ACLS",
        engaged_at=now,
        engaged_by="user-1",
        pack_version="engine:test:1",
    )
    session.add(first)
    await session.commit()

    # Disengage the first context.
    first.disengaged_at = datetime.now(UTC)
    await session.commit()

    # A second context becomes active.
    second = EpcrProtocolContext(
        id=str(uuid4()),
        tenant_id="t1",
        chart_id=chart.id,
        active_pack="PALS",
        engaged_at=datetime.now(UTC),
        engaged_by="user-2",
        pack_version="engine:test:1",
    )
    session.add(second)
    await session.commit()

    active = (
        await session.execute(
            select(EpcrProtocolContext).where(
                and_(
                    EpcrProtocolContext.tenant_id == "t1",
                    EpcrProtocolContext.chart_id == chart.id,
                    EpcrProtocolContext.disengaged_at.is_(None),
                )
            )
        )
    ).scalars().all()
    assert len(active) == 1
    assert active[0].active_pack == "PALS"

    # First row is preserved with disengaged_at set.
    history = (
        await session.execute(
            select(EpcrProtocolContext).where(
                EpcrProtocolContext.chart_id == chart.id
            )
        )
    ).scalars().all()
    assert len(history) == 2
    disengaged_packs = {
        r.active_pack for r in history if r.disengaged_at is not None
    }
    assert disengaged_packs == {"ACLS"}


async def test_tenant_isolation(db_session) -> None:
    session, chart = db_session
    now = datetime.now(UTC)
    session.add(
        EpcrProtocolContext(
            id=str(uuid4()),
            tenant_id="t1",
            chart_id=chart.id,
            active_pack="ACLS",
            engaged_at=now,
            engaged_by="user-1",
            pack_version="engine:test:1",
        )
    )
    # A foreign-tenant row with the same chart_id (intentionally
    # nonsensical referentially but useful as a guard) should never
    # appear when filtering by tenant_id="t1".
    session.add(
        EpcrProtocolContext(
            id=str(uuid4()),
            tenant_id="t2",
            chart_id=chart.id,
            active_pack="PALS",
            engaged_at=now,
            engaged_by="user-other",
            pack_version="engine:test:1",
        )
    )
    await session.commit()

    rows = (
        await session.execute(
            select(EpcrProtocolContext).where(
                EpcrProtocolContext.tenant_id == "t1"
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].active_pack == "ACLS"
