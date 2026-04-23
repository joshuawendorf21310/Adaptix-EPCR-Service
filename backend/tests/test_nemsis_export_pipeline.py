"""Regression coverage for the shared NEMSIS export pipeline."""

from __future__ import annotations

import zipfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from epcr_app.api_export import router as export_router
from epcr_app.db import get_session
from epcr_app.nemsis_xml_builder import NemsisXmlBuilder
from epcr_app.nemsis_xsd_validator import NemsisXSDValidator


def test_state_dataset_builder_emits_state_dataset_and_mapped_elements(
    monkeypatch,
) -> None:
    """Builder should emit a StateDataSet artifact with required top-level sections."""
    monkeypatch.setenv("NEMSIS_VALIDATOR_ASSET_VERSION", "3.5.1.250403CP1")
    monkeypatch.setenv("NEMSIS_STATE_CODE", "12")
    monkeypatch.setenv("NEMSIS_SOFTWARE_CREATOR", "Adaptix")
    monkeypatch.setenv("NEMSIS_SOFTWARE_NAME", "Adaptix Platform")
    monkeypatch.setenv("NEMSIS_SOFTWARE_VERSION", "2026.04.21")

    chart = SimpleNamespace(
        id="chart-1",
        call_number="CALL-100",
        created_at=datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc),
    )
    mappings = [
        SimpleNamespace(nemsis_field="eRecord.01", nemsis_value="PCR-1"),
        SimpleNamespace(nemsis_field="eDisposition.27", nemsis_value="4227001"),
    ]

    xml_bytes, warnings = NemsisXmlBuilder(
        chart=chart,
        mapping_records=mappings,
    ).build()
    xml_text = xml_bytes.decode("utf-8")

    assert "<StateDataSet" in xml_text
    assert "StateDataSet_v3.xsd" in xml_text
    assert "<sState.01>12</sState.01>" in xml_text
    assert "<sSoftware.01>Adaptix</sSoftware.01>" in xml_text
    assert "<sElement.01>eDisposition.27</sElement.01>" in xml_text
    assert "<sElement.01>eRecord.01</sElement.01>" in xml_text
    assert warnings == []


def test_validator_reports_missing_assets_as_deterministic_failure(
    monkeypatch,
) -> None:
    """Validator should fail explicitly when official assets are unavailable."""
    monkeypatch.delenv("NEMSIS_XSD_PATH", raising=False)
    monkeypatch.delenv("NEMSIS_SCHEMATRON_PATH", raising=False)

    validator = NemsisXSDValidator()
    result = validator.validate_xml(
        b"<?xml version='1.0' encoding='UTF-8'?><StateDataSet xmlns='http://www.nemsis.org'/>"
    )

    assert result["valid"] is False
    assert result["validation_skipped"] is False
    assert result["xsd_valid"] is False
    assert result["schematron_valid"] is False
    assert result["checksum_sha256"]
    assert result["errors"]


def test_validator_resolves_state_dataset_xsd_from_official_zip(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Validator should accept the official NEMSIS ZIP bundle as the XSD source."""
    bundle_path = tmp_path / "NEMSIS_XSDs.zip"

    with zipfile.ZipFile(bundle_path, "w") as archive:
        archive.writestr(
            "NEMSIS_XSDs/StateDataSet_v3.xsd",
            """<?xml version='1.0' encoding='UTF-8'?>
<xs:schema xmlns:xs='http://www.w3.org/2001/XMLSchema'
           targetNamespace='http://www.nemsis.org'
           xmlns='http://www.nemsis.org'
           elementFormDefault='qualified'>
  <xs:element name='StateDataSet' type='xs:anyType'/>
</xs:schema>
""",
        )

    monkeypatch.setenv("NEMSIS_XSD_PATH", str(bundle_path))

    validator = NemsisXSDValidator()
    resolved = validator.get_xsd_asset_path("StateDataSet")

    assert resolved is not None
    assert resolved.endswith("StateDataSet_v3.xsd")

    validation = validator.validate_xml(
        b"<?xml version='1.0' encoding='UTF-8'?><StateDataSet xmlns='http://www.nemsis.org'/>"
    )
    assert validation["checksum_sha256"]


def test_export_artifact_endpoint_returns_raw_xml_and_checksum() -> None:
    """Artifact retrieval endpoint should stream raw XML bytes with checksum metadata."""
    app = FastAPI()

    async def override_session():
        yield object()

    app.dependency_overrides[get_session] = override_session
    app.include_router(export_router)

    with patch(
        "epcr_app.api_export.NemsisExportService.get_export_artifact",
        new=AsyncMock(
            return_value=(
                b"<?xml version='1.0'?><StateDataSet/>",
                "state-export.xml",
                "application/xml",
                "abc123",
            )
        ),
    ):
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/epcr/nemsis/export/77/artifact",
                headers={"X-Tenant-ID": "tenant-1"},
            )

    assert response.status_code == 200
    assert response.content == b"<?xml version='1.0'?><StateDataSet/>"
    assert response.headers["x-checksum-sha256"] == "abc123"
    assert "state-export.xml" in response.headers["content-disposition"]