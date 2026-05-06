"""Tests for the CTA demo seeder.

These tests use an in-memory SQLite database and the existing model
metadata, so no production credentials are required and no production
data is touched. The seeder must:

* discover all expected CTA template files,
* create one chart per required case under the supplied tenant,
* persist every NEMSIS leaf element from the source XML,
* be idempotent on re-run (no duplicate charts, no exceptions),
* keep all rows scoped to the supplied tenant,
* never fabricate submission success,
* preserve the template filename + md5 in the audit log.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure the backend root is importable when pytest is run from anywhere.
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import select

from epcr_app.models import (  # noqa: E402  (import after sys.path edit)
    Base,
    Chart,
    EpcrAuditLog,
    NemsisMappingRecord,
)

from scripts.seed_cta_demo import (  # noqa: E402
    DEMO_TENANT_ID,
    REQUIRED_CASES,
    TEMPLATE_DIR,
    deterministic_chart_id,
    deterministic_call_number,
    discover_cta_files,
    extract_nemsis_fields,
    seed_demo_tenant,
)


REQUIRED_CASE_IDS = {c.case_id for c in REQUIRED_CASES}


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield factory
    await engine.dispose()


def test_template_files_discoverable() -> None:
    files = discover_cta_files()
    names = {p.name for p in files}
    expected = {c.template_filename for c in REQUIRED_CASES}
    missing = expected - names
    assert not missing, f"CTA template files missing on disk: {missing}"


def test_extract_nemsis_fields_reads_dotted_leaves() -> None:
    sample = TEMPLATE_DIR / "2025-EMS-1-Allergy_v351.xml"
    fields = extract_nemsis_fields(sample)
    field_ids = {f for f, _ in fields}
    # eRecord.01 / eResponse.03 / eResponse.05 are present in the template.
    assert "eRecord.01" in field_ids
    assert "eResponse.03" in field_ids
    assert "eResponse.05" in field_ids
    # Group containers must NOT appear as leaves.
    assert not any(f.endswith("Group") for f in field_ids)
    # Every value must be non-empty.
    assert all(v.strip() for _, v in fields)


def test_deterministic_ids_are_stable() -> None:
    a = deterministic_chart_id(DEMO_TENANT_ID, "EMS-CTA-ACTIVE-001")
    b = deterministic_chart_id(DEMO_TENANT_ID, "EMS-CTA-ACTIVE-001")
    assert a == b
    # Different cases produce different ids.
    c = deterministic_chart_id(DEMO_TENANT_ID, "EMS-CTA-ACTIVE-002")
    assert a != c
    # Different tenants produce different ids.
    d = deterministic_chart_id("other-tenant", "EMS-CTA-ACTIVE-001")
    assert a != d


def test_call_number_includes_case_id() -> None:
    assert deterministic_call_number("EMS-CTA-ACTIVE-001") == "CTA-EMS-CTA-ACTIVE-001"


@pytest.mark.asyncio
async def test_seeder_creates_all_required_records(session_factory):
    results = await seed_demo_tenant(session_factory, tenant_id=DEMO_TENANT_ID)
    seeded_case_ids = {r.case_id for r in results}
    assert seeded_case_ids == REQUIRED_CASE_IDS, "Every required CTA case must be seeded"
    assert all(r.created for r in results), "First run should create every chart"
    assert all(r.nemsis_field_count > 0 for r in results), "Must persist NEMSIS fields"

    async with session_factory() as session:
        chart_rows = (await session.execute(select(Chart))).scalars().all()
        assert len(chart_rows) == len(REQUIRED_CASES)
        assert all(c.tenant_id == DEMO_TENANT_ID for c in chart_rows)


@pytest.mark.asyncio
async def test_seeder_is_idempotent(session_factory):
    first = await seed_demo_tenant(session_factory, tenant_id=DEMO_TENANT_ID)
    second = await seed_demo_tenant(session_factory, tenant_id=DEMO_TENANT_ID)

    # Same number of results, same chart ids, no new creations on the
    # second pass.
    assert len(first) == len(second)
    first_ids = {r.chart_id for r in first}
    second_ids = {r.chart_id for r in second}
    assert first_ids == second_ids
    assert all(not r.created for r in second), "Second run must not re-create charts"

    async with session_factory() as session:
        # Still exactly one chart per case.
        chart_rows = (await session.execute(select(Chart))).scalars().all()
        assert len(chart_rows) == len(REQUIRED_CASES)


@pytest.mark.asyncio
async def test_seeded_records_are_tenant_scoped(session_factory):
    other_tenant = "other-tenant-aaaa-bbbb-cccc-dddd"
    await seed_demo_tenant(session_factory, tenant_id=DEMO_TENANT_ID)
    await seed_demo_tenant(session_factory, tenant_id=other_tenant)

    async with session_factory() as session:
        demo_charts = (await session.execute(
            select(Chart).where(Chart.tenant_id == DEMO_TENANT_ID)
        )).scalars().all()
        other_charts = (await session.execute(
            select(Chart).where(Chart.tenant_id == other_tenant)
        )).scalars().all()
        assert {c.id for c in demo_charts}.isdisjoint({c.id for c in other_charts})

        # NEMSIS mappings inherit tenant scope.
        mappings = (await session.execute(select(NemsisMappingRecord))).scalars().all()
        assert all(m.tenant_id in {DEMO_TENANT_ID, other_tenant} for m in mappings)
        assert any(m.tenant_id == DEMO_TENANT_ID for m in mappings)
        assert any(m.tenant_id == other_tenant for m in mappings)


@pytest.mark.asyncio
async def test_seeder_does_not_fabricate_submission(session_factory):
    """The seeder must NEVER write a row that claims TAC submission success."""
    await seed_demo_tenant(session_factory, tenant_id=DEMO_TENANT_ID)
    async with session_factory() as session:
        audits = (await session.execute(select(EpcrAuditLog))).scalars().all()
        for a in audits:
            action = (a.action or "").lower()
            assert "submission_succeeded" not in action
            assert "tac_submitted" not in action
            assert "certification_passed" not in action


@pytest.mark.asyncio
async def test_seeder_records_template_provenance(session_factory):
    await seed_demo_tenant(session_factory, tenant_id=DEMO_TENANT_ID)
    async with session_factory() as session:
        seed_audits = (await session.execute(
            select(EpcrAuditLog).where(EpcrAuditLog.action == "cta_template_seeded")
        )).scalars().all()
        assert len(seed_audits) == len(REQUIRED_CASES)
        for a in seed_audits:
            detail = a.detail_json or ""
            assert "template_filename" in detail
            assert "template_md5" in detail
            assert "_v351.xml" in detail
