"""Model-level tests for the prior-ECG pillar.

Verifies that :class:`EpcrPriorEcgReference` and
:class:`EpcrEcgComparisonResult` round-trip through the ORM with the
documented column shape, and that ``provider_confirmed`` defaults to
False so the export-readiness gate has a safe initial state.
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
    EpcrEcgComparisonResult,
    EpcrPriorEcgReference,
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


async def test_prior_ecg_reference_round_trip(db_session) -> None:
    session, chart = db_session
    now = datetime.now(UTC)
    row = EpcrPriorEcgReference(
        id=str(uuid4()),
        tenant_id="t1",
        chart_id=chart.id,
        prior_chart_id=None,
        captured_at=now,
        encounter_context="prior_clinic_visit",
        image_storage_uri="s3://bucket/key",
        monitor_imported=True,
        quality="good",
        notes="captured on monitor",
        created_at=now,
    )
    session.add(row)
    await session.commit()

    fetched = (
        await session.execute(
            select(EpcrPriorEcgReference).where(
                EpcrPriorEcgReference.id == row.id
            )
        )
    ).scalar_one()
    assert fetched.tenant_id == "t1"
    assert fetched.encounter_context == "prior_clinic_visit"
    assert fetched.quality == "good"
    assert fetched.monitor_imported is True
    assert fetched.image_storage_uri == "s3://bucket/key"


async def test_comparison_result_defaults_provider_unconfirmed(
    db_session,
) -> None:
    session, chart = db_session
    now = datetime.now(UTC)
    prior = EpcrPriorEcgReference(
        id=str(uuid4()),
        tenant_id="t1",
        chart_id=chart.id,
        captured_at=now,
        encounter_context="prior_clinic_visit",
        monitor_imported=False,
        quality="acceptable",
        created_at=now,
    )
    session.add(prior)
    await session.flush()

    cmp_row = EpcrEcgComparisonResult(
        id=str(uuid4()),
        tenant_id="t1",
        chart_id=chart.id,
        prior_ecg_id=prior.id,
        comparison_state="similar",
        created_at=now,
        updated_at=now,
    )
    session.add(cmp_row)
    await session.commit()

    fetched = (
        await session.execute(
            select(EpcrEcgComparisonResult).where(
                EpcrEcgComparisonResult.id == cmp_row.id
            )
        )
    ).scalar_one()
    assert fetched.comparison_state == "similar"
    assert fetched.provider_confirmed is False
    assert fetched.provider_id is None
    assert fetched.confirmed_at is None
