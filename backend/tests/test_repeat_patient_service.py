"""Service-level tests for :class:`RepeatPatientService`.

Validates:
- ``find_matches`` discovers candidates by DOB + last_name + phone tail,
  populates ``match_reason_json`` per matched field, and produces a
  numeric confidence that reflects the documented per-field weights.
- ``review`` performs the documented state transition and writes a
  ``repeat_patient.reviewed`` audit row.
- ``list_prior_charts`` returns prior chart references for the matched
  profile's chart.
- ``carry_forward`` writes a ``repeat_patient.carry_forward`` audit row
  and updates the active chart's :class:`PatientProfile` only when the
  match has been explicitly reviewed and approved.
- An un-reviewed match causes carry_forward to raise and mutate nothing.
"""

from __future__ import annotations

import json
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
    EpcrPriorChartReference,
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
        # Active chart + its (empty) PatientProfile.
        active_chart = Chart(
            id=str(uuid4()),
            tenant_id="t1",
            call_number="CALL-ACTIVE",
            incident_type="medical",
            status=ChartStatus.NEW,
            created_by_user_id="user-1",
        )
        prior_chart = Chart(
            id=str(uuid4()),
            tenant_id="t1",
            call_number="CALL-PRIOR",
            incident_type="medical",
            status=ChartStatus.FINALIZED,
            created_by_user_id="user-0",
        )
        other_tenant_chart = Chart(
            id=str(uuid4()),
            tenant_id="t2",
            call_number="CALL-OTHER",
            incident_type="medical",
            status=ChartStatus.FINALIZED,
            created_by_user_id="user-9",
        )
        session.add_all([active_chart, prior_chart, other_tenant_chart])
        await session.flush()

        active_profile = PatientProfile(
            id=str(uuid4()),
            chart_id=active_chart.id,
            tenant_id="t1",
            last_name=None,
            first_name=None,
            date_of_birth=None,
            phone_number=None,
        )
        prior_profile = PatientProfile(
            id=str(uuid4()),
            chart_id=prior_chart.id,
            tenant_id="t1",
            first_name="Jane",
            last_name="Doe",
            date_of_birth="1980-04-12",
            phone_number="555-867-5309",
            sex="F",
        )
        other_tenant_profile = PatientProfile(
            id=str(uuid4()),
            chart_id=other_tenant_chart.id,
            tenant_id="t2",
            first_name="Jane",
            last_name="Doe",
            date_of_birth="1980-04-12",
            phone_number="555-867-5309",
        )
        session.add_all(
            [active_profile, prior_profile, other_tenant_profile]
        )
        await session.commit()
        yield {
            "session": session,
            "active_chart": active_chart,
            "prior_chart": prior_chart,
            "active_profile": active_profile,
            "prior_profile": prior_profile,
        }
    await engine.dispose()


async def _audit_actions(session: AsyncSession, chart_id: str) -> list[str]:
    rows = (
        await session.execute(
            select(EpcrAuditLog).where(EpcrAuditLog.chart_id == chart_id)
        )
    ).scalars().all()
    return [r.action for r in rows]


async def test_find_matches_populates_match_reason_and_confidence(db_setup):
    s = db_setup["session"]
    active_chart = db_setup["active_chart"]
    prior_profile = db_setup["prior_profile"]

    matches = await RepeatPatientService.find_matches(
        s,
        tenant_id="t1",
        chart_id=active_chart.id,
        current_patient={
            "last_name": "doe",  # case-insensitive equality
            "date_of_birth": "1980-04-12",
            "phone_number": "(212) 555 5309",  # last 4 = 5309
        },
    )
    await s.commit()

    assert len(matches) == 1
    m = matches[0]
    assert m.matched_profile_id == prior_profile.id

    # Per-field weights: dob 0.45 + last_name 0.35 + phone_last4 0.20 = 1.00
    assert float(m.confidence) == pytest.approx(1.00)

    reasons = json.loads(m.match_reason_json)
    fields = sorted(r["field"] for r in reasons)
    assert fields == ["date_of_birth", "last_name", "phone_last4"]

    # Tenant isolation: t2 profile must not match.
    t2_matches = (
        await s.execute(
            select(EpcrRepeatPatientMatch).where(
                EpcrRepeatPatientMatch.tenant_id == "t2"
            )
        )
    ).scalars().all()
    assert t2_matches == []


async def test_find_matches_partial_confidence(db_setup):
    s = db_setup["session"]
    active_chart = db_setup["active_chart"]

    matches = await RepeatPatientService.find_matches(
        s,
        tenant_id="t1",
        chart_id=active_chart.id,
        current_patient={
            "last_name": "Doe",  # match
            "date_of_birth": "1999-01-01",  # mismatch
            "phone_number": "555-000-0000",  # mismatch on tail
        },
    )
    await s.commit()
    assert len(matches) == 1
    # Only last_name (0.35) matches.
    assert float(matches[0].confidence) == pytest.approx(0.35)


async def test_find_matches_writes_prior_chart_reference(db_setup):
    s = db_setup["session"]
    active_chart = db_setup["active_chart"]
    prior_chart = db_setup["prior_chart"]

    await RepeatPatientService.find_matches(
        s,
        tenant_id="t1",
        chart_id=active_chart.id,
        current_patient={
            "last_name": "Doe",
            "date_of_birth": "1980-04-12",
            "phone_number": "5309",
        },
    )
    await s.commit()

    refs = (
        await s.execute(
            select(EpcrPriorChartReference).where(
                EpcrPriorChartReference.chart_id == active_chart.id
            )
        )
    ).scalars().all()
    assert len(refs) == 1
    assert refs[0].prior_chart_id == prior_chart.id


async def test_review_state_transitions_and_audits(db_setup):
    s = db_setup["session"]
    active_chart = db_setup["active_chart"]

    matches = await RepeatPatientService.find_matches(
        s,
        tenant_id="t1",
        chart_id=active_chart.id,
        current_patient={
            "last_name": "Doe",
            "date_of_birth": "1980-04-12",
            "phone_number": "5309",
        },
    )
    await s.commit()
    m = matches[0]
    assert m.reviewed is False
    assert m.carry_forward_allowed is False

    reviewed = await RepeatPatientService.review(
        s,
        tenant_id="t1",
        chart_id=active_chart.id,
        user_id="provider-1",
        match_id=m.id,
        carry_forward_allowed=True,
    )
    await s.commit()
    assert reviewed.reviewed is True
    assert reviewed.reviewed_by == "provider-1"
    assert reviewed.reviewed_at is not None
    assert reviewed.carry_forward_allowed is True

    actions = await _audit_actions(s, active_chart.id)
    assert "repeat_patient.reviewed" in actions


async def test_list_prior_charts_returns_references(db_setup):
    s = db_setup["session"]
    active_chart = db_setup["active_chart"]
    prior_profile = db_setup["prior_profile"]

    await RepeatPatientService.find_matches(
        s,
        tenant_id="t1",
        chart_id=active_chart.id,
        current_patient={
            "last_name": "Doe",
            "date_of_birth": "1980-04-12",
            "phone_number": "5309",
        },
    )
    await s.commit()

    refs = await RepeatPatientService.list_prior_charts(
        s, tenant_id="t1", matched_profile_id=prior_profile.id
    )
    assert len(refs) == 1
    assert refs[0].prior_chart_id == prior_profile.chart_id


async def test_carry_forward_happy_path(db_setup):
    s = db_setup["session"]
    active_chart = db_setup["active_chart"]
    active_profile = db_setup["active_profile"]

    matches = await RepeatPatientService.find_matches(
        s,
        tenant_id="t1",
        chart_id=active_chart.id,
        current_patient={
            "last_name": "Doe",
            "date_of_birth": "1980-04-12",
            "phone_number": "5309",
        },
    )
    await s.commit()
    m = matches[0]

    await RepeatPatientService.review(
        s,
        tenant_id="t1",
        chart_id=active_chart.id,
        user_id="provider-1",
        match_id=m.id,
        carry_forward_allowed=True,
    )
    await s.commit()

    result = await RepeatPatientService.carry_forward(
        s,
        tenant_id="t1",
        chart_id=active_chart.id,
        user_id="provider-1",
        source_field="last_name",
        target_field="last_name",
        match_id=m.id,
    )
    await s.commit()

    assert result["value"] == "Doe"
    refreshed = (
        await s.execute(
            select(PatientProfile).where(
                PatientProfile.id == active_profile.id
            )
        )
    ).scalar_one()
    assert refreshed.last_name == "Doe"

    actions = await _audit_actions(s, active_chart.id)
    assert "repeat_patient.carry_forward" in actions


async def test_carry_forward_without_review_raises(db_setup):
    s = db_setup["session"]
    active_chart = db_setup["active_chart"]

    matches = await RepeatPatientService.find_matches(
        s,
        tenant_id="t1",
        chart_id=active_chart.id,
        current_patient={
            "last_name": "Doe",
            "date_of_birth": "1980-04-12",
            "phone_number": "5309",
        },
    )
    await s.commit()
    m = matches[0]

    with pytest.raises(RepeatPatientReviewRequiredError):
        await RepeatPatientService.carry_forward(
            s,
            tenant_id="t1",
            chart_id=active_chart.id,
            user_id="provider-1",
            source_field="last_name",
            target_field="last_name",
            match_id=m.id,
        )
