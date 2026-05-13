"""Service-level tests for :class:`SentenceEvidenceService`.

Constructs a real workspace from real ORM models (no mocks) and verifies:

* :func:`SentenceEvidenceService.map_sentences` proposes the expected
  per-sentence evidence kind / ref id with non-zero confidence for
  clearly-linkable sentences and falls back to ``provider_note`` for
  unrelated sentences.
* :func:`persist` writes both the evidence rows and a single
  ``sentence.evidence_added`` audit event per chart.
* :func:`confirm` flips ``provider_confirmed`` and emits a fresh audit
  event with ``confirmed: true`` in its payload.
* :func:`unlink` downgrades the row to ``provider_note`` and emits a
  ``sentence.evidence_unlinked`` audit event.
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
    EpcrAiAuditEvent,
    EpcrAnatomicalFinding,
    EpcrSentenceEvidence,
    MedicationAdministration,
    Vitals,
)
from epcr_app.services.sentence_evidence_service import (
    SentenceEvidenceService,
    SentenceEvidenceServiceError,
)


# Resolve the medication model lazily — the codebase exposes it as
# ``MedicationAdministration``.
try:  # pragma: no cover - import-time wiring
    _MED_MODEL = MedicationAdministration
except NameError:  # pragma: no cover
    _MED_MODEL = None


@pytest_asyncio.fixture
async def workspace_fixture():
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

        vital = Vitals(
            id=str(uuid4()),
            chart_id=chart.id,
            tenant_id="t1",
            bp_sys=140,
            bp_dia=90,
            hr=110,
            rr=22,
            temp_f=98.6,
            spo2=94,
            glucose=120,
            recorded_at=datetime.now(UTC),
        )
        med = _MED_MODEL(
            id=str(uuid4()),
            chart_id=chart.id,
            tenant_id="t1",
            medication_name="Nitroglycerin",
            dose_value="0.4",
            dose_unit="mg",
            route="SL",
            indication="chest pain relief",
            administered_at=datetime.now(UTC),
            administered_by_user_id="user-1",
        )
        anat = EpcrAnatomicalFinding(
            id=str(uuid4()),
            chart_id=chart.id,
            tenant_id="t1",
            region_id="region_chest",
            region_label="Chest",
            body_view="front",
            finding_type="tenderness",
            severity="moderate",
            laterality="midline",
            pertinent_negative=False,
            assessed_at=datetime.now(UTC),
            assessed_by="user-1",
        )
        session.add_all([vital, med, anat])
        await session.commit()

        workspace = {
            "vitals": [vital],
            "medications": [med],
            "anatomical_findings": [anat],
            "fields": {
                "chief_complaint": "chest pain",
                "primary_impression": "ACS suspected",
            },
        }
        yield session, chart, workspace, {"vital": vital, "med": med, "anat": anat}

    await engine.dispose()


async def test_map_sentences_links_medication_and_vital(workspace_fixture) -> None:
    session, chart, workspace, refs = workspace_fixture

    narrative = (
        "Patient presented with chest pain. "
        "Blood pressure 140/90 with heart rate of 110. "
        "Administered nitroglycerin 0.4 mg SL for chest pain relief. "
        "Pilot reports favorable weather conditions for the helicopter."
    )

    rows = SentenceEvidenceService.map_sentences(
        session,
        tenant_id="t1",
        chart_id=chart.id,
        narrative_id="narr-1",
        narrative_text=narrative,
        workspace=workspace,
    )

    assert len(rows) == 4
    # Sentence 0: chest pain -> field (chief_complaint) or anatomical_finding
    assert rows[0].evidence_kind in {"field", "anatomical_finding"}
    # Sentence 1: BP / HR -> vital
    assert rows[1].evidence_kind == "vital"
    assert rows[1].evidence_ref_id == refs["vital"].id
    # Sentence 2: nitroglycerin -> medication
    assert rows[2].evidence_kind == "medication"
    assert rows[2].evidence_ref_id == refs["med"].id
    assert rows[2].confidence > Decimal("0.10")
    # Sentence 3: unrelated chatter -> provider_note fallback
    assert rows[3].evidence_kind == "provider_note"
    assert rows[3].evidence_ref_id is None
    assert rows[3].confidence == Decimal("0.00")

    # Nothing should have been persisted yet.
    persisted = (
        await session.execute(select(EpcrSentenceEvidence))
    ).scalars().all()
    assert persisted == []


async def test_persist_writes_rows_and_single_audit_event(
    workspace_fixture,
) -> None:
    session, chart, workspace, _ = workspace_fixture

    narrative = (
        "Administered nitroglycerin 0.4 mg SL. "
        "Heart rate 110 documented."
    )
    proposed = SentenceEvidenceService.map_sentences(
        session,
        tenant_id="t1",
        chart_id=chart.id,
        narrative_id="narr-1",
        narrative_text=narrative,
        workspace=workspace,
    )
    SentenceEvidenceService.persist(session, proposed, user_id="user-1")
    await session.commit()

    persisted = (
        await session.execute(
            select(EpcrSentenceEvidence).order_by(
                EpcrSentenceEvidence.sentence_index.asc()
            )
        )
    ).scalars().all()
    assert len(persisted) == 2

    audits = (
        await session.execute(
            select(EpcrAiAuditEvent).where(
                EpcrAiAuditEvent.event_kind == "sentence.evidence_added"
            )
        )
    ).scalars().all()
    assert len(audits) == 1
    payload = json.loads(audits[0].payload_json)
    assert payload["count"] == 2
    assert payload["narrative_id"] == "narr-1"
    assert set(payload["evidence_ids"]) == {r.id for r in persisted}


async def test_persist_rejects_unknown_evidence_kind(workspace_fixture) -> None:
    session, chart, _, _ = workspace_fixture
    bad = EpcrSentenceEvidence(
        id=str(uuid4()),
        tenant_id="t1",
        chart_id=chart.id,
        narrative_id=None,
        sentence_index=0,
        sentence_text="bogus",
        evidence_kind="not_a_real_kind",
        evidence_ref_id=None,
        confidence=Decimal("0.50"),
    )
    with pytest.raises(SentenceEvidenceServiceError):
        SentenceEvidenceService.persist(session, [bad])


async def test_confirm_flips_flag_and_audits(workspace_fixture) -> None:
    session, chart, workspace, _ = workspace_fixture
    proposed = SentenceEvidenceService.map_sentences(
        session,
        tenant_id="t1",
        chart_id=chart.id,
        narrative_id="narr-1",
        narrative_text="Administered nitroglycerin 0.4 mg SL.",
        workspace=workspace,
    )
    SentenceEvidenceService.persist(session, proposed, user_id="user-1")
    await session.commit()
    target = proposed[0]

    updated = await SentenceEvidenceService.confirm(
        session,
        tenant_id="t1",
        chart_id=chart.id,
        user_id="user-2",
        evidence_id=target.id,
    )
    await session.commit()

    assert updated.provider_confirmed is True

    audits = (
        await session.execute(
            select(EpcrAiAuditEvent).where(
                EpcrAiAuditEvent.event_kind == "sentence.evidence_added"
            )
        )
    ).scalars().all()
    confirm_payloads = [
        json.loads(a.payload_json)
        for a in audits
        if a.payload_json and json.loads(a.payload_json).get("confirmed") is True
    ]
    assert len(confirm_payloads) == 1
    assert confirm_payloads[0]["evidence_id"] == target.id


async def test_unlink_downgrades_and_audits(workspace_fixture) -> None:
    session, chart, workspace, _ = workspace_fixture
    proposed = SentenceEvidenceService.map_sentences(
        session,
        tenant_id="t1",
        chart_id=chart.id,
        narrative_id="narr-1",
        narrative_text="Administered nitroglycerin 0.4 mg SL.",
        workspace=workspace,
    )
    SentenceEvidenceService.persist(session, proposed, user_id="user-1")
    await session.commit()
    target = proposed[0]
    assert target.evidence_kind == "medication"

    updated = await SentenceEvidenceService.unlink(
        session,
        tenant_id="t1",
        chart_id=chart.id,
        user_id="user-2",
        evidence_id=target.id,
    )
    await session.commit()

    assert updated.evidence_kind == "provider_note"
    assert updated.evidence_ref_id is None
    assert updated.provider_confirmed is False
    assert Decimal(str(updated.confidence)) == Decimal("0.00")

    audits = (
        await session.execute(
            select(EpcrAiAuditEvent).where(
                EpcrAiAuditEvent.event_kind == "sentence.evidence_unlinked"
            )
        )
    ).scalars().all()
    assert len(audits) == 1
    payload = json.loads(audits[0].payload_json)
    assert payload["evidence_id"] == target.id
    assert payload["prior_kind"] == "medication"


async def test_list_for_chart_filters_by_narrative(workspace_fixture) -> None:
    session, chart, workspace, _ = workspace_fixture
    proposed_a = SentenceEvidenceService.map_sentences(
        session,
        tenant_id="t1",
        chart_id=chart.id,
        narrative_id="narr-A",
        narrative_text="Heart rate 110 documented.",
        workspace=workspace,
    )
    proposed_b = SentenceEvidenceService.map_sentences(
        session,
        tenant_id="t1",
        chart_id=chart.id,
        narrative_id="narr-B",
        narrative_text="Administered nitroglycerin 0.4 mg SL.",
        workspace=workspace,
    )
    SentenceEvidenceService.persist(session, proposed_a + proposed_b)
    await session.commit()

    only_a = await SentenceEvidenceService.list_for_chart(
        session, tenant_id="t1", chart_id=chart.id, narrative_id="narr-A"
    )
    only_b = await SentenceEvidenceService.list_for_chart(
        session, tenant_id="t1", chart_id=chart.id, narrative_id="narr-B"
    )
    everything = await SentenceEvidenceService.list_for_chart(
        session, tenant_id="t1", chart_id=chart.id
    )
    assert {r.narrative_id for r in only_a} == {"narr-A"}
    assert {r.narrative_id for r in only_b} == {"narr-B"}
    assert len(everything) == len(only_a) + len(only_b)


async def test_confirm_unknown_evidence_id_raises(workspace_fixture) -> None:
    session, chart, _, _ = workspace_fixture
    with pytest.raises(SentenceEvidenceServiceError):
        await SentenceEvidenceService.confirm(
            session,
            tenant_id="t1",
            chart_id=chart.id,
            user_id="user-1",
            evidence_id="does-not-exist",
        )
