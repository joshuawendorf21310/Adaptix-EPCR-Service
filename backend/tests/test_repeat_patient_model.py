"""Model-level tests for the RepeatPatientService pillar.

Verifies that :class:`EpcrRepeatPatientMatch` and
:class:`EpcrPriorChartReference` round-trip through the ORM with the
documented column shape, including the confidence range check and the
default ``reviewed`` / ``carry_forward_allowed`` flags.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
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
    EpcrPriorChartReference,
    EpcrRepeatPatientMatch,
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
            call_number="CALL-1",
            incident_type="medical",
            status=ChartStatus.NEW,
            created_by_user_id="user-1",
        )
        session.add(chart)
        await session.commit()
        yield session, chart
    await engine.dispose()


async def test_match_row_round_trip(db_session) -> None:
    session, chart = db_session
    reasons = [
        {"field": "date_of_birth", "equality": "exact"},
        {"field": "last_name", "equality": "case_insensitive"},
    ]
    now = datetime.now(UTC)
    row = EpcrRepeatPatientMatch(
        id=str(uuid4()),
        tenant_id="t1",
        chart_id=chart.id,
        matched_profile_id=str(uuid4()),
        confidence=Decimal("0.80"),
        match_reason_json=json.dumps(reasons),
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.commit()

    fetched = (
        await session.execute(
            select(EpcrRepeatPatientMatch).where(
                EpcrRepeatPatientMatch.id == row.id
            )
        )
    ).scalar_one()
    assert fetched.tenant_id == "t1"
    assert fetched.chart_id == chart.id
    assert float(fetched.confidence) == 0.80
    assert fetched.reviewed is False
    assert fetched.carry_forward_allowed is False
    assert fetched.reviewed_by is None
    assert fetched.reviewed_at is None
    assert json.loads(fetched.match_reason_json) == reasons


async def test_match_confidence_out_of_range_rejected(db_session) -> None:
    session, chart = db_session
    now = datetime.now(UTC)
    row = EpcrRepeatPatientMatch(
        id=str(uuid4()),
        tenant_id="t1",
        chart_id=chart.id,
        matched_profile_id=str(uuid4()),
        confidence=Decimal("1.50"),
        match_reason_json="[]",
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_prior_chart_reference_round_trip(db_session) -> None:
    session, chart = db_session
    now = datetime.now(UTC)
    ref = EpcrPriorChartReference(
        id=str(uuid4()),
        tenant_id="t1",
        chart_id=chart.id,
        prior_chart_id=str(uuid4()),
        encounter_at=now,
        chief_complaint="Chest pain",
        disposition="Transported",
        created_at=now,
    )
    session.add(ref)
    await session.commit()

    fetched = (
        await session.execute(
            select(EpcrPriorChartReference).where(
                EpcrPriorChartReference.id == ref.id
            )
        )
    ).scalar_one()
    assert fetched.chief_complaint == "Chest pain"
    assert fetched.disposition == "Transported"
    assert fetched.encounter_at is not None
