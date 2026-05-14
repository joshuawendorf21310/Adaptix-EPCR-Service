"""Model-level tests for :class:`EpcrSentenceEvidence` and
:class:`EpcrAiAuditEvent`.

Verifies both rows round-trip through the ORM with the documented
column shape and default values.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
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
    EpcrAiAuditEvent,
    EpcrSentenceEvidence,
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


async def test_sentence_evidence_round_trip(db_session) -> None:
    session, chart = db_session
    row = EpcrSentenceEvidence(
        id=str(uuid4()),
        tenant_id="t1",
        chart_id=chart.id,
        narrative_id="narr-1",
        sentence_index=0,
        sentence_text="Administered 0.4 mg nitroglycerin SL for chest pain.",
        evidence_kind="medication",
        evidence_ref_id="med-1",
        confidence=Decimal("0.87"),
    )
    session.add(row)
    await session.commit()

    fetched = (
        await session.execute(
            select(EpcrSentenceEvidence).where(EpcrSentenceEvidence.id == row.id)
        )
    ).scalar_one()
    assert fetched.tenant_id == "t1"
    assert fetched.chart_id == chart.id
    assert fetched.narrative_id == "narr-1"
    assert fetched.sentence_index == 0
    assert "nitroglycerin" in fetched.sentence_text
    assert fetched.evidence_kind == "medication"
    assert fetched.evidence_ref_id == "med-1"
    assert Decimal(str(fetched.confidence)) == Decimal("0.87")
    assert fetched.provider_confirmed is False
    assert fetched.created_at is not None
    assert fetched.updated_at is not None


async def test_sentence_evidence_provider_confirmed_toggles(db_session) -> None:
    session, chart = db_session
    row = EpcrSentenceEvidence(
        id=str(uuid4()),
        tenant_id="t1",
        chart_id=chart.id,
        narrative_id=None,
        sentence_index=3,
        sentence_text="Vitals reassessed enroute.",
        evidence_kind="vital",
        evidence_ref_id="vit-9",
        confidence=Decimal("0.42"),
    )
    session.add(row)
    await session.commit()
    assert row.provider_confirmed is False

    row.provider_confirmed = True
    await session.commit()

    fetched = (
        await session.execute(
            select(EpcrSentenceEvidence).where(EpcrSentenceEvidence.id == row.id)
        )
    ).scalar_one()
    assert fetched.provider_confirmed is True


async def test_ai_audit_event_round_trip(db_session) -> None:
    session, chart = db_session
    payload = {"narrative_id": "narr-1", "count": 4}
    row = EpcrAiAuditEvent(
        id=str(uuid4()),
        tenant_id="t1",
        chart_id=chart.id,
        event_kind="sentence.evidence_added",
        user_id="user-1",
        payload_json=json.dumps(payload, sort_keys=True),
        performed_at=datetime.now(UTC),
    )
    session.add(row)
    await session.commit()

    fetched = (
        await session.execute(
            select(EpcrAiAuditEvent).where(EpcrAiAuditEvent.id == row.id)
        )
    ).scalar_one()
    assert fetched.tenant_id == "t1"
    assert fetched.chart_id == chart.id
    assert fetched.event_kind == "sentence.evidence_added"
    assert fetched.user_id == "user-1"
    assert json.loads(fetched.payload_json) == payload
    assert fetched.performed_at is not None
