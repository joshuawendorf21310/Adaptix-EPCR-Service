"""Service-level tests for ``prior_ecg_service``.

Validates attach / list / compare flows and verifies that each write
emits an :class:`EpcrAuditLog` row with the documented action verb.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
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
    EpcrAuditLog,
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


async def _audit_actions(session: AsyncSession) -> list[str]:
    rows = (
        await session.execute(
            select(EpcrAuditLog).order_by(EpcrAuditLog.performed_at)
        )
    ).scalars().all()
    return [r.action for r in rows]


async def test_attach_prior_persists_and_audits(db_session) -> None:
    session, chart = db_session
    row = await prior_ecg_service.attach_prior(
        session,
        tenant_id="t1",
        chart_id=chart.id,
        user_id="user-1",
        prior_chart_id=None,
        image_storage_uri="s3://bucket/key",
        encounter_context="prior_clinic_visit",
        monitor_imported=True,
        quality="good",
        captured_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
    )
    await session.commit()
    assert isinstance(row, EpcrPriorEcgReference)
    assert row.quality == "good"
    assert row.encounter_context == "prior_clinic_visit"

    actions = await _audit_actions(session)
    assert "ecg.prior_attached" in actions


async def test_attach_prior_rejects_bad_quality(db_session) -> None:
    session, chart = db_session
    with pytest.raises(prior_ecg_service.PriorEcgValidationError):
        await prior_ecg_service.attach_prior(
            session,
            tenant_id="t1",
            chart_id=chart.id,
            user_id="user-1",
            prior_chart_id=None,
            image_storage_uri=None,
            encounter_context="prior_clinic_visit",
            monitor_imported=False,
            quality="excellent",  # not in allowed set
        )


async def test_list_prior_for_chart_returns_in_order(db_session) -> None:
    session, chart = db_session
    early = await prior_ecg_service.attach_prior(
        session,
        tenant_id="t1",
        chart_id=chart.id,
        user_id="user-1",
        prior_chart_id=None,
        image_storage_uri=None,
        encounter_context="prior_clinic_visit",
        monitor_imported=False,
        quality="good",
        captured_at=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
    )
    later = await prior_ecg_service.attach_prior(
        session,
        tenant_id="t1",
        chart_id=chart.id,
        user_id="user-1",
        prior_chart_id=None,
        image_storage_uri=None,
        encounter_context="prior_ed_visit",
        monitor_imported=False,
        quality="acceptable",
        captured_at=datetime(2026, 5, 1, 0, 0, tzinfo=UTC),
    )
    await session.commit()

    rows = await prior_ecg_service.list_prior_for_chart(
        session, "t1", chart.id
    )
    assert [r.id for r in rows] == [early.id, later.id]


async def test_record_comparison_marks_provider_confirmed(db_session) -> None:
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
    cmp_row = await prior_ecg_service.record_comparison(
        session,
        tenant_id="t1",
        chart_id=chart.id,
        user_id="provider-7",
        prior_ecg_id=prior.id,
        comparison_state="different",
        notes="ST changes vs prior",
    )
    await session.commit()

    assert isinstance(cmp_row, EpcrEcgComparisonResult)
    assert cmp_row.provider_confirmed is True
    assert cmp_row.provider_id == "provider-7"
    assert cmp_row.confirmed_at is not None
    assert cmp_row.comparison_state == "different"

    actions = await _audit_actions(session)
    assert "ecg.prior_attached" in actions
    assert "ecg.comparison_recorded" in actions


async def test_record_comparison_rejects_unknown_state(db_session) -> None:
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
    with pytest.raises(prior_ecg_service.PriorEcgValidationError):
        await prior_ecg_service.record_comparison(
            session,
            tenant_id="t1",
            chart_id=chart.id,
            user_id="provider-7",
            prior_ecg_id=prior.id,
            comparison_state="stemi",  # forbidden / not in pre-enumerated set
        )


async def test_record_comparison_rejects_unknown_prior(db_session) -> None:
    session, chart = db_session
    with pytest.raises(prior_ecg_service.PriorEcgValidationError):
        await prior_ecg_service.record_comparison(
            session,
            tenant_id="t1",
            chart_id=chart.id,
            user_id="provider-7",
            prior_ecg_id=str(uuid4()),
            comparison_state="similar",
        )
