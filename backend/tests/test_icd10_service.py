"""Service-level tests for the ICD-10 documentation specificity prompt
service.

Exercises the heuristic prompt generation for a chest-pain chart, the
persist + audit pathway, and the acknowledgement (accept + reject)
pathway.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from epcr_app.models import (
    Assessment,
    Base,
    Chart,
    ChartStatus,
    EpcrAuditLog,
    EpcrIcd10DocumentationSuggestion,
)
from epcr_app.services import icd10_service


@pytest_asyncio.fixture
async def chart_with_assessment():
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
        assessment = Assessment(
            id=str(uuid4()),
            chart_id=chart.id,
            tenant_id="t1",
            chief_complaint="chest pain",
            field_diagnosis=None,
            impression_notes=None,
            documented_at=datetime.now(UTC),
        )
        session.add(assessment)
        await session.commit()
        yield session, chart
    await engine.dispose()


async def test_chest_pain_generates_specificity_and_symptom_prompts(
    chart_with_assessment,
):
    session, chart = chart_with_assessment

    prompts = await icd10_service.generate_prompts_for_chart(
        session, "t1", chart.id
    )

    kinds = {p.prompt_kind for p in prompts}
    assert icd10_service.PROMPT_KIND_SPECIFICITY in kinds
    assert icd10_service.PROMPT_KIND_SYMPTOM_VS_DIAGNOSIS in kinds
    # 'chest pain' has no laterality word, so the laterality prompt must
    # also have fired.
    assert icd10_service.PROMPT_KIND_LATERALITY in kinds

    # Every emitted suggestion must have provider_selected_code = None.
    for p in prompts:
        assert p.provider_selected_code is None
        assert p.provider_acknowledged is False
        assert p.provider_selected_at is None

    # The specificity prompt must carry candidate codes including R07.9.
    specificity = next(
        p
        for p in prompts
        if p.prompt_kind == icd10_service.PROMPT_KIND_SPECIFICITY
    )
    candidates = json.loads(specificity.candidate_codes_json)
    codes = {c["code"] for c in candidates}
    assert "R07.9" in codes
    for c in candidates:
        assert set(c.keys()) == {"code", "description"}


async def test_fall_and_mvc_emit_mechanism_prompts(chart_with_assessment):
    session, chart = chart_with_assessment

    # Mutate the assessment to a fall.
    a = (
        await session.execute(
            select(Assessment).where(Assessment.chart_id == chart.id)
        )
    ).scalar_one()
    a.chief_complaint = "fall from 6ft ladder"
    a.field_diagnosis = "Right ankle pain after MVC earlier in day"
    await session.commit()

    prompts = await icd10_service.generate_prompts_for_chart(
        session, "t1", chart.id
    )
    kinds = [p.prompt_kind for p in prompts]
    # fall -> mechanism, mvc -> mechanism + encounter_context
    assert kinds.count(icd10_service.PROMPT_KIND_MECHANISM) >= 2
    assert icd10_service.PROMPT_KIND_ENCOUNTER_CONTEXT in kinds
    # "Right" is present so no laterality prompt for the pain rule.
    assert icd10_service.PROMPT_KIND_LATERALITY not in kinds


async def test_persist_and_acknowledge_flow(chart_with_assessment):
    session, chart = chart_with_assessment

    prompts = await icd10_service.generate_prompts_for_chart(
        session, "t1", chart.id
    )
    persisted = await icd10_service.persist_prompts(
        session, prompts, user_id="user-1"
    )
    assert len(persisted) == len(prompts)

    # One audit entry of action icd10.prompts_generated.
    audits = (
        await session.execute(
            select(EpcrAuditLog).where(
                EpcrAuditLog.action == "icd10.prompts_generated"
            )
        )
    ).scalars().all()
    assert len(audits) == 1
    detail = json.loads(audits[0].detail_json)
    assert detail["count"] == len(persisted)

    # Acknowledge with a selected code.
    target = next(
        p
        for p in persisted
        if p.prompt_kind == icd10_service.PROMPT_KIND_SPECIFICITY
    )
    updated = await icd10_service.acknowledge(
        session,
        tenant_id="t1",
        chart_id=chart.id,
        user_id="user-1",
        suggestion_id=target.id,
        selected_code_or_null="R07.9",
    )
    assert updated.provider_acknowledged is True
    assert updated.provider_selected_code == "R07.9"
    assert updated.provider_selected_at is not None

    # Acknowledge with rejection (None).
    reject_target = next(
        p
        for p in persisted
        if p.prompt_kind == icd10_service.PROMPT_KIND_LATERALITY
    )
    rejected = await icd10_service.acknowledge(
        session,
        tenant_id="t1",
        chart_id=chart.id,
        user_id="user-1",
        suggestion_id=reject_target.id,
        selected_code_or_null=None,
    )
    assert rejected.provider_acknowledged is True
    assert rejected.provider_selected_code is None

    ack_audits = (
        await session.execute(
            select(EpcrAuditLog).where(
                EpcrAuditLog.action == "icd10.acknowledged"
            )
        )
    ).scalars().all()
    assert len(ack_audits) == 2
    selected_codes = {json.loads(a.detail_json)["selected_code"] for a in ack_audits}
    assert selected_codes == {"R07.9", None}


async def test_specificity_score():
    # Empty list -> 0.0
    assert icd10_service.specificity_score([]) == 0.0

    # Build three lightweight rows directly.
    rows = [
        EpcrIcd10DocumentationSuggestion(
            id=str(uuid4()),
            tenant_id="t1",
            chart_id="c1",
            prompt_kind="laterality",
            prompt_text="x",
            provider_acknowledged=ack,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        for ack in (True, False, True)
    ]
    assert abs(icd10_service.specificity_score(rows) - (2 / 3)) < 1e-9


async def test_persist_rejects_preselected_code(chart_with_assessment):
    session, chart = chart_with_assessment
    now = datetime.now(UTC)
    bad = EpcrIcd10DocumentationSuggestion(
        id=str(uuid4()),
        tenant_id="t1",
        chart_id=chart.id,
        prompt_kind="specificity",
        prompt_text="x",
        provider_selected_code="R07.9",  # forbidden at persist time
        created_at=now,
        updated_at=now,
    )
    import pytest

    with pytest.raises(ValueError):
        await icd10_service.persist_prompts(session, [bad], user_id="user-1")
