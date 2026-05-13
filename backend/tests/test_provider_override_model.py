"""ORM-level tests for :class:`EpcrProviderOverride`.

Validates round-trip persistence and the portable CHECK constraint
enforcing ``length(reason_text) >= 8``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from epcr_app.models import (
    Base,
    Chart,
    ChartStatus,
    EpcrProviderOverride,
)


@pytest_asyncio.fixture
async def db_setup():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessionmaker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with sessionmaker() as session:
        chart = Chart(
            id=str(uuid4()),
            tenant_id="t-mod",
            call_number="CALL-MOD",
            incident_type="medical",
            status=ChartStatus.NEW,
            created_by_user_id="user-mod",
        )
        session.add(chart)
        await session.commit()
        yield session, chart
    await engine.dispose()


@pytest.mark.asyncio
async def test_provider_override_round_trip(db_setup):
    session, chart = db_setup
    now = datetime.now(UTC)
    row = EpcrProviderOverride(
        id=str(uuid4()),
        tenant_id=chart.tenant_id,
        chart_id=chart.id,
        section="vitals",
        field_key="systolic_bp",
        kind="validation_warning",
        reason_text="BP outside automated range due to known hypertension",
        overrode_at=now,
        overrode_by="user-mod",
        created_at=now,
    )
    session.add(row)
    await session.commit()

    fetched = (
        await session.execute(
            select(EpcrProviderOverride).where(
                EpcrProviderOverride.id == row.id
            )
        )
    ).scalar_one()

    assert fetched.tenant_id == chart.tenant_id
    assert fetched.chart_id == chart.id
    assert fetched.section == "vitals"
    assert fetched.field_key == "systolic_bp"
    assert fetched.kind == "validation_warning"
    assert fetched.reason_text.startswith("BP outside")
    assert fetched.overrode_by == "user-mod"
    assert fetched.supervisor_id is None
    assert fetched.supervisor_confirmed_at is None


@pytest.mark.asyncio
async def test_provider_override_reason_min_length_enforced(db_setup):
    session, chart = db_setup
    now = datetime.now(UTC)
    row = EpcrProviderOverride(
        id=str(uuid4()),
        tenant_id=chart.tenant_id,
        chart_id=chart.id,
        section="vitals",
        field_key="systolic_bp",
        kind="validation_warning",
        reason_text="short",  # 5 chars, below the 8-char minimum
        overrode_at=now,
        overrode_by="user-mod",
        created_at=now,
    )
    session.add(row)
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


@pytest.mark.asyncio
async def test_provider_override_supervisor_round_trip(db_setup):
    session, chart = db_setup
    now = datetime.now(UTC)
    row = EpcrProviderOverride(
        id=str(uuid4()),
        tenant_id=chart.tenant_id,
        chart_id=chart.id,
        section="medications",
        field_key="dose_outside_protocol",
        kind="lock_blocker",
        reason_text="Medical control approved dose escalation",
        overrode_at=now,
        overrode_by="user-mod",
        supervisor_id="sup-7",
        supervisor_confirmed_at=now,
        created_at=now,
    )
    session.add(row)
    await session.commit()

    fetched = (
        await session.execute(
            select(EpcrProviderOverride).where(
                EpcrProviderOverride.id == row.id
            )
        )
    ).scalar_one()
    assert fetched.supervisor_id == "sup-7"
    assert fetched.supervisor_confirmed_at is not None
