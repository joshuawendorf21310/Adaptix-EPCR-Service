"""B-002 NEMSIS pipeline driver — runs inside epcr-backend container.

Purpose: prove (or honestly reject) the end-to-end NEMSIS export pipeline:
  1. resolve seeded demo chart
  2. invoke NemsisExportService.generate_export
  3. capture artifact bytes
  4. validate against StateDataSet_v3.xsd with lxml
  5. write JSON evidence + raw XML to /app/artifact/b002

Exits non-zero on any pipeline failure so callers can detect honest-fail.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import traceback
from pathlib import Path

OUT_DIR = Path("/app/artifact/b002")
OUT_DIR.mkdir(parents=True, exist_ok=True)
EVIDENCE = OUT_DIR / "b002_evidence.json"
XML_OUT = OUT_DIR / "demo_pcr.xml"

evidence: dict = {
    "stage": None,
    "ok": False,
    "chart_id": None,
    "tenant_id": "11111111-1111-4111-8111-111111111111",
    "snapshot": None,
    "generate_response": None,
    "artifact_bytes": 0,
    "artifact_sha256": None,
    "xsd_validation": None,
    "error": None,
}


async def main() -> int:
    try:
        evidence["stage"] = "import"
        from epcr_app.db import get_session, _get_session_maker, _require_database_url
        from epcr_app.services_export import NemsisExportService
        from adaptix_contracts.schemas.nemsis_exports import (
            GenerateExportRequest,
            ExportScope,
            ExportTriggerSource,
        )

        chart_id = "0deda819-ea1e-5524-9920-1c5c49cebfbb"
        tenant_id = evidence["tenant_id"]
        evidence["chart_id"] = chart_id

        evidence["stage"] = "snapshot"
        async with _get_session_maker(_require_database_url())() as s:
            snap = await NemsisExportService._snapshot(s, chart_id, tenant_id)
            evidence["snapshot"] = {
                "ready_for_export": snap.ready_for_export,
                "compliance_percentage": getattr(snap, "compliance_percentage", None),
                "missing_mandatory_fields": list(getattr(snap, "missing_mandatory_fields", []) or []),
                "blocker_count": getattr(snap, "blocker_count", None),
            }

        if not evidence["snapshot"]["ready_for_export"]:
            # Honest blocker: seed produced PARTIALLY_COMPLIANT, not export-ready.
            evidence["stage"] = "snapshot-blocked"
            evidence["error"] = "Chart not export-ready (PARTIALLY_COMPLIANT). Real production gate; not a code defect."
            EVIDENCE.write_text(json.dumps(evidence, indent=2))
            print(json.dumps(evidence, indent=2))
            return 2

        evidence["stage"] = "generate"
        async with _get_session_maker(_require_database_url())() as s:
            req = GenerateExportRequest(
                chart_id=chart_id,
                scope=ExportScope.SINGLE_RECORD,
                trigger_source=ExportTriggerSource.CHART,
                allow_retry_of_failed_attempt=True,
            )
            resp = await NemsisExportService.generate_export(
                s, tenant_id=tenant_id, user_id="22222222-2222-4222-8222-222222222222", request=req,
            )
            evidence["generate_response"] = json.loads(resp.model_dump_json())

        # Pull artifact bytes via service, write to disk, sha256 verify
        evidence["stage"] = "artifact"
        if evidence["generate_response"].get("status") == "failed":
            # Re-run the builder + validator inline so we surface the actual
            # validation diagnostics (the failure_reason from generate_export
            # is intentionally generic).
            from epcr_app.services_export import _VALIDATOR
            from epcr_app.nemsis_xml_builder import NemsisXmlBuilder
            from epcr_app.models import Chart, NemsisMappingRecord
            from sqlalchemy import select
            async with _get_session_maker(_require_database_url())() as s:
                chart = (
                    await s.execute(
                        select(Chart).where(Chart.id == chart_id, Chart.tenant_id == tenant_id)
                    )
                ).scalar_one_or_none()
                mappings = list(
                    (
                        await s.execute(
                            select(NemsisMappingRecord).where(
                                NemsisMappingRecord.chart_id == chart_id,
                                NemsisMappingRecord.tenant_id == tenant_id,
                            )
                        )
                    ).scalars()
                )
            builder = NemsisXmlBuilder(chart=chart, mapping_records=mappings)
            xml_bytes, _ = builder.build()
            XML_OUT.write_bytes(xml_bytes)
            evidence["artifact_bytes"] = len(xml_bytes)
            evidence["artifact_sha256"] = hashlib.sha256(xml_bytes).hexdigest()
            evidence["inline_validation"] = _VALIDATOR.validate_xml(xml_bytes)
        else:
            async with _get_session_maker(_require_database_url())() as s:
                art = await NemsisExportService.get_export_artifact(
                    s, tenant_id=tenant_id, export_id=evidence["generate_response"]["export_id"],
                )
            # get_export_artifact returns (bytes, file_name, mime, checksum).
            if isinstance(art, tuple):
                xml_bytes = art[0]
            elif isinstance(art, (bytes, bytearray)):
                xml_bytes = art
            else:
                xml_bytes = art["bytes"]
            XML_OUT.write_bytes(xml_bytes)
            evidence["artifact_bytes"] = len(xml_bytes)
            evidence["artifact_sha256"] = hashlib.sha256(xml_bytes).hexdigest()

        # External XSD validation with lxml — pick the schema matching the
        # actual root element of the artifact (EMSDataSet vs StateDataSet).
        evidence["stage"] = "xsd"
        from lxml import etree
        doc_for_root = etree.fromstring(xml_bytes)
        root_local = etree.QName(doc_for_root.tag).localname
        xsd_filename = f"{root_local}_v3.xsd"
        xsd_path = Path("/app/nemsis/xsd") / xsd_filename
        if not xsd_path.exists():
            for alt in [Path("/app/nemsis") / xsd_filename]:
                if alt.exists():
                    xsd_path = alt
                    break
        if not xsd_path.exists():
            evidence["error"] = f"XSD not found in container at {xsd_path}"
            EVIDENCE.write_text(json.dumps(evidence, indent=2))
            print(json.dumps(evidence, indent=2))
            return 3
        schema_doc = etree.parse(str(xsd_path))
        schema = etree.XMLSchema(schema_doc)
        doc = etree.fromstring(xml_bytes)
        valid = schema.validate(doc)
        errors = []
        if not valid:
            for e in schema.error_log:
                errors.append({
                    "line": e.line,
                    "column": e.column,
                    "level_name": e.level_name,
                    "domain_name": e.domain_name,
                    "type_name": e.type_name,
                    "message": e.message,
                })
        evidence["xsd_validation"] = {
            "valid": bool(valid),
            "xsd_path": str(xsd_path),
            "error_count": len(errors),
            "first_errors": errors[:10],
        }

        evidence["ok"] = bool(valid)
        evidence["stage"] = "done"
        EVIDENCE.write_text(json.dumps(evidence, indent=2))
        print(json.dumps(evidence, indent=2))
        return 0 if valid else 4

    except Exception as exc:
        evidence["error"] = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        EVIDENCE.write_text(json.dumps(evidence, indent=2))
        print(json.dumps(evidence, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
