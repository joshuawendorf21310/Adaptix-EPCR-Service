"""Service-level tests for :class:`MultiPatientService`.

Covers the create / attach / detach lifecycle, audit emission for each
state change, and the sibling-listing contract returned by
``list_for_chart``.
"""

from __future__ import annotations

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
    EpcrMultiPatientIncident,
    EpcrMultiPatientLink,
)
from epcr_app.services.multi_patient_service import (
    MultiPatientService,
    MultiPatientServiceError,
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
        charts = []
        for idx in range(3):
            c = Chart(
                id=str(uuid4()),
                tenant_id="t1",
                call_number=f"CALL-MCI-{idx}",
                incident_type="medical",
                status=ChartStatus.NEW,
                created_by_user_id="user-1",
            )
            session.add(c)
            charts.append(c)
        await session.commit()
        yield session, charts
    await engine.dispose()


async def _audit_actions(session, chart_id: str) -> list[str]:
    rows = (
        await session.execute(
            select(EpcrAuditLog).where(EpcrAuditLog.chart_id == chart_id)
        )
    ).scalars().all()
    return [r.action for r in rows]


async def test_create_incident_persists_and_audits(db_setup) -> None:
    session, charts = db_setup
    result = await MultiPatientService.create_incident(
        session,
        tenant_id="t1",
        user_id="user-1",
        payload={
            "parentIncidentNumber": "INC-A",
            "sceneAddress": {"street": "1 Main St"},
            "mciFlag": True,
            "patientCount": 3,
            "mechanism": "explosion",
            "hazardsText": "structural collapse",
        },
        seed_chart_id=charts[0].id,
    )
    await session.commit()

    assert result["parentIncidentNumber"] == "INC-A"
    assert result["mciFlag"] is True
    assert result["patientCount"] == 3
    assert result["sceneAddress"] == {"street": "1 Main St"}
    assert result["mechanism"] == "explosion"

    rows = (
        await session.execute(select(EpcrMultiPatientIncident))
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].parent_incident_number == "INC-A"

    actions = await _audit_actions(session, charts[0].id)
    assert "multi_patient.incident_created" in actions


async def test_create_incident_requires_parent_incident_number(db_setup) -> None:
    session, _charts = db_setup
    with pytest.raises(MultiPatientServiceError):
        await MultiPatientService.create_incident(
            session,
            tenant_id="t1",
            user_id="user-1",
            payload={"mciFlag": True},
        )


async def test_attach_and_detach_chart_audits_and_soft_deletes(db_setup) -> None:
    session, charts = db_setup
    incident = await MultiPatientService.create_incident(
        session,
        tenant_id="t1",
        user_id="user-1",
        payload={"parentIncidentNumber": "INC-B", "patientCount": 2},
    )
    incident_id = incident["id"]

    link_a = await MultiPatientService.attach_chart(
        session,
        tenant_id="t1",
        user_id="user-1",
        incident_id=incident_id,
        chart_id=charts[0].id,
        patient_label="A",
        triage_category="red",
        acuity="critical",
        transport_priority="emergent",
        destination_id="HOSP-1",
    )
    await session.commit()
    assert link_a["patientLabel"] == "A"
    assert link_a["triageCategory"] == "red"
    assert link_a["removedAt"] is None

    actions_a = await _audit_actions(session, charts[0].id)
    assert "multi_patient.chart_attached" in actions_a

    # Detach via the link id.
    detached = await MultiPatientService.detach_chart(
        session,
        tenant_id="t1",
        user_id="user-1",
        link_id=link_a["id"],
    )
    await session.commit()
    assert detached["removedAt"] is not None

    actions_a2 = await _audit_actions(session, charts[0].id)
    assert "multi_patient.chart_detached" in actions_a2

    # The row is preserved in the DB (soft delete).
    row = (
        await session.execute(
            select(EpcrMultiPatientLink).where(
                EpcrMultiPatientLink.id == link_a["id"]
            )
        )
    ).scalar_one()
    assert row.removed_at is not None


async def test_attach_rejects_invalid_triage_and_duplicate(db_setup) -> None:
    session, charts = db_setup
    incident = await MultiPatientService.create_incident(
        session,
        tenant_id="t1",
        user_id="user-1",
        payload={"parentIncidentNumber": "INC-C"},
    )
    incident_id = incident["id"]

    with pytest.raises(MultiPatientServiceError):
        await MultiPatientService.attach_chart(
            session,
            tenant_id="t1",
            user_id="user-1",
            incident_id=incident_id,
            chart_id=charts[0].id,
            patient_label="A",
            triage_category="purple",  # invalid
        )

    await MultiPatientService.attach_chart(
        session,
        tenant_id="t1",
        user_id="user-1",
        incident_id=incident_id,
        chart_id=charts[0].id,
        patient_label="A",
    )
    # Duplicate live link for same (incident, chart) rejected.
    with pytest.raises(MultiPatientServiceError):
        await MultiPatientService.attach_chart(
            session,
            tenant_id="t1",
            user_id="user-1",
            incident_id=incident_id,
            chart_id=charts[0].id,
            patient_label="A2",
        )


async def test_attach_rejects_unknown_incident(db_setup) -> None:
    session, charts = db_setup
    with pytest.raises(MultiPatientServiceError):
        await MultiPatientService.attach_chart(
            session,
            tenant_id="t1",
            user_id="user-1",
            incident_id="does-not-exist",
            chart_id=charts[0].id,
            patient_label="A",
        )


async def test_list_for_chart_returns_incident_and_siblings(db_setup) -> None:
    session, charts = db_setup
    incident = await MultiPatientService.create_incident(
        session,
        tenant_id="t1",
        user_id="user-1",
        payload={"parentIncidentNumber": "INC-SIB", "patientCount": 3},
    )
    incident_id = incident["id"]

    await MultiPatientService.attach_chart(
        session, "t1", "user-1", incident_id, charts[0].id, "A",
        triage_category="red",
    )
    await MultiPatientService.attach_chart(
        session, "t1", "user-1", incident_id, charts[1].id, "B",
        triage_category="yellow",
    )
    await MultiPatientService.attach_chart(
        session, "t1", "user-1", incident_id, charts[2].id, "C",
        triage_category="green",
    )
    await session.commit()

    view = await MultiPatientService.list_for_chart(
        session, "t1", charts[0].id
    )
    assert view["incident"] is not None
    assert view["incident"]["parentIncidentNumber"] == "INC-SIB"
    assert view["self"] is not None
    assert view["self"]["chartId"] == charts[0].id
    assert view["self"]["patientLabel"] == "A"

    sibling_chart_ids = sorted([s["chartId"] for s in view["siblings"]])
    assert sibling_chart_ids == sorted([charts[1].id, charts[2].id])

    sibling_labels = sorted([s["patientLabel"] for s in view["siblings"]])
    assert sibling_labels == ["B", "C"]


async def test_list_for_chart_returns_empty_when_chart_unlinked(db_setup) -> None:
    session, charts = db_setup
    view = await MultiPatientService.list_for_chart(
        session, "t1", charts[0].id
    )
    assert view == {"incident": None, "self": None, "siblings": []}


async def test_detached_link_excluded_from_siblings(db_setup) -> None:
    session, charts = db_setup
    incident = await MultiPatientService.create_incident(
        session,
        tenant_id="t1",
        user_id="user-1",
        payload={"parentIncidentNumber": "INC-DET", "patientCount": 2},
    )
    incident_id = incident["id"]
    link_a = await MultiPatientService.attach_chart(
        session, "t1", "user-1", incident_id, charts[0].id, "A"
    )
    link_b = await MultiPatientService.attach_chart(
        session, "t1", "user-1", incident_id, charts[1].id, "B"
    )
    await MultiPatientService.detach_chart(
        session, "t1", "user-1", link_b["id"]
    )
    await session.commit()
    view = await MultiPatientService.list_for_chart(
        session, "t1", charts[0].id
    )
    assert view["self"]["id"] == link_a["id"]
    assert view["siblings"] == []


async def test_merge_incidents_repoints_links(db_setup) -> None:
    session, charts = db_setup
    src = await MultiPatientService.create_incident(
        session, "t1", "user-1",
        {"parentIncidentNumber": "INC-SRC", "patientCount": 1},
    )
    tgt = await MultiPatientService.create_incident(
        session, "t1", "user-1",
        {"parentIncidentNumber": "INC-TGT", "patientCount": 2},
    )
    await MultiPatientService.attach_chart(
        session, "t1", "user-1", src["id"], charts[0].id, "A"
    )
    await session.commit()

    result = await MultiPatientService.merge_incidents(
        session, "t1", "user-1", src["id"], tgt["id"]
    )
    await session.commit()
    assert result["moved"] == 1

    view = await MultiPatientService.list_for_chart(
        session, "t1", charts[0].id
    )
    assert view["incident"]["id"] == tgt["id"]


async def test_split_incident_creates_new_and_repoints(db_setup) -> None:
    session, charts = db_setup
    parent = await MultiPatientService.create_incident(
        session, "t1", "user-1",
        {"parentIncidentNumber": "INC-PARENT", "patientCount": 2},
    )
    link_a = await MultiPatientService.attach_chart(
        session, "t1", "user-1", parent["id"], charts[0].id, "A"
    )
    link_b = await MultiPatientService.attach_chart(
        session, "t1", "user-1", parent["id"], charts[1].id, "B"
    )
    await session.commit()

    out = await MultiPatientService.split_incident(
        session,
        "t1",
        "user-1",
        source_incident_id=parent["id"],
        link_ids=[link_b["id"]],
        new_incident_payload={"parentIncidentNumber": "INC-SPLIT"},
    )
    await session.commit()
    assert out["new_incident"]["parentIncidentNumber"] == "INC-SPLIT"
    assert link_b["id"] in out["moved_link_ids"]

    view_b = await MultiPatientService.list_for_chart(
        session, "t1", charts[1].id
    )
    assert view_b["incident"]["id"] == out["new_incident"]["id"]
    view_a = await MultiPatientService.list_for_chart(
        session, "t1", charts[0].id
    )
    assert view_a["incident"]["id"] == parent["id"]
