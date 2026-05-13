"""Service-level tests for
:class:`epcr_app.services.provider_override_service.ProviderOverrideService`.

Covers:
- :meth:`record` happy-path + audit row.
- :meth:`record` minimum-length validation.
- :meth:`record` canonical ``kind`` validation.
- :meth:`request_supervisor` + audit row.
- :meth:`supervisor_confirm` + audit row + supervisor-mismatch guard.
- :meth:`list_for_chart` chronological output.
"""

from __future__ import annotations

import json
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
    EpcrProviderOverride,
)
from epcr_app.services.provider_override_service import (
    ProviderOverrideService,
    ProviderOverrideValidationError,
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
            tenant_id="t-srv",
            call_number="CALL-SRV",
            incident_type="medical",
            status=ChartStatus.NEW,
            created_by_user_id="user-srv",
        )
        session.add(chart)
        await session.commit()
        yield session, chart
    await engine.dispose()


async def _audit_actions(session, chart_id):
    rows = (
        await session.execute(
            select(EpcrAuditLog)
            .where(EpcrAuditLog.chart_id == chart_id)
            .order_by(EpcrAuditLog.performed_at, EpcrAuditLog.id)
        )
    ).scalars().all()
    return [r.action for r in rows]


@pytest.mark.asyncio
async def test_record_happy_path_persists_and_audits(db_setup):
    session, chart = db_setup
    result = await ProviderOverrideService.record(
        session=session,
        tenant_id=chart.tenant_id,
        chart_id=chart.id,
        user_id="user-srv",
        section="vitals",
        field_key="systolic_bp",
        kind="validation_warning",
        reason_text="Patient with documented chronic hypertension",
    )
    await session.commit()

    assert result["section"] == "vitals"
    assert result["fieldKey"] == "systolic_bp"
    assert result["kind"] == "validation_warning"
    assert result["overrodeBy"] == "user-srv"
    assert result["supervisorId"] is None
    assert result["supervisorConfirmedAt"] is None

    rows = (
        await session.execute(select(EpcrProviderOverride))
    ).scalars().all()
    assert len(rows) == 1

    audit = (
        await session.execute(
            select(EpcrAuditLog).where(
                EpcrAuditLog.action == "provider_override.recorded"
            )
        )
    ).scalars().all()
    assert len(audit) == 1
    detail = json.loads(audit[0].detail_json)
    assert detail["override_id"] == result["id"]
    assert detail["kind"] == "validation_warning"


@pytest.mark.asyncio
async def test_record_rejects_short_reason(db_setup):
    session, chart = db_setup
    with pytest.raises(ProviderOverrideValidationError) as exc:
        await ProviderOverrideService.record(
            session=session,
            tenant_id=chart.tenant_id,
            chart_id=chart.id,
            user_id="user-srv",
            section="vitals",
            field_key="systolic_bp",
            kind="validation_warning",
            reason_text="2short",  # 6 chars after strip
        )
    assert exc.value.field == "reason_text"


@pytest.mark.asyncio
async def test_record_rejects_unknown_kind(db_setup):
    session, chart = db_setup
    with pytest.raises(ProviderOverrideValidationError) as exc:
        await ProviderOverrideService.record(
            session=session,
            tenant_id=chart.tenant_id,
            chart_id=chart.id,
            user_id="user-srv",
            section="vitals",
            field_key="systolic_bp",
            kind="not_a_real_kind",
            reason_text="Long enough reason text here",
        )
    assert exc.value.field == "kind"


@pytest.mark.asyncio
async def test_request_supervisor_sets_pending_and_audits(db_setup):
    session, chart = db_setup
    rec = await ProviderOverrideService.record(
        session=session,
        tenant_id=chart.tenant_id,
        chart_id=chart.id,
        user_id="user-srv",
        section="medications",
        field_key="dose_outside_protocol",
        kind="lock_blocker",
        reason_text="Online medical control authorized this dose",
    )
    updated = await ProviderOverrideService.request_supervisor(
        session=session,
        tenant_id=chart.tenant_id,
        chart_id=chart.id,
        user_id="user-srv",
        override_id=rec["id"],
        supervisor_id="sup-42",
    )
    await session.commit()

    assert updated["supervisorId"] == "sup-42"
    assert updated["supervisorConfirmedAt"] is None

    actions = await _audit_actions(session, chart.id)
    assert "provider_override.recorded" in actions
    assert "provider_override.supervisor_requested" in actions


@pytest.mark.asyncio
async def test_supervisor_confirm_sets_timestamp_and_audits(db_setup):
    session, chart = db_setup
    rec = await ProviderOverrideService.record(
        session=session,
        tenant_id=chart.tenant_id,
        chart_id=chart.id,
        user_id="user-srv",
        section="medications",
        field_key="dose_outside_protocol",
        kind="lock_blocker",
        reason_text="Online medical control authorized this dose",
    )
    await ProviderOverrideService.request_supervisor(
        session=session,
        tenant_id=chart.tenant_id,
        chart_id=chart.id,
        user_id="user-srv",
        override_id=rec["id"],
        supervisor_id="sup-42",
    )
    confirmed = await ProviderOverrideService.supervisor_confirm(
        session=session,
        tenant_id=chart.tenant_id,
        chart_id=chart.id,
        user_id="user-srv",
        override_id=rec["id"],
        supervisor_id="sup-42",
    )
    await session.commit()

    assert confirmed["supervisorConfirmedAt"] is not None

    actions = await _audit_actions(session, chart.id)
    assert "provider_override.supervisor_confirmed" in actions


@pytest.mark.asyncio
async def test_supervisor_confirm_rejects_mismatched_supervisor(db_setup):
    session, chart = db_setup
    rec = await ProviderOverrideService.record(
        session=session,
        tenant_id=chart.tenant_id,
        chart_id=chart.id,
        user_id="user-srv",
        section="medications",
        field_key="dose_outside_protocol",
        kind="lock_blocker",
        reason_text="Online medical control authorized this dose",
    )
    await ProviderOverrideService.request_supervisor(
        session=session,
        tenant_id=chart.tenant_id,
        chart_id=chart.id,
        user_id="user-srv",
        override_id=rec["id"],
        supervisor_id="sup-42",
    )
    with pytest.raises(ProviderOverrideValidationError) as exc:
        await ProviderOverrideService.supervisor_confirm(
            session=session,
            tenant_id=chart.tenant_id,
            chart_id=chart.id,
            user_id="user-srv",
            override_id=rec["id"],
            supervisor_id="someone-else",
        )
    assert exc.value.field == "supervisor_id"


@pytest.mark.asyncio
async def test_list_for_chart_returns_chronological(db_setup):
    session, chart = db_setup
    a = await ProviderOverrideService.record(
        session=session,
        tenant_id=chart.tenant_id,
        chart_id=chart.id,
        user_id="user-srv",
        section="vitals",
        field_key="systolic_bp",
        kind="validation_warning",
        reason_text="Reason number one is long enough",
    )
    b = await ProviderOverrideService.record(
        session=session,
        tenant_id=chart.tenant_id,
        chart_id=chart.id,
        user_id="user-srv",
        section="vitals",
        field_key="heart_rate",
        kind="state_required",
        reason_text="Reason number two is also long enough",
    )
    await session.commit()

    listing = await ProviderOverrideService.list_for_chart(
        session, chart.tenant_id, chart.id
    )
    ids = [item["id"] for item in listing]
    assert a["id"] in ids
    assert b["id"] in ids
    # Chronological: a precedes b
    assert ids.index(a["id"]) < ids.index(b["id"])
