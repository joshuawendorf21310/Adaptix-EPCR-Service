"""Hard-rule test: carry_forward must NEVER overwrite without provider review.

This file pins the regression. Even if upstream code changes how matches
are discovered or persisted, the carry-forward gate must continue to:

- refuse on an un-reviewed match,
- refuse on a reviewed-but-not-approved match (reviewed=True,
  carry_forward_allowed=False),
- leave the active chart's :class:`PatientProfile` untouched on refusal,
- write no ``repeat_patient.carry_forward`` audit row on refusal.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
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
    EpcrRepeatPatientMatch,
    PatientProfile,
)
from epcr_app.services.repeat_patient_service import (
    RepeatPatientReviewRequiredError,
    RepeatPatientService,
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
        active_chart = Chart(
            id=str(uuid4()),
            tenant_id="t1",
            call_number="CALL-NO-OVERWRITE",
            incident_type="medical",
            status=ChartStatus.NEW,
            created_by_user_id="user-1",
        )
        prior_chart = Chart(
            id=str(uuid4()),
            tenant_id="t1",
            call_number="CALL-PRIOR-NO-OVERWRITE",
            incident_type="medical",
            status=ChartStatus.FINALIZED,
            created_by_user_id="user-0",
        )
        session.add_all([active_chart, prior_chart])
        await session.flush()

        active_profile = PatientProfile(
            id=str(uuid4()),
            chart_id=active_chart.id,
            tenant_id="t1",
            last_name="OriginalActive",
        )
        prior_profile = PatientProfile(
            id=str(uuid4()),
            chart_id=prior_chart.id,
            tenant_id="t1",
            last_name="Doe",
            date_of_birth="1980-04-12",
            phone_number="555-867-5309",
        )
        session.add_all([active_profile, prior_profile])

        # Seed a match row directly so the test does not depend on the
        # find_matches implementation. Default state: NOT reviewed.
        match = EpcrRepeatPatientMatch(
            id=str(uuid4()),
            tenant_id="t1",
            chart_id=active_chart.id,
            matched_profile_id=prior_profile.id,
            confidence=Decimal("0.80"),
            match_reason_json="[]",
            reviewed=False,
            carry_forward_allowed=False,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(match)
        await session.commit()

        yield {
            "session": session,
            "active_chart": active_chart,
            "active_profile": active_profile,
            "match": match,
        }
    await engine.dispose()


async def test_carry_forward_refuses_on_unreviewed_match(db_setup) -> None:
    s = db_setup["session"]
    active_chart = db_setup["active_chart"]
    active_profile = db_setup["active_profile"]
    match = db_setup["match"]

    assert match.reviewed is False
    assert match.carry_forward_allowed is False

    with pytest.raises(RepeatPatientReviewRequiredError):
        await RepeatPatientService.carry_forward(
            s,
            tenant_id="t1",
            chart_id=active_chart.id,
            user_id="provider-1",
            source_field="last_name",
            target_field="last_name",
            match_id=match.id,
        )

    # No mutation, no audit row.
    refreshed = (
        await s.execute(
            select(PatientProfile).where(PatientProfile.id == active_profile.id)
        )
    ).scalar_one()
    assert refreshed.last_name == "OriginalActive"

    audits = (
        await s.execute(
            select(EpcrAuditLog).where(
                EpcrAuditLog.chart_id == active_chart.id,
                EpcrAuditLog.action == "repeat_patient.carry_forward",
            )
        )
    ).scalars().all()
    assert audits == []


async def test_carry_forward_refuses_when_reviewed_but_not_approved(db_setup):
    s = db_setup["session"]
    active_chart = db_setup["active_chart"]
    active_profile = db_setup["active_profile"]
    match = db_setup["match"]

    # Provider reviewed but explicitly disallowed carry-forward.
    await RepeatPatientService.review(
        s,
        tenant_id="t1",
        chart_id=active_chart.id,
        user_id="provider-1",
        match_id=match.id,
        carry_forward_allowed=False,
    )
    await s.commit()

    with pytest.raises(RepeatPatientReviewRequiredError):
        await RepeatPatientService.carry_forward(
            s,
            tenant_id="t1",
            chart_id=active_chart.id,
            user_id="provider-1",
            source_field="last_name",
            target_field="last_name",
            match_id=match.id,
        )

    refreshed = (
        await s.execute(
            select(PatientProfile).where(PatientProfile.id == active_profile.id)
        )
    ).scalar_one()
    assert refreshed.last_name == "OriginalActive"
