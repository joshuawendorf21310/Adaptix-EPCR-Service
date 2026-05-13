"""Service-level tests for :class:`ProtocolContextService`.

Covers:

* ``engage`` creates an active context, emits a ``protocol.engaged``
  audit row, and computes a satisfaction snapshot whose shape is
  compatible with the lock-readiness payload contract.
* Re-engaging a pack supersedes the prior active context (only one row
  with ``disengaged_at IS NULL`` at a time).
* ``disengage`` closes the active context and emits a
  ``protocol.disengaged`` audit row.
* ``evaluate_required_field_satisfaction`` honestly counts NEMSIS-tagged
  audit events as the populated-element source, including the
  no-pack-engaged and unknown-pack edge cases.
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

from epcr_app.ai_clinical_engine import PROTOCOL_PACKS
from epcr_app.models import (
    Base,
    Chart,
    ChartStatus,
    EpcrAuditLog,
    EpcrProtocolContext,
)
from epcr_app.models_audit import ChartFieldAuditEvent
from epcr_app.services.protocol_context_service import (
    ProtocolContextService,
    supported_pack_keys,
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
            tenant_id="tenant-A",
            call_number="CALL-SVC-1",
            incident_type="medical",
            status=ChartStatus.NEW,
            created_by_user_id="user-1",
        )
        session.add(chart)
        await session.commit()
        yield session, chart
    await engine.dispose()


def _add_field_audit(
    session: AsyncSession,
    *,
    tenant_id: str,
    chart_id: str,
    nemsis_element: str,
    new_value: str = "value",
) -> None:
    session.add(
        ChartFieldAuditEvent(
            id=str(uuid4()),
            chart_id=chart_id,
            tenant_id=tenant_id,
            section="eVitals",
            nemsis_element=nemsis_element,
            field_key=f"fk-{nemsis_element}",
            prior_value=None,
            new_value=new_value,
            source_type="manual_entry",
            actor_id="user-1",
            actor_role="provider",
        )
    )


# ----------------------------------------------------------------------
# engage / list_active / audit
# ----------------------------------------------------------------------


async def test_engage_creates_active_context_and_audit(db_session) -> None:
    session, chart = db_session

    ctx = await ProtocolContextService.engage(
        session,
        tenant_id="tenant-A",
        chart_id=chart.id,
        user_id="user-1",
        pack="ACLS",
    )
    await session.commit()

    assert ctx.active_pack == "ACLS"
    assert ctx.disengaged_at is None
    assert ctx.engaged_by == "user-1"
    assert ctx.pack_version.startswith("engine:")
    # Snapshot is persisted as JSON in the expected shape.
    snap = json.loads(ctx.required_field_satisfaction_json)
    for key in (
        "score",
        "blockers",
        "warnings",
        "advisories",
        "generated_at",
        "active_pack",
        "pack_known",
        "satisfied_fields",
        "missing_fields",
        "required_total",
        "required_present",
    ):
        assert key in snap
    assert snap["active_pack"] == "ACLS"
    assert snap["pack_known"] is True

    # list_active returns this row.
    active = await ProtocolContextService.list_active(
        session, "tenant-A", chart.id
    )
    assert active is not None
    assert active.id == ctx.id

    # An audit row was emitted with action 'protocol.engaged'.
    audits = (
        await session.execute(
            select(EpcrAuditLog).where(
                EpcrAuditLog.chart_id == chart.id,
                EpcrAuditLog.tenant_id == "tenant-A",
                EpcrAuditLog.action == "protocol.engaged",
            )
        )
    ).scalars().all()
    assert len(audits) == 1
    detail = json.loads(audits[0].detail_json)
    assert detail["active_pack"] == "ACLS"
    assert detail["context_id"] == ctx.id
    assert detail["pack_known"] is True


async def test_engage_supersedes_prior_active(db_session) -> None:
    session, chart = db_session
    first = await ProtocolContextService.engage(
        session,
        tenant_id="tenant-A",
        chart_id=chart.id,
        user_id="user-1",
        pack="ACLS",
    )
    await session.commit()

    second = await ProtocolContextService.engage(
        session,
        tenant_id="tenant-A",
        chart_id=chart.id,
        user_id="user-2",
        pack="STEMI",
    )
    await session.commit()

    await session.refresh(first)
    assert first.disengaged_at is not None
    assert second.disengaged_at is None
    assert second.active_pack == "STEMI"

    # Only one active row.
    active_rows = (
        await session.execute(
            select(EpcrProtocolContext).where(
                EpcrProtocolContext.chart_id == chart.id,
                EpcrProtocolContext.disengaged_at.is_(None),
            )
        )
    ).scalars().all()
    assert len(active_rows) == 1
    assert active_rows[0].id == second.id

    # The supersede emitted a protocol.disengaged audit row plus two
    # engage rows.
    disengaged = (
        await session.execute(
            select(EpcrAuditLog).where(
                EpcrAuditLog.chart_id == chart.id,
                EpcrAuditLog.action == "protocol.disengaged",
            )
        )
    ).scalars().all()
    assert len(disengaged) == 1
    detail = json.loads(disengaged[0].detail_json)
    assert detail["reason"] == "superseded_by_engage"
    assert detail["superseded_by_pack"] == "STEMI"


async def test_engage_requires_non_empty_pack(db_session) -> None:
    session, chart = db_session
    with pytest.raises(ValueError):
        await ProtocolContextService.engage(
            session,
            tenant_id="tenant-A",
            chart_id=chart.id,
            user_id="user-1",
            pack="",
        )


# ----------------------------------------------------------------------
# disengage
# ----------------------------------------------------------------------


async def test_disengage_closes_active_context_and_audits(db_session) -> None:
    session, chart = db_session
    ctx = await ProtocolContextService.engage(
        session,
        tenant_id="tenant-A",
        chart_id=chart.id,
        user_id="user-1",
        pack="ACLS",
    )
    await session.commit()

    closed = await ProtocolContextService.disengage(
        session,
        tenant_id="tenant-A",
        chart_id=chart.id,
        user_id="user-1",
        reason="patient_handoff",
    )
    await session.commit()

    assert closed is not None
    assert closed.id == ctx.id
    assert closed.disengaged_at is not None
    assert (
        await ProtocolContextService.list_active(
            session, "tenant-A", chart.id
        )
        is None
    )

    audits = (
        await session.execute(
            select(EpcrAuditLog).where(
                EpcrAuditLog.chart_id == chart.id,
                EpcrAuditLog.action == "protocol.disengaged",
            )
        )
    ).scalars().all()
    assert len(audits) == 1
    detail = json.loads(audits[0].detail_json)
    assert detail["reason"] == "patient_handoff"
    assert detail["noop"] is False
    assert detail["context_id"] == ctx.id


async def test_disengage_noop_when_no_active_context_still_audits(
    db_session,
) -> None:
    session, chart = db_session
    result = await ProtocolContextService.disengage(
        session,
        tenant_id="tenant-A",
        chart_id=chart.id,
        user_id="user-1",
        reason="cleared_after_review",
    )
    await session.commit()
    assert result is None

    audits = (
        await session.execute(
            select(EpcrAuditLog).where(
                EpcrAuditLog.chart_id == chart.id,
                EpcrAuditLog.action == "protocol.disengaged",
            )
        )
    ).scalars().all()
    assert len(audits) == 1
    assert json.loads(audits[0].detail_json)["noop"] is True


async def test_disengage_requires_reason(db_session) -> None:
    session, chart = db_session
    with pytest.raises(ValueError):
        await ProtocolContextService.disengage(
            session,
            tenant_id="tenant-A",
            chart_id=chart.id,
            user_id="user-1",
            reason="",
        )


# ----------------------------------------------------------------------
# evaluate_required_field_satisfaction
# ----------------------------------------------------------------------


def _expected_shape_keys() -> set[str]:
    return {
        "score",
        "blockers",
        "warnings",
        "advisories",
        "generated_at",
        "active_pack",
        "pack_known",
        "satisfied_fields",
        "missing_fields",
        "required_total",
        "required_present",
    }


async def test_satisfaction_no_active_pack(db_session) -> None:
    session, chart = db_session
    payload = await ProtocolContextService.evaluate_required_field_satisfaction(
        session, "tenant-A", chart.id
    )
    assert set(payload.keys()) >= _expected_shape_keys()
    assert payload["active_pack"] is None
    assert payload["pack_known"] is False
    assert payload["score"] == 1.0
    assert payload["blockers"] == []
    assert payload["missing_fields"] == []
    assert payload["satisfied_fields"] == []
    assert any(
        a["kind"] == "no_active_pack" for a in payload["advisories"]
    )


async def test_satisfaction_known_pack_counts_audit_events(db_session) -> None:
    session, chart = db_session

    # Engage ACLS (known pack with required_fields:
    # eVitals.03, eVitals.10, eMedications.03, eProcedures.03, eArrest.01).
    await ProtocolContextService.engage(
        session,
        tenant_id="tenant-A",
        chart_id=chart.id,
        user_id="user-1",
        pack="ACLS",
    )
    # Populate two of the five required NEMSIS elements via audit log.
    _add_field_audit(
        session,
        tenant_id="tenant-A",
        chart_id=chart.id,
        nemsis_element="eVitals.03",
        new_value="120/80",
    )
    _add_field_audit(
        session,
        tenant_id="tenant-A",
        chart_id=chart.id,
        nemsis_element="eMedications.03",
        new_value="epinephrine",
    )
    # An empty-value audit row must NOT count.
    _add_field_audit(
        session,
        tenant_id="tenant-A",
        chart_id=chart.id,
        nemsis_element="eArrest.01",
        new_value="",
    )
    await session.commit()

    payload = await ProtocolContextService.evaluate_required_field_satisfaction(
        session, "tenant-A", chart.id
    )
    assert set(payload.keys()) >= _expected_shape_keys()
    assert payload["active_pack"] == "ACLS"
    assert payload["pack_known"] is True
    assert payload["required_total"] == 5
    assert payload["required_present"] == 2
    assert set(payload["satisfied_fields"]) == {
        "eVitals.03",
        "eMedications.03",
    }
    assert set(payload["missing_fields"]) == {
        "eVitals.10",
        "eProcedures.03",
        "eArrest.01",
    }
    # Blockers force score to 0.0 (honest — partial coverage is not "ready").
    assert payload["score"] == 0.0
    assert all(
        b["kind"] == "missing_protocol_required_field"
        for b in payload["blockers"]
    )
    # A protocol_partial warning is present.
    assert any(
        w["kind"] == "protocol_partial" for w in payload["warnings"]
    )


async def test_satisfaction_known_pack_all_fields_populated(db_session) -> None:
    session, chart = db_session

    await ProtocolContextService.engage(
        session,
        tenant_id="tenant-A",
        chart_id=chart.id,
        user_id="user-1",
        pack="ACLS",
    )
    for field_id in PROTOCOL_PACKS["ACLS"]["required_fields"]:
        _add_field_audit(
            session,
            tenant_id="tenant-A",
            chart_id=chart.id,
            nemsis_element=field_id,
            new_value="captured",
        )
    await session.commit()

    payload = await ProtocolContextService.evaluate_required_field_satisfaction(
        session, "tenant-A", chart.id
    )
    assert payload["required_present"] == payload["required_total"]
    assert payload["missing_fields"] == []
    assert payload["blockers"] == []
    assert payload["score"] == 1.0


async def test_satisfaction_unknown_pack_returns_advisory(db_session) -> None:
    session, chart = db_session
    # Engage a pack key that is intentionally not present in the engine
    # registry. NRP and CCT are documented in the model contract but
    # are not in PROTOCOL_PACKS at engine version pinned for this build.
    candidates = [k for k in ("NRP", "CCT") if k not in PROTOCOL_PACKS]
    assert candidates, (
        "Test relies on at least one model-contract pack key being "
        "absent from the engine registry. Update test if the engine "
        "now includes both NRP and CCT."
    )
    pack_key = candidates[0]

    await ProtocolContextService.engage(
        session,
        tenant_id="tenant-A",
        chart_id=chart.id,
        user_id="user-1",
        pack=pack_key,
    )
    await session.commit()

    payload = await ProtocolContextService.evaluate_required_field_satisfaction(
        session, "tenant-A", chart.id
    )
    assert payload["active_pack"] == pack_key
    assert payload["pack_known"] is False
    assert payload["required_total"] == 0
    assert payload["required_present"] == 0
    assert payload["satisfied_fields"] == []
    assert payload["missing_fields"] == []
    assert payload["score"] == 0.0  # honest: cannot evaluate
    assert any(
        a["kind"] == "pack_unknown" for a in payload["advisories"]
    )


async def test_supported_pack_keys_reflects_engine_registry() -> None:
    keys = tuple(supported_pack_keys())
    assert set(keys) == set(PROTOCOL_PACKS.keys())
