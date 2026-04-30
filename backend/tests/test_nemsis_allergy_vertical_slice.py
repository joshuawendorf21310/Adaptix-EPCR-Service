from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from epcr_app.api_nemsis import router as nemsis_router
from epcr_app.nemsis.compare_official import compare_official
from epcr_app.nemsis.cta_client import CtaSubmissionClient
from epcr_app.nemsis.service import AllergyVerticalSliceService
from epcr_app.nemsis.template_loader import LOCKED_TACTICAL_TEST_KEY, OfficialTemplateLoader

NEMSIS_NS = {"nem": "http://www.nemsis.org"}

_WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
_CTA_XML_DIR = (
    _WORKSPACE_ROOT
    / "Adaptix-EPCR-Service"
    / "nemsis_test"
    / "assets"
    / "cta"
    / "cta_uploaded_package"
    / "v3.5.1 C&S for vendors"
)
_CORE_CTA_UPLOAD_DIR = _WORKSPACE_ROOT / "Adaptix-Core-Service" / "cta_upload"
_cta_available = (
    _CTA_XML_DIR.exists()
    and _CORE_CTA_UPLOAD_DIR.exists()
    and any(_CTA_XML_DIR.glob("2025-EMS-*.xml"))
    and (_CORE_CTA_UPLOAD_DIR / "2025-EMS-1-Allergy_v351.xml").exists()
    and (_CORE_CTA_UPLOAD_DIR / "2025-DEM-1_v351.xml").exists()
)
_skip_no_cta = pytest.mark.skipif(
    not _cta_available,
    reason="NEMSIS CTA vendor/core upload XML templates not present on disk",
)


@_skip_no_cta
@pytest.mark.asyncio
async def test_allergy_vertical_slice_builds_and_validates_official_artifact() -> None:
    """Build the official Allergy slice and prove the locked validation path is real.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If the official Allergy artifact drifts from the required pass path.
    """

    service = AllergyVerticalSliceService()
    result = await service.run(integration_enabled=False)

    assert result.case_id == "2025-EMS-1-Allergy_v351"
    assert result.tactical_test_key == LOCKED_TACTICAL_TEST_KEY
    assert result.demographic_values["agency_id"] == "120495"
    assert result.demographic_values["agency_number"] == "351-T0495"
    assert result.demographic_values["agency_state_code"] == "12"
    assert result.demographic_values["agency_state_name"] == "Florida"
    assert result.unresolved_placeholders == []
    assert result.repeated_group_counts_before == result.repeated_group_counts_after
    assert result.xsd_validation["is_valid"] is True
    assert result.schematron_validation["is_valid"] is True
    assert result.cta_submission["response_status"] == "skipped"

    artifact_path = Path(result.artifact_path)
    xsd_result_path = Path(result.xsd_result_path)
    schematron_result_path = Path(result.schematron_result_path)
    fidelity_result_path = Path(result.fidelity_result_path)
    assert artifact_path.exists()
    assert xsd_result_path.exists()
    assert schematron_result_path.exists()
    assert fidelity_result_path.exists()

    root = ET.parse(artifact_path).getroot()
    official_root = OfficialTemplateLoader().load().ems_root
    assert root.tag.endswith("EMSDataSet")
    assert root.find(".//nem:dAgency.01", NEMSIS_NS).text == "120495"
    assert root.find(".//nem:dAgency.02", NEMSIS_NS).text == "351-T0495"
    assert root.find(".//nem:dAgency.04", NEMSIS_NS).text == "12"
    assert root.find(".//nem:eResponse.01", NEMSIS_NS).text == "351-T0495"
    assert root.find(".//nem:eResponse.02", NEMSIS_NS).text == "Okaloosa County Emergency Medical Services"
    assert root.find(".//nem:eResponse.04", NEMSIS_NS).text == LOCKED_TACTICAL_TEST_KEY
    assert root.find(".//nem:eRecord.01", NEMSIS_NS).text == official_root.find(".//nem:eRecord.01", NEMSIS_NS).text
    assert root.find(".//nem:eRecord.02", NEMSIS_NS).text == official_root.find(".//nem:eRecord.02", NEMSIS_NS).text
    assert root.find(".//nem:eRecord.03", NEMSIS_NS).text == official_root.find(".//nem:eRecord.03", NEMSIS_NS).text
    assert root.find(".//nem:eRecord.04", NEMSIS_NS).text == official_root.find(".//nem:eRecord.04", NEMSIS_NS).text
    assert root.find(".//nem:PatientCareReport", NEMSIS_NS).attrib["UUID"] == official_root.find(".//nem:PatientCareReport", NEMSIS_NS).attrib["UUID"]
    assert not any("[" in (element.text or "") for element in root.iter())

    official_path = OfficialTemplateLoader().load().paths.ems_xml_path
    fidelity = compare_official(official_path, artifact_path)
    assert fidelity["is_match"] is True

    original_root = official_root
    original_pn_nv_count = sum(
        1
        for element in original_root.iter()
        if "PN" in element.attrib or "NV" in element.attrib
    )
    built_pn_nv_count = sum(
        1
        for element in root.iter()
        if "PN" in element.attrib or "NV" in element.attrib
    )
    assert original_pn_nv_count > 0
    assert built_pn_nv_count == original_pn_nv_count


@pytest.mark.asyncio
async def test_cta_client_can_submit_when_integration_enabled_with_mocked_network() -> None:
    """Exercise the CTA submission parser behind the explicit integration gate.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If the CTA client fails to parse a successful response.
    """

    class FakeResponse:
        status_code = 200
        text = """<SubmitDataResponse><status>accepted</status><statusCode>1</statusCode><requestHandle>REQ-123</requestHandle></SubmitDataResponse>"""

        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def post(self, *args, **kwargs) -> FakeResponse:
            return FakeResponse()

    client = CtaSubmissionClient(
        endpoint="https://example.test/cta",
        username="demo-user",
        password="demo-pass",
        organization="Adaptix Demo Organization",
        client_factory=FakeAsyncClient,
    )
    result = await client.submit(
        b"<EMSDataSet xmlns=\"http://www.nemsis.org\" />",
        integration_enabled=True,
    )

    assert result.integration_enabled is True
    assert result.submitted is True
    assert result.http_status == 200
    assert result.status_code == "1"
    assert result.request_handle == "REQ-123"
    assert result.response_status == "accepted"


@_skip_no_cta
def test_allergy_vertical_slice_api_endpoint_returns_evidence_payload() -> None:
    """Verify the public API route exposes the locked Allergy vertical slice response.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If the API route contract drifts.
    """

    app = FastAPI()
    app.include_router(nemsis_router)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/epcr/nemsis/vertical-slice/allergy",
            headers={"X-Tenant-ID": "tenant-test"},
            json={"integration_enabled": False},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["case_id"] == "2025-EMS-1-Allergy_v351"
    assert payload["tactical_test_key"] == LOCKED_TACTICAL_TEST_KEY
    assert payload["xsd_validation"]["is_valid"] is True
    assert payload["schematron_validation"]["is_valid"] is True
    assert payload["cta_submission"]["response_status"] == "skipped"
