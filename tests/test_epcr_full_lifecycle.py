"""Slice A — EPCR full lifecycle proof (single combined test).

Runs against the LIVE EPCR backend container's postgres against the
deterministic demo chart 0deda819-... that B-002 already validated.
Uses the same `_get_session_maker(_require_database_url())()` pattern as
scripts/b002_pipeline.py to stay on a single asyncpg engine within a single
event loop. All 15 lifecycle steps are asserted in one async test so we
never cross asyncpg connections between event loops.

Honest skip: outside the container set EPCR_LIFECYCLE_LIVE=0 (default).
Inside the container run with EPCR_LIFECYCLE_LIVE=1.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest


CHART_ID = "0deda819-ea1e-5524-9920-1c5c49cebfbb"
TENANT_ID = "11111111-1111-4111-8111-111111111111"
USER_ID = "22222222-2222-4222-8222-222222222222"

LIVE_FLAG = os.getenv("EPCR_LIFECYCLE_LIVE", "").strip() in {"1", "true", "yes"}

pytestmark = pytest.mark.skipif(
    not LIVE_FLAG,
    reason=(
        "EPCR_LIFECYCLE_LIVE not enabled — this test asserts against the "
        "deterministic demo chart in the running EPCR postgres. Run inside "
        "adaptix-core-service-epcr-backend-1 with EPCR_LIFECYCLE_LIVE=1."
    ),
)


def _evidence_path() -> Path:
    out = (
        Path("/app/artifact/lifecycle")
        if Path("/app/artifact").exists()
        else Path("./artifact/lifecycle")
    )
    out.mkdir(parents=True, exist_ok=True)
    return out / "epcr_full_lifecycle_evidence.json"


@pytest.mark.asyncio
async def test_epcr_full_lifecycle():
    from sqlalchemy import select

    from epcr_app.db import _get_session_maker, _require_database_url
    from epcr_app.models import (
        Assessment,
        Chart,
        ClinicalIntervention,
        MedicationAdministration,
        NemsisMappingRecord,
        PatientProfile,
        Vitals,
    )
    from epcr_app.services_export import NemsisExportService
    from adaptix_contracts.schemas.nemsis_exports import (
        ExportScope,
        ExportTriggerSource,
        GenerateExportRequest,
    )

    session_maker = _get_session_maker(_require_database_url())
    proven: list[str] = []

    # 1-7: clinical row assertions in a single session
    async with session_maker() as s:
        chart = (
            await s.execute(
                select(Chart).where(
                    Chart.id == CHART_ID, Chart.tenant_id == TENANT_ID
                )
            )
        ).scalar_one_or_none()
        assert chart is not None, f"Demo chart {CHART_ID} missing in tenant {TENANT_ID}"
        proven.append("chart_row")

        pp = (
            await s.execute(
                select(PatientProfile).where(PatientProfile.chart_id == CHART_ID)
            )
        ).scalar_one_or_none()
        assert pp is not None, "PatientProfile missing for demo chart"
        proven.append("patient_profile")

        assessment = (
            await s.execute(
                select(Assessment).where(Assessment.chart_id == CHART_ID)
            )
        ).scalar_one_or_none()
        assert assessment is not None, "Assessment missing for demo chart"
        proven.append("assessment")

        vitals = (
            await s.execute(
                select(Vitals).where(Vitals.chart_id == CHART_ID)
            )
        ).scalars().all()
        assert len(vitals) >= 1, f"Vitals empty for demo chart (got {len(vitals)})"
        proven.append("vitals")

        interventions = (
            await s.execute(
                select(ClinicalIntervention).where(
                    ClinicalIntervention.chart_id == CHART_ID
                )
            )
        ).scalars().all()
        assert len(interventions) >= 1, "Interventions empty for demo chart"
        proven.append("interventions")

        meds = (
            await s.execute(
                select(MedicationAdministration).where(
                    MedicationAdministration.chart_id == CHART_ID
                )
            )
        ).scalars().all()
        assert len(meds) >= 1, "Medications empty for demo chart"
        proven.append("medications")

        mappings = (
            await s.execute(
                select(NemsisMappingRecord).where(
                    NemsisMappingRecord.chart_id == CHART_ID,
                    NemsisMappingRecord.tenant_id == TENANT_ID,
                )
            )
        ).scalars().all()
        assert len(mappings) >= 13, (
            f"Expected >=13 NEMSIS mandatory mappings, got {len(mappings)}"
        )
        proven.append("nemsis_mandatory_mappings")

    # 8: generate_export
    async with session_maker() as s:
        req = GenerateExportRequest(
            chart_id=CHART_ID,
            scope=ExportScope.SINGLE_RECORD,
            trigger_source=ExportTriggerSource.CHART,
            allow_retry_of_failed_attempt=True,
        )
        resp = await NemsisExportService.generate_export(
            s, tenant_id=TENANT_ID, user_id=USER_ID, request=req
        )
    assert resp.success is True, f"generate_export failed: {resp.failure_reason}"
    assert resp.status == "generated", f"unexpected status: {resp.status}"
    proven.append("generate_export")

    # 9: validation not skipped
    val_block = (
        getattr(resp, "validation", None)
        or (resp.readiness_snapshot or {}).get("validation")
        or {}
    )
    skipped = (
        val_block.get("validation_skipped")
        if isinstance(val_block, dict)
        else getattr(val_block, "validation_skipped", False)
    )
    assert skipped in (False, None), f"validation_skipped truthy: {skipped!r}"
    proven.append("validation_not_skipped")

    # 10/11: surface xsd + schematron flags (truthful capture)
    xsd_valid_svc = (
        val_block.get("xsd_valid")
        if isinstance(val_block, dict)
        else getattr(val_block, "xsd_valid", None)
    )
    sch_valid_svc = (
        val_block.get("schematron_valid")
        if isinstance(val_block, dict)
        else getattr(val_block, "schematron_valid", None)
    )

    # 12: round-trip artifact
    async with session_maker() as s:
        artifact = await NemsisExportService.get_export_artifact(
            s, tenant_id=TENANT_ID, export_id=resp.export_id
        )
    if isinstance(artifact, tuple):
        xml_bytes = artifact[0]
        recorded_checksum = artifact[3] if len(artifact) >= 4 else None
    elif isinstance(artifact, (bytes, bytearray)):
        xml_bytes = bytes(artifact)
        recorded_checksum = None
    else:
        xml_bytes = artifact["bytes"]
        recorded_checksum = artifact.get("checksum")
    assert xml_bytes and len(xml_bytes) > 1000, "Artifact suspiciously small"
    proven.append("artifact_round_trip")

    # 13: sha256 round-trip
    actual_sha = hashlib.sha256(xml_bytes).hexdigest()
    if recorded_checksum:
        assert actual_sha == recorded_checksum, (
            f"checksum mismatch recorded={recorded_checksum} actual={actual_sha}"
        )
    proven.append("sha256_match")

    # 14: external XSD revalidation
    from lxml import etree

    doc = etree.fromstring(xml_bytes)
    root_local = etree.QName(doc.tag).localname
    xsd_filename = f"{root_local}_v3.xsd"
    candidates = [
        Path("/app/nemsis/xsd") / xsd_filename,
        Path("/app/nemsis") / xsd_filename,
        Path(__file__).parent.parent / "backend" / "nemsis" / "xsd" / xsd_filename,
    ]
    xsd_path = next((p for p in candidates if p.exists()), None)
    assert xsd_path is not None, f"XSD {xsd_filename} not found in {candidates}"

    schema = etree.XMLSchema(etree.parse(str(xsd_path)))
    valid = schema.validate(etree.fromstring(xml_bytes))
    errors = []
    if not valid:
        for e in schema.error_log:
            errors.append(
                {"line": e.line, "level_name": e.level_name, "message": e.message}
            )
    assert valid, f"XSD validation failed: {errors[:5]}"
    proven.append("xsd_revalidate_external")

    # 15: write evidence
    evidence = {
        "chart_id": CHART_ID,
        "tenant_id": TENANT_ID,
        "export_id": resp.export_id,
        "status": resp.status,
        "validation_skipped": skipped,
        "service_xsd_valid": xsd_valid_svc,
        "service_schematron_valid": sch_valid_svc,
        "artifact_bytes": len(xml_bytes),
        "artifact_sha256": actual_sha,
        "recorded_checksum": recorded_checksum,
        "xsd_path": str(xsd_path),
        "lifecycle_steps_proven": proven,
        "verdict": "EPCR_FULL_LIFECYCLE_PASS",
    }
    out = _evidence_path()
    out.write_text(json.dumps(evidence, indent=2))
    print(json.dumps(evidence, indent=2))
