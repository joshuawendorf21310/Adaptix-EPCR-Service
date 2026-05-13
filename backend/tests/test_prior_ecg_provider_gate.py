"""Provider-attestation gate for prior-ECG comparison consumption.

NEMSIS exporters call
:func:`prior_ecg_service.is_comparison_ready_for_export`. The contract
is: the gate returns False unless the comparison row exists AND has
``provider_confirmed=True``. This test pins that contract.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest_asyncio
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
from epcr_app.services import prior_ecg_service


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


def test_gate_rejects_none() -> None:
    assert prior_ecg_service.is_comparison_ready_for_export(None) is False


async def test_gate_rejects_unconfirmed_row(db_session) -> None:
    session, chart = db_session
    now = datetime.now(UTC)
    prior = EpcrPriorEcgReference(
        id=str(uuid4()),
        tenant_id="t1",
        chart_id=chart.id,
        captured_at=now,
        encounter_context="prior_clinic_visit",
        monitor_imported=False,
        quality="good",
        created_at=now,
    )
    session.add(prior)
    await session.flush()

    # Directly construct a comparison row WITHOUT going through
    # record_comparison, so provider_confirmed stays False.
    unconfirmed = EpcrEcgComparisonResult(
        id=str(uuid4()),
        tenant_id="t1",
        chart_id=chart.id,
        prior_ecg_id=prior.id,
        comparison_state="similar",
        provider_confirmed=False,
        created_at=now,
        updated_at=now,
    )
    session.add(unconfirmed)
    await session.commit()

    assert (
        prior_ecg_service.is_comparison_ready_for_export(unconfirmed) is False
    )


async def test_gate_accepts_confirmed_row(db_session) -> None:
    session, chart = db_session
    prior = await prior_ecg_service.attach_prior(
        session,
        tenant_id="t1",
        chart_id=chart.id,
        user_id="user-1",
        prior_chart_id=None,
        image_storage_uri=None,
        encounter_context="prior_clinic_visit",
        monitor_imported=False,
        quality="good",
    )
    confirmed = await prior_ecg_service.record_comparison(
        session,
        tenant_id="t1",
        chart_id=chart.id,
        user_id="provider-7",
        prior_ecg_id=prior.id,
        comparison_state="similar",
    )
    await session.commit()
    assert (
        prior_ecg_service.is_comparison_ready_for_export(confirmed) is True
    )
