"""Tests for
:class:`epcr_app.services.audit_trail_query_service.AuditTrailQueryService`.

Verifies chronological merge correctness across all three sources:
:class:`EpcrAuditLog`, :class:`EpcrAiAuditEvent`, and
:class:`EpcrProviderOverride`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
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
    EpcrAiAuditEvent,
    EpcrAuditLog,
    EpcrProviderOverride,
)
from epcr_app.services.audit_trail_query_service import (
    AuditTrailQueryService,
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
            tenant_id="t-merge",
            call_number="CALL-MERGE",
            incident_type="medical",
            status=ChartStatus.NEW,
            created_by_user_id="user-merge",
        )
        session.add(chart)
        await session.commit()
        yield session, chart
    await engine.dispose()


@pytest.mark.asyncio
async def test_merge_is_chronological_across_sources(db_setup):
    session, chart = db_setup
    base = datetime(2026, 5, 12, 12, 0, 0, tzinfo=UTC)

    # t0 -> audit_log
    log_row = EpcrAuditLog(
        id="log-1",
        chart_id=chart.id,
        tenant_id=chart.tenant_id,
        user_id="user-merge",
        action="chart.created",
        detail_json=json.dumps({"who": "user-merge"}),
        performed_at=base,
    )
    # t1 -> ai_audit_event
    ai_row = EpcrAiAuditEvent(
        id="ai-1",
        chart_id=chart.id,
        tenant_id=chart.tenant_id,
        event_kind="narrative.draft",
        user_id="user-merge",
        payload_json=json.dumps({"narrative_id": "nar-1"}),
        performed_at=base + timedelta(minutes=1),
    )
    # t2 -> provider_override
    po_row = EpcrProviderOverride(
        id="po-1",
        tenant_id=chart.tenant_id,
        chart_id=chart.id,
        section="vitals",
        field_key="systolic_bp",
        kind="validation_warning",
        reason_text="Chronic hypertension on file",
        overrode_at=base + timedelta(minutes=2),
        overrode_by="user-merge",
        created_at=base + timedelta(minutes=2),
    )
    # t3 -> another audit_log
    log_row2 = EpcrAuditLog(
        id="log-2",
        chart_id=chart.id,
        tenant_id=chart.tenant_id,
        user_id="user-merge",
        action="chart.updated",
        detail_json=json.dumps({"field": "vitals"}),
        performed_at=base + timedelta(minutes=3),
    )

    session.add_all([log_row, ai_row, po_row, log_row2])
    await session.commit()

    trail = await AuditTrailQueryService.list_for_chart(
        session, chart.tenant_id, chart.id
    )

    assert len(trail) == 4
    # Chronological ascending
    assert [t["id"] for t in trail] == ["log-1", "ai-1", "po-1", "log-2"]
    assert [t["source"] for t in trail] == [
        "audit_log",
        "ai_audit_event",
        "provider_override",
        "audit_log",
    ]
    assert [t["kind"] for t in trail] == [
        "chart.created",
        "narrative.draft",
        "provider_override.validation_warning",
        "chart.updated",
    ]

    # Payload is parsed JSON for audit_log + ai_audit_event, structured
    # dict for provider_override.
    assert trail[0]["payload"] == {"who": "user-merge"}
    assert trail[1]["payload"] == {"narrative_id": "nar-1"}
    assert trail[2]["payload"]["fieldKey"] == "systolic_bp"
    assert trail[2]["payload"]["reasonText"] == "Chronic hypertension on file"


@pytest.mark.asyncio
async def test_since_filter_applies_to_all_sources(db_setup):
    session, chart = db_setup
    base = datetime(2026, 5, 12, 12, 0, 0, tzinfo=UTC)
    session.add_all(
        [
            EpcrAuditLog(
                id="log-old",
                chart_id=chart.id,
                tenant_id=chart.tenant_id,
                user_id="u",
                action="chart.created",
                detail_json=None,
                performed_at=base,
            ),
            EpcrAuditLog(
                id="log-new",
                chart_id=chart.id,
                tenant_id=chart.tenant_id,
                user_id="u",
                action="chart.updated",
                detail_json=None,
                performed_at=base + timedelta(hours=1),
            ),
            EpcrProviderOverride(
                id="po-new",
                tenant_id=chart.tenant_id,
                chart_id=chart.id,
                section="vitals",
                field_key="hr",
                kind="state_required",
                reason_text="State required override reason",
                overrode_at=base + timedelta(hours=1, minutes=5),
                overrode_by="u",
                created_at=base + timedelta(hours=1, minutes=5),
            ),
        ]
    )
    await session.commit()

    trail = await AuditTrailQueryService.list_for_chart(
        session,
        chart.tenant_id,
        chart.id,
        since=base + timedelta(minutes=30),
    )
    ids = [t["id"] for t in trail]
    assert "log-old" not in ids
    assert set(ids) == {"log-new", "po-new"}


@pytest.mark.asyncio
async def test_limit_caps_returned_entries(db_setup):
    session, chart = db_setup
    base = datetime(2026, 5, 12, 12, 0, 0, tzinfo=UTC)
    rows = []
    for i in range(5):
        rows.append(
            EpcrAuditLog(
                id=f"log-{i}",
                chart_id=chart.id,
                tenant_id=chart.tenant_id,
                user_id="u",
                action=f"chart.event_{i}",
                detail_json=None,
                performed_at=base + timedelta(minutes=i),
            )
        )
    session.add_all(rows)
    await session.commit()

    trail = await AuditTrailQueryService.list_for_chart(
        session, chart.tenant_id, chart.id, limit=2
    )
    assert len(trail) == 2
    # Most recent 2 retained
    assert [t["id"] for t in trail] == ["log-3", "log-4"]


@pytest.mark.asyncio
async def test_tenant_isolation(db_setup):
    session, chart = db_setup
    base = datetime(2026, 5, 12, 12, 0, 0, tzinfo=UTC)
    session.add(
        EpcrAuditLog(
            id="log-other-tenant",
            chart_id=chart.id,
            tenant_id="t-other",
            user_id="u",
            action="chart.created",
            detail_json=None,
            performed_at=base,
        )
    )
    session.add(
        EpcrAuditLog(
            id="log-mine",
            chart_id=chart.id,
            tenant_id=chart.tenant_id,
            user_id="u",
            action="chart.created",
            detail_json=None,
            performed_at=base,
        )
    )
    await session.commit()

    trail = await AuditTrailQueryService.list_for_chart(
        session, chart.tenant_id, chart.id
    )
    ids = [t["id"] for t in trail]
    assert "log-mine" in ids
    assert "log-other-tenant" not in ids
