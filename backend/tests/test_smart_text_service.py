"""Service-level tests for :mod:`epcr_app.services.smart_text_service`.

Covers:

- :func:`resolve_for_field` empty path: no rows for slot -> [].
- :func:`resolve_for_field` populated path: orders by confidence DESC,
  filters by tenant/chart/section/field_key, hides already-accepted /
  already-rejected rows.
- :func:`accept` writes ``smart_text.accepted`` audit row and flips
  ``accepted=True``.
- :func:`reject` writes ``smart_text.rejected`` audit row and flips
  ``accepted=False``.
- :func:`accept` / :func:`reject` raise ``LookupError`` on unknown
  suggestion id.
"""

from __future__ import annotations

import json
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
    EpcrSmartTextSuggestion,
)
from epcr_app.services import smart_text_service


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
            tenant_id="t1",
            call_number="CALL-SVC-1",
            incident_type="medical",
            status=ChartStatus.NEW,
            created_by_user_id="user-1",
        )
        session.add(chart)
        await session.commit()
        yield session, chart
    await engine.dispose()


async def _make_row(
    session: AsyncSession,
    chart_id: str,
    *,
    section: str = "narrative",
    field_key: str = "chief_complaint",
    source: str = "agency_library",
    confidence: float = 0.5,
    compliance_state: str = "approved",
    phrase: str = "Test phrase.",
    accepted=None,
) -> EpcrSmartTextSuggestion:
    now = datetime.now(UTC)
    row = EpcrSmartTextSuggestion(
        id=str(uuid4()),
        chart_id=chart_id,
        tenant_id="t1",
        section=section,
        field_key=field_key,
        phrase=phrase,
        source=source,
        confidence=Decimal(str(confidence)),
        compliance_state=compliance_state,
        accepted=accepted,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.flush()
    return row


# --------------------------- resolve_for_field --------------------------- #


async def test_resolve_empty_returns_empty_list(db_setup) -> None:
    session, chart = db_setup
    result = await smart_text_service.resolve_for_field(
        session,
        tenant_id="t1",
        chart_id=chart.id,
        section="narrative",
        field_key="chief_complaint",
    )
    assert result == []


async def test_resolve_populated_returns_ranked_offered_only(db_setup) -> None:
    session, chart = db_setup
    low = await _make_row(
        session, chart.id, confidence=0.3, phrase="low-conf"
    )
    high = await _make_row(
        session, chart.id, confidence=0.9, phrase="high-conf"
    )
    mid = await _make_row(
        session, chart.id, confidence=0.6, phrase="mid-conf"
    )
    # Already-accepted suggestion must NOT be returned by resolver.
    await _make_row(
        session,
        chart.id,
        confidence=0.95,
        phrase="already-accepted",
        accepted=True,
    )
    # Wrong slot must NOT be returned.
    await _make_row(
        session,
        chart.id,
        section="assessment",
        field_key="impression",
        confidence=0.99,
        phrase="wrong-slot",
    )
    # Wrong tenant must NOT be returned.
    other = EpcrSmartTextSuggestion(
        id=str(uuid4()),
        chart_id=chart.id,
        tenant_id="t-other",
        section="narrative",
        field_key="chief_complaint",
        phrase="wrong-tenant",
        source="agency_library",
        confidence=Decimal("0.99"),
        compliance_state="approved",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(other)
    await session.flush()

    result = await smart_text_service.resolve_for_field(
        session,
        tenant_id="t1",
        chart_id=chart.id,
        section="narrative",
        field_key="chief_complaint",
    )

    ids_in_order = [r["id"] for r in result]
    assert ids_in_order == [high.id, mid.id, low.id]
    for r in result:
        assert r["source"] in smart_text_service.ALLOWED_SOURCES
        assert r["complianceState"] in smart_text_service.ALLOWED_COMPLIANCE_STATES
        assert 0.0 <= r["confidence"] <= 1.0


# --------------------------- accept --------------------------- #


async def test_accept_flips_state_and_writes_audit(db_setup) -> None:
    session, chart = db_setup
    row = await _make_row(session, chart.id, confidence=0.8)

    result = await smart_text_service.accept(
        session,
        tenant_id="t1",
        chart_id=chart.id,
        user_id="user-1",
        suggestion_id=row.id,
    )

    assert result["accepted"] is True
    assert result["performedBy"] == "user-1"

    refreshed = (
        await session.execute(
            select(EpcrSmartTextSuggestion).where(
                EpcrSmartTextSuggestion.id == row.id
            )
        )
    ).scalar_one()
    assert refreshed.accepted is True
    assert refreshed.accepted_at is not None
    assert refreshed.performed_by == "user-1"

    audits = (
        await session.execute(
            select(EpcrAuditLog).where(
                EpcrAuditLog.action == "smart_text.accepted",
                EpcrAuditLog.chart_id == chart.id,
            )
        )
    ).scalars().all()
    assert len(audits) == 1
    entry = audits[0]
    assert entry.tenant_id == "t1"
    assert entry.user_id == "user-1"
    payload = json.loads(entry.detail_json)
    assert payload["suggestion_id"] == row.id
    assert payload["section"] == "narrative"
    assert payload["field_key"] == "chief_complaint"
    assert payload["source"] == "agency_library"
    assert payload["compliance_state"] == "approved"


# --------------------------- reject --------------------------- #


async def test_reject_flips_state_and_writes_audit(db_setup) -> None:
    session, chart = db_setup
    row = await _make_row(
        session, chart.id, source="ai", confidence=0.45, compliance_state="risk"
    )

    result = await smart_text_service.reject(
        session,
        tenant_id="t1",
        chart_id=chart.id,
        user_id="user-2",
        suggestion_id=row.id,
    )

    assert result["accepted"] is False
    assert result["performedBy"] == "user-2"

    refreshed = (
        await session.execute(
            select(EpcrSmartTextSuggestion).where(
                EpcrSmartTextSuggestion.id == row.id
            )
        )
    ).scalar_one()
    assert refreshed.accepted is False
    assert refreshed.performed_by == "user-2"

    audits = (
        await session.execute(
            select(EpcrAuditLog).where(
                EpcrAuditLog.action == "smart_text.rejected",
                EpcrAuditLog.chart_id == chart.id,
            )
        )
    ).scalars().all()
    assert len(audits) == 1
    payload = json.loads(audits[0].detail_json)
    assert payload["suggestion_id"] == row.id
    assert payload["source"] == "ai"
    assert payload["compliance_state"] == "risk"


async def test_accept_unknown_id_raises(db_setup) -> None:
    session, chart = db_setup
    with pytest.raises(LookupError):
        await smart_text_service.accept(
            session,
            tenant_id="t1",
            chart_id=chart.id,
            user_id="user-1",
            suggestion_id="does-not-exist",
        )


async def test_reject_unknown_id_raises(db_setup) -> None:
    session, chart = db_setup
    with pytest.raises(LookupError):
        await smart_text_service.reject(
            session,
            tenant_id="t1",
            chart_id=chart.id,
            user_id="user-1",
            suggestion_id="does-not-exist",
        )


async def test_accept_wrong_tenant_raises(db_setup) -> None:
    session, chart = db_setup
    row = await _make_row(session, chart.id)
    with pytest.raises(LookupError):
        await smart_text_service.accept(
            session,
            tenant_id="t-other",
            chart_id=chart.id,
            user_id="user-1",
            suggestion_id=row.id,
        )


# --------------------------- create_suggestion --------------------------- #


async def test_create_suggestion_validates_provenance(db_setup) -> None:
    session, chart = db_setup

    with pytest.raises(ValueError):
        await smart_text_service.create_suggestion(
            session,
            tenant_id="t1",
            chart_id=chart.id,
            section="narrative",
            field_key="hpi",
            phrase="x",
            source="bogus",
            confidence=0.5,
            compliance_state="approved",
        )
    with pytest.raises(ValueError):
        await smart_text_service.create_suggestion(
            session,
            tenant_id="t1",
            chart_id=chart.id,
            section="narrative",
            field_key="hpi",
            phrase="x",
            source="ai",
            confidence=2.0,
            compliance_state="approved",
        )
    with pytest.raises(ValueError):
        await smart_text_service.create_suggestion(
            session,
            tenant_id="t1",
            chart_id=chart.id,
            section="narrative",
            field_key="hpi",
            phrase="x",
            source="ai",
            confidence=0.5,
            compliance_state="bogus",
        )


async def test_create_suggestion_persists_row(db_setup) -> None:
    session, chart = db_setup
    row = await smart_text_service.create_suggestion(
        session,
        tenant_id="t1",
        chart_id=chart.id,
        section="narrative",
        field_key="hpi",
        phrase="Patient denies SOB.",
        source="ai",
        confidence=0.83,
        compliance_state="pending",
        evidence_link_id="ev-42",
    )
    assert row.id is not None
    assert row.accepted is None

    fetched = (
        await session.execute(
            select(EpcrSmartTextSuggestion).where(
                EpcrSmartTextSuggestion.id == row.id
            )
        )
    ).scalar_one()
    assert fetched.source == "ai"
    assert float(fetched.confidence) == pytest.approx(0.83)
    assert fetched.compliance_state == "pending"
    assert fetched.evidence_link_id == "ev-42"
