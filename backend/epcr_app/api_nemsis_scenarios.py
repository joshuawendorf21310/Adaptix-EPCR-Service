"""NEMSIS compliance studio scenario management and execution API routes.

Supports both the authoritative 2025 CTA EMS package and the existing 2026
pre-testing scenarios. The 2025 CTA scenarios are built exclusively through the
template resolver so the official XML structure, repeated groups, NV/PN fields,
and custom/state elements remain intact.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import tempfile
import uuid
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.models_nemsis_core import (
    NemsisScenario,
    NemsisSubmissionResult,
    NemsisSubmissionStatusHistory,
)
from epcr_app.nemsis_template_resolver import (
    build_nemsis_xml_from_template,
    resolve_cta_template_path,
)
from epcr_app.nemsis_xsd_validator import NemsisXSDValidator

logger = logging.getLogger(__name__)

TAC_ENDPOINT_URL = os.environ.get(
    "NEMSIS_CTA_ENDPOINT",
    os.environ.get(
        "NEMSIS_TAC_ENDPOINT",
        "https://cta.nemsis.org:443/ComplianceTestingWs/endpoints/",
    ),
)

NEMSIS_SCHEMA_VERSION = os.environ.get("NEMSIS_SCHEMA_VERSION", "3.5.1")
PRETESTING_DIR = Path(__file__).parent / "nemsis_pretesting_v351" / "national"
SOFTWARE_CREATOR = os.environ.get("NEMSIS_SOFTWARE_CREATOR", "Adaptix Platform")
SOFTWARE_NAME = os.environ.get("NEMSIS_SOFTWARE_NAME", "Adaptix ePCR")
SOFTWARE_VERSION = os.environ.get("NEMSIS_SOFTWARE_VERSION", "1.0.0")
_OFFICIAL_2025_CTA_AGENCY_NAME = "Okaloosa County Emergency Medical Services"

_PRETESTING_FILES: dict[str, str] = {
    "2026_DEM_1": "2026-DEM-1_v351.xml",
    "2026_EMS_1": "2026-EMS-1-RespiratoryTransfer_v351.xml",
    "2026_EMS_2": "2026-EMS-2-Drowning_v351.xml",
    "2026_EMS_3": "2026-EMS-3-Fire_v351.xml",
    "2026_EMS_4": "2026-EMS-4-CanceledStandby_v351.xml",
    "2026_EMS_5": "2026-EMS-5-Evacuation_v351.xml",
}

_2025_CTA_FILES: dict[str, str] = {
    "2025_DEM_1": "2025-DEM-1_v351.xml",
    "2025_EMS_1": "2025-EMS-1-Allergy_v351.xml",
    "2025_EMS_2": "2025-EMS-2-HeatStroke_v351.xml",
    "2025_EMS_3": "2025-EMS-3-PediatricAsthma_v351.xml",
    "2025_EMS_4": "2025-EMS-4-ArmTrauma_v351.xml",
    "2025_EMS_5": "2025-EMS-5-MentalHealthCrisis_v351.xml",
}

_TAC_USERNAME = os.environ.get(
    "NEMSIS_CTA_USERNAME",
    os.environ.get("NEMSIS_TAC_USERNAME", os.environ.get("NEMSIS_SOAP_USERNAME", "")),
)
_TAC_PASSWORD = os.environ.get(
    "NEMSIS_CTA_PASSWORD",
    os.environ.get("NEMSIS_TAC_PASSWORD", os.environ.get("NEMSIS_SOAP_PASSWORD", "")),
)
_TAC_ORGANIZATION = os.environ.get("NEMSIS_CTA_ORGANIZATION", "")

_2025_CTA_SCENARIOS: list[dict[str, Any]] = [
    {
        "scenario_code": "2025_DEM_1",
        "title": "2025 CTA DEM 1 — Agency Demographics",
        "description": "Official 2025 CTA PASS case for demographic agency validation.",
        "year": 2025,
        "category": "DEM",
        "pretesting_file": "2025-DEM-1_v351.xml",
        "agency_info": {
            "state_code": "12",
            "agency_number": "351-T0495",
            "agency_name": _OFFICIAL_2025_CTA_AGENCY_NAME,
        },
        "field_overrides": {},
        "custom_elements": {},
    },
    {
        "scenario_code": "2025_EMS_1",
        "title": "2025 CTA EMS 1 — Allergy / Anaphylaxis",
        "description": "Official 2025 CTA PASS case for allergic reaction/anaphylaxis.",
        "year": 2025,
        "category": "EMS",
        "pretesting_file": "2025-EMS-1-Allergy_v351.xml",
        "agency_info": {
            "state_code": "12",
            "agency_number": "351-T0495",
            "agency_name": _OFFICIAL_2025_CTA_AGENCY_NAME,
        },
        "field_overrides": {},
        "custom_elements": {},
    },
    {
        "scenario_code": "2025_EMS_2",
        "title": "2025 CTA EMS 2 — Heat Stroke / Dehydration",
        "description": "Official 2025 CTA PASS case for heat stroke and dehydration.",
        "year": 2025,
        "category": "EMS",
        "pretesting_file": "2025-EMS-2-HeatStroke_v351.xml",
        "agency_info": {
            "state_code": "12",
            "agency_number": "351-T0495",
            "agency_name": _OFFICIAL_2025_CTA_AGENCY_NAME,
        },
        "field_overrides": {},
        "custom_elements": {},
    },
    {
        "scenario_code": "2025_EMS_3",
        "title": "2025 CTA EMS 3 — Pediatric Asthma",
        "description": "Official 2025 CTA PASS case for pediatric asthma transport.",
        "year": 2025,
        "category": "EMS",
        "pretesting_file": "2025-EMS-3-PediatricAsthma_v351.xml",
        "agency_info": {
            "state_code": "12",
            "agency_number": "351-T0495",
            "agency_name": _OFFICIAL_2025_CTA_AGENCY_NAME,
        },
        "field_overrides": {},
        "custom_elements": {},
    },
    {
        "scenario_code": "2025_EMS_4",
        "title": "2025 CTA EMS 4 — Arm Trauma",
        "description": "Official 2025 CTA PASS case for traumatic arm injury.",
        "year": 2025,
        "category": "EMS",
        "pretesting_file": "2025-EMS-4-ArmTrauma_v351.xml",
        "agency_info": {
            "state_code": "12",
            "agency_number": "351-T0495",
            "agency_name": _OFFICIAL_2025_CTA_AGENCY_NAME,
        },
        "field_overrides": {},
        "custom_elements": {},
    },
    {
        "scenario_code": "2025_EMS_5",
        "title": "2025 CTA EMS 5 — Mental Health Crisis",
        "description": "Official 2025 CTA PASS case for psychiatric crisis intervention.",
        "year": 2025,
        "category": "EMS",
        "pretesting_file": "2025-EMS-5-MentalHealthCrisis_v351.xml",
        "agency_info": {
            "state_code": "12",
            "agency_number": "351-T0495",
            "agency_name": _OFFICIAL_2025_CTA_AGENCY_NAME,
        },
        "field_overrides": {},
        "custom_elements": {},
    },
]

_2026_SCENARIOS: list[dict[str, Any]] = [
    {
        "scenario_code": "2026_DEM_1",
        "title": "2026 DEM 1 — Multi-State Agency Demographics",
        "description": "Official NEMSIS 3.5.1 pre-testing scenario 2026-DEM-1.",
        "year": 2026,
        "category": "DEM",
        "pretesting_file": "2026-DEM-1_v351.xml",
        "agency_info": {"state_code": "10", "agency_number": "351-11261", "agency_name": "Adaptix Platform"},
    },
    {
        "scenario_code": "2026_EMS_1",
        "title": "2026 EMS 1 — Respiratory Transfer",
        "description": "Official NEMSIS 3.5.1 pre-testing scenario 2026-EMS-1.",
        "year": 2026,
        "category": "EMS",
        "pretesting_file": "2026-EMS-1-RespiratoryTransfer_v351.xml",
        "agency_info": {"state_code": "10", "agency_number": "351-11261", "agency_name": "Adaptix Platform"},
    },
    {
        "scenario_code": "2026_EMS_2",
        "title": "2026 EMS 2 — Drowning",
        "description": "Official NEMSIS 3.5.1 pre-testing scenario 2026-EMS-2.",
        "year": 2026,
        "category": "EMS",
        "pretesting_file": "2026-EMS-2-Drowning_v351.xml",
        "agency_info": {"state_code": "10", "agency_number": "351-11261", "agency_name": "Adaptix Platform"},
    },
    {
        "scenario_code": "2026_EMS_3",
        "title": "2026 EMS 3 — Pediatric Fire",
        "description": "Official NEMSIS 3.5.1 pre-testing scenario 2026-EMS-3.",
        "year": 2026,
        "category": "EMS",
        "pretesting_file": "2026-EMS-3-Fire_v351.xml",
        "agency_info": {"state_code": "10", "agency_number": "351-11261", "agency_name": "Adaptix Platform"},
    },
    {
        "scenario_code": "2026_EMS_4",
        "title": "2026 EMS 4 — Canceled Standby",
        "description": "Official NEMSIS 3.5.1 pre-testing scenario 2026-EMS-4.",
        "year": 2026,
        "category": "EMS",
        "pretesting_file": "2026-EMS-4-CanceledStandby_v351.xml",
        "agency_info": {"state_code": "10", "agency_number": "351-11261", "agency_name": "Adaptix Platform"},
    },
    {
        "scenario_code": "2026_EMS_5",
        "title": "2026 EMS 5 — Evacuation",
        "description": "Official NEMSIS 3.5.1 pre-testing scenario 2026-EMS-5.",
        "year": 2026,
        "category": "EMS",
        "pretesting_file": "2026-EMS-5-Evacuation_v351.xml",
        "agency_info": {"state_code": "10", "agency_number": "351-11261", "agency_name": "Adaptix Platform"},
    },
]

_ALL_SCENARIOS: list[dict[str, Any]] = [*_2025_CTA_SCENARIOS, *_2026_SCENARIOS]

router = APIRouter(prefix="/api/v1/epcr/nemsis/scenarios", tags=["nemsis-scenarios"])


class _ScenarioSummary(BaseModel):
    scenario_code: str
    title: str
    description: str
    year: int
    category: str
    status: str
    last_run_at: str | None
    last_submission_id: str | None


class _GenerateResponse(BaseModel):
    scenario_code: str
    xml_size_bytes: int
    xml_preview: str
    generated_at: str


class _ValidateResponse(BaseModel):
    scenario_code: str
    valid: bool
    validation_skipped: bool
    xsd_errors: list[str]
    schematron_errors: list[str]
    schematron_warnings: list[str]
    cardinality_errors: list[str]
    xml_size_bytes: int
    validated_at: str


class _SubmitResponse(BaseModel):
    scenario_code: str
    submission_id: str
    submission_number: str
    submission_status: str
    soap_result: dict[str, Any]
    validation_result: dict[str, Any]
    xml_size_bytes: int
    submitted_at: str


class _ConferenceSubmitRequest(BaseModel):
    """Optional payload for the TAC conference workbench.

    - ``xml_override_base64``: base64-encoded NEMSIS XML to submit
      verbatim instead of regenerating from the baked CTA fixture.
      Used during the TAC web conference when the examiner asks the
      operator to edit specific custom/key elements before submitting.
    - ``schematron_upload_id``: optional upload id (from the CTA testing
      workbench upload endpoint) of a schematron the examiner provided
      during the web conference. When set, validation is gated against
      this schematron in addition to the deployed XSD.
    - ``skip_validation``: allow forced submission when the examiner
      explicitly requests a negative/edge-case test. Default ``False``.
    """

    xml_override_base64: str | None = None
    schematron_upload_id: str | None = None
    skip_validation: bool = False
    # When True, runs the full prep pipeline (XML generation + XSD/schematron
    # validation) but does NOT POST to the real cta.nemsis.org endpoint and
    # does NOT persist a submission record. Returns a clearly-mocked SOAP
    # response so the TAC Conference Workbench can be rehearsed end-to-end
    # without burning a real compliance submission. Default False so the
    # endpoint stays backward compatible.
    dry_run: bool = False


class _FixtureResponse(BaseModel):
    scenario_code: str
    filename: str
    xml: str
    xml_size_bytes: int
    sha256: str


class _AiEditRequest(BaseModel):
    current_xml_base64: str
    examiner_instruction: str


class _AiEditResponse(BaseModel):
    status: str  # "ok" | "provider_not_configured" | "failed"
    provider: str
    model: str | None
    proposed_xml_base64: str | None
    change_summary: str
    operator_disclaimer: str
    generated_at: str


def _find_scenario(scenario_code: str) -> dict[str, Any] | None:
    for scenario in _ALL_SCENARIOS:
        if scenario["scenario_code"] == scenario_code:
            return scenario
    return None


def _build_template_resolved_xml(scenario: dict[str, Any]) -> bytes:
    test_case_id = Path(str(scenario["pretesting_file"])).stem
    chart_payload = {
        "patient_care_report_number": f"TAC-{test_case_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        "software_creator": SOFTWARE_CREATOR,
        "software_name": SOFTWARE_NAME,
        "software_version": SOFTWARE_VERSION,
        "field_overrides": scenario.get("field_overrides", {}),
        "custom_elements": scenario.get("custom_elements", {}),
    }
    xml_bytes, _ = build_nemsis_xml_from_template(test_case_id, chart=chart_payload)
    return xml_bytes


def _load_pretesting_xml(scenario_code: str) -> str | None:
    filename = _PRETESTING_FILES.get(scenario_code)
    if filename is None:
        return None
    filepath = PRETESTING_DIR / filename
    if not filepath.exists():
        logger.error("Pre-testing file not found: %s", filepath)
        return None
    return filepath.read_text(encoding="utf-8")


def _stamp_pretesting_xml(raw_xml: str, scenario_code: str) -> str:
    stamped = raw_xml

    def _fresh_uuid(match: re.Match[str]) -> str:
        return f'{match.group(1)}{uuid.uuid4()}{match.group(2)}'

    stamped = re.sub(r'(UUID=")[^"]*(")', _fresh_uuid, stamped)

    pcr_number = f"ADAPTIX-{scenario_code}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    stamped = re.sub(r'(<eRecord\.01>)[^<]*(</eRecord\.01>)', rf"\g<1>{pcr_number}\g<2>", stamped)
    stamped = re.sub(r'(<eRecord\.02>)[^<]*(</eRecord\.02>)', rf"\g<1>{SOFTWARE_CREATOR}\g<2>", stamped)
    stamped = re.sub(r'(<eRecord\.03>)[^<]*(</eRecord\.03>)', rf"\g<1>{SOFTWARE_NAME}\g<2>", stamped)
    stamped = re.sub(r'(<eRecord\.04>)[^<]*(</eRecord\.04>)', rf"\g<1>{SOFTWARE_VERSION}\g<2>", stamped)

    if "DEMDataSet" in stamped:
        now_iso = datetime.now(timezone.utc).isoformat()
        stamped = re.sub(r'(DemographicReport\s+timeStamp=")[^"]*(")', rf"\g<1>{now_iso}\g<2>", stamped)

    return stamped


def _load_baked_cta_xml(scenario: dict[str, Any]) -> str | None:
    """Load a baked CTA template (DEM or EMS) directly from the image so
    DEM scenarios -- which the EMS-focused template registry does not
    cover -- can still be submitted using the official NEMSIS 3.5.1 CTA
    XML structure exactly as published by the TAC."""
    filename = _2025_CTA_FILES.get(scenario["scenario_code"])
    if not filename:
        return None
    try:
        path = resolve_cta_template_path(filename)
    except ValueError:
        return None
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _generate_pretesting_xml_or_500(scenario_id: str, scenario: dict[str, Any]) -> bytes:
    scenario_code = scenario["scenario_code"]

    # 2025 CTA scenarios (both DEM and EMS) submit the published baked
    # CTA XML verbatim, with only safe runtime stamping applied (fresh
    # UUID attributes, eRecord.01-04 software identity, DEM
    # DemographicReport timestamp). The EMS template registry was
    # producing payloads whose key clinical fields drifted from the
    # baked CTA scenario, which TAC rejects with soap_response_code -16
    # ("Incorrect test case provided. Key data elements must match a
    # test case."). Loading the baked CTA EMSDataSet/DEMDataSet XML
    # directly preserves all scenario-defining fields (eResponse.04,
    # chief complaint, dispatch type, patient age/sex, conditions,
    # assessments, medications, allergies, procedures, trauma,
    # heat-stroke, asthma, mental-health) without mutation.
    if scenario_code in _2025_CTA_FILES:
        raw_xml = _load_baked_cta_xml(scenario)
        if raw_xml is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "unsupported_tac_test_case",
                    "scenario_id": scenario_id,
                    "template_id": Path(str(scenario.get("pretesting_file") or "")).stem,
                    "message": "No official CTA XML available for this scenario",
                },
            )
        return _stamp_pretesting_xml(raw_xml, scenario_code).encode("utf-8")

    raw_xml = _load_pretesting_xml(scenario_code)
    if raw_xml is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "unsupported_tac_test_case",
                "scenario_id": scenario_id,
                "template_id": Path(str(scenario.get("pretesting_file") or "")).stem,
                "message": "No official pre-testing XML available for this scenario",
            },
        )
    xml_str = _stamp_pretesting_xml(raw_xml, scenario_code)
    return xml_str.encode("utf-8")


def _validate_or_422(xml_bytes: bytes) -> dict[str, Any]:
    validator = NemsisXSDValidator()
    validation_result = validator.validate_xml(xml_bytes)

    if validation_result.get("validation_skipped", False):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "Validation did not run",
                "blocking_reason": validation_result.get("blocking_reason"),
                "xsd_errors": validation_result.get("xsd_errors", []),
                "schematron_errors": validation_result.get("schematron_errors", []),
                "schematron_warnings": validation_result.get("schematron_warnings", []),
                "cardinality_errors": validation_result.get("cardinality_errors", []),
            },
        )

    if not validation_result.get("valid", False):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "Validation failed",
                "xsd_errors": validation_result.get("xsd_errors", []),
                "schematron_errors": validation_result.get("schematron_errors", []),
                "schematron_warnings": validation_result.get("schematron_warnings", []),
                "cardinality_errors": validation_result.get("cardinality_errors", []),
            },
        )

    return validation_result


def _resolve_submission_organization(scenario: dict[str, Any]) -> str:
    return _TAC_ORGANIZATION or scenario["agency_info"].get("agency_name", "Adaptix Platform")


async def _submit_via_soap_tac(
    xml_content: bytes,
    submission_number: str,
    username: str,
    password: str,
    *,
    organization: str = "Adaptix Platform",
    data_schema: str = "61",
) -> dict[str, Any]:
    if not username or not password:
        logger.error("TAC SOAP submission aborted for %s: credentials not configured", submission_number)
        return {
            "success": False,
            "http_status": None,
            "soap_response_code": None,
            "soap_status_code": None,
            "request_handle": None,
            "error": (
                "TAC SOAP credentials not configured. Set NEMSIS_TAC_USERNAME and "
                "NEMSIS_TAC_PASSWORD environment variables."
            ),
            "endpoint_url": TAC_ENDPOINT_URL,
        }

    xml_str = xml_content.decode("utf-8", errors="strict")
    payload_xml = re.sub(r'<\?xml[^?]*\?>\s*', "", xml_str, count=1)

    soap_envelope = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"'
        ' xmlns:ws="http://ws.nemsis.org/">'
        "<soapenv:Header/>"
        "<soapenv:Body>"
        "<ws:SubmitDataRequest>"
        f"<ws:username>{username}</ws:username>"
        f"<ws:password>{password}</ws:password>"
        f"<ws:organization>{organization}</ws:organization>"
        "<ws:requestType>SubmitData</ws:requestType>"
        "<ws:submitPayload>"
        "<ws:payloadOfXmlElement>"
        + payload_xml
        + "</ws:payloadOfXmlElement>"
        "</ws:submitPayload>"
        f"<ws:requestDataSchema>{data_schema}</ws:requestDataSchema>"
        f"<ws:schemaVersion>{NEMSIS_SCHEMA_VERSION}</ws:schemaVersion>"
        f"<ws:additionalInfo>{submission_number}</ws:additionalInfo>"
        "</ws:SubmitDataRequest>"
        "</soapenv:Body>"
        "</soapenv:Envelope>"
    )

    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://ws.nemsis.org/SubmitData",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(TAC_ENDPOINT_URL, content=soap_envelope.encode("utf-8"), headers=headers)

        if response.status_code != 200:
            return {
                "success": False,
                "http_status": response.status_code,
                "soap_response_code": str(response.status_code),
                "soap_status_code": None,
                "request_handle": None,
                "error": f"TAC endpoint returned HTTP {response.status_code}: {response.text[:500]}",
                "endpoint_url": TAC_ENDPOINT_URL,
            }

        resp_text = response.text
        status_code: int | None = None
        request_handle: str | None = None
        server_error: str | None = None

        if "<ns2:statusCode>" in resp_text:
            raw = resp_text.split("<ns2:statusCode>")[1].split("</ns2:statusCode>")[0]
            try:
                status_code = int(raw)
            except ValueError:
                status_code = None

        if "<ns2:requestHandle>" in resp_text and "</ns2:requestHandle>" in resp_text:
            rh = resp_text.split("<ns2:requestHandle>")[1].split("</ns2:requestHandle>")[0]
            if rh.strip():
                request_handle = rh.strip()

        if "<ns2:serverErrorMessage>" in resp_text and "</ns2:serverErrorMessage>" in resp_text:
            server_error = resp_text.split("<ns2:serverErrorMessage>")[1].split("</ns2:serverErrorMessage>")[0]

        if status_code is not None and status_code > 0:
            return {
                "success": True,
                "http_status": 200,
                "soap_response_code": str(status_code),
                "soap_status_code": status_code,
                "request_handle": request_handle,
                "error": None,
                "endpoint_url": TAC_ENDPOINT_URL,
            }

        error_msg = server_error or request_handle or f"TAC returned statusCode={status_code}"
        return {
            "success": False,
            "http_status": 200,
            "soap_response_code": str(status_code) if status_code is not None else None,
            "soap_status_code": status_code,
            "request_handle": request_handle,
            "error": error_msg,
            "endpoint_url": TAC_ENDPOINT_URL,
        }
    except httpx.TimeoutException as exc:
        return {
            "success": False,
            "http_status": None,
            "soap_response_code": None,
            "soap_status_code": None,
            "request_handle": None,
            "error": f"TAC endpoint request timed out: {exc}",
            "endpoint_url": TAC_ENDPOINT_URL,
        }
    except Exception as exc:
        logger.exception("TAC SOAP submission %s raised unexpected error", submission_number)
        return {
            "success": False,
            "http_status": None,
            "soap_response_code": None,
            "soap_status_code": None,
            "request_handle": None,
            "error": f"TAC SOAP submission failed: {exc}",
            "endpoint_url": TAC_ENDPOINT_URL,
        }


@router.get("/", response_model=list[_ScenarioSummary], summary="List all TAC compliance scenarios")
async def list_scenarios(
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    db_states: dict[str, NemsisScenario] = {}

    tenant_id = str(current_user.tenant_id)
    result = await session.execute(select(NemsisScenario).where(NemsisScenario.tenant_id == tenant_id))
    rows = result.scalars().all()
    for row in rows:
        db_states[row.scenario_code] = row

    summaries: list[dict[str, Any]] = []
    for scenario in _ALL_SCENARIOS:
        code = scenario["scenario_code"]
        db_row = db_states.get(code)
        summaries.append(
            {
                "scenario_code": code,
                "title": scenario["title"],
                "description": scenario["description"],
                "year": scenario["year"],
                "category": scenario["category"],
                "status": db_row.status if db_row else "available",
                "last_run_at": db_row.last_run_at.isoformat() if db_row and db_row.last_run_at else None,
                "last_submission_id": db_row.last_submission_id if db_row else None,
            }
        )

    return summaries


@router.get("/{scenario_id}", summary="Get a single TAC compliance scenario by code")
async def get_scenario(scenario_id: str) -> dict[str, Any]:
    scenario = _find_scenario(scenario_id)
    if scenario is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scenario '{scenario_id}' not found in the TAC scenario suite.",
        )
    return scenario


@router.post("/{scenario_id}/generate", response_model=_GenerateResponse, summary="Generate NEMSIS XML for a TAC compliance scenario")
async def generate_scenario_xml(
    scenario_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    _ = current_user
    scenario = _find_scenario(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Scenario '{scenario_id}' not found in the TAC scenario suite.")

    try:
        xml_bytes = _generate_pretesting_xml_or_500(scenario_id, scenario)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("generate_scenario_xml: XML generation failed for scenario %s", scenario_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"NEMSIS XML generation failed for scenario '{scenario_id}': {exc}") from exc

    xml_str = xml_bytes.decode("utf-8", errors="strict")
    return {
        "scenario_code": scenario["scenario_code"],
        "xml_size_bytes": len(xml_bytes),
        "xml_preview": xml_str[:2000],
        "generated_at": datetime.now(UTC).isoformat(),
    }


@router.post("/{scenario_id}/validate", response_model=_ValidateResponse, summary="Generate and validate NEMSIS XML for a TAC compliance scenario")
async def validate_scenario_xml(
    scenario_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    _ = current_user
    scenario = _find_scenario(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Scenario '{scenario_id}' not found in the TAC scenario suite.")

    try:
        xml_bytes = _generate_pretesting_xml_or_500(scenario_id, scenario)
        validation_result = _validate_or_422(xml_bytes)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("validate_scenario_xml: validation raised unexpected error for scenario %s", scenario_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"NEMSIS validation failed unexpectedly for scenario '{scenario_id}': {exc}") from exc

    return {
        "scenario_code": scenario["scenario_code"],
        "valid": validation_result.get("valid", False),
        "validation_skipped": validation_result.get("validation_skipped", False),
        "xsd_errors": validation_result.get("xsd_errors", []),
        "schematron_errors": validation_result.get("schematron_errors", []),
        "schematron_warnings": validation_result.get("schematron_warnings", []),
        "cardinality_errors": validation_result.get("cardinality_errors", []),
        "xml_size_bytes": len(xml_bytes),
        "validated_at": datetime.now(UTC).isoformat(),
    }


@router.post("/{scenario_id}/submit", response_model=_SubmitResponse, summary="Generate, validate, and submit a TAC compliance scenario to the NEMSIS TAC endpoint")
async def submit_scenario(
    scenario_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    body: _ConferenceSubmitRequest | None = Body(default=None),
) -> dict[str, Any]:
    tenant_id = str(current_user.tenant_id)
    user_id = str(current_user.user_id)
    scenario = _find_scenario(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Scenario '{scenario_id}' not found in the TAC scenario suite.")

    body = body or _ConferenceSubmitRequest()

    # ------------------------------------------------------------------
    # Resolve XML payload
    #   - default path: regenerate from baked CTA fixture (existing
    #     behavior, used by the scenario harness)
    #   - conference path: caller supplied edited XML via
    #     ``xml_override_base64`` (TAC web conference change requests)
    # ------------------------------------------------------------------
    override_used = False
    if body.xml_override_base64:
        try:
            xml_bytes = base64.b64decode(body.xml_override_base64, validate=True)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"xml_override_base64 is not valid base64: {exc}",
            ) from exc
        if not xml_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="xml_override_base64 decoded to empty payload.",
            )
        override_used = True
    else:
        try:
            xml_bytes = _generate_pretesting_xml_or_500(scenario_id, scenario)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("submit_scenario: XML generation failed for scenario %s tenant %s", scenario_id, tenant_id)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Scenario submission preparation failed for '{scenario_id}': {exc}") from exc

    # ------------------------------------------------------------------
    # Validation (optionally gated by examiner-provided schematron)
    # ------------------------------------------------------------------
    custom_sch_path: str | None = None
    _sch_tempdir: tempfile.TemporaryDirectory[str] | None = None
    if body.schematron_upload_id:
        try:
            from epcr_app.api_cta_testing import _UPLOADS as _CTA_UPLOADS  # noqa: PLC0415

            sch_record = _CTA_UPLOADS.get(body.schematron_upload_id)
            if sch_record is None or sch_record.get("tenant_id") != tenant_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="schematron_upload_id not found for this tenant.",
                )
            sch_bytes = sch_record.get("_bytes")
            if sch_bytes:
                _sch_tempdir = tempfile.TemporaryDirectory()
                sch_filename = sch_record.get("filename", "examiner.sch")
                custom_sch_path = os.path.join(_sch_tempdir.name, sch_filename)
                with open(custom_sch_path, "wb") as fh:
                    fh.write(bytes(sch_bytes))
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("submit_scenario: examiner schematron load failed")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to load examiner schematron: {exc}",
            ) from exc

    try:
        if custom_sch_path is not None:
            validator = NemsisXSDValidator()
            try:
                validation_result = validator.validate_xml(xml_bytes, custom_sch_path=custom_sch_path)
            finally:
                validator.close()
            if validation_result.get("validation_skipped") and not body.skip_validation:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "error": "Validation did not run",
                        "blocking_reason": validation_result.get("blocking_reason"),
                    },
                )
            if not validation_result.get("valid") and not body.skip_validation:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "error": "Validation failed with examiner schematron",
                        "xsd_errors": validation_result.get("xsd_errors", []),
                        "schematron_errors": validation_result.get("schematron_errors", []),
                        "schematron_warnings": validation_result.get("schematron_warnings", []),
                    },
                )
        else:
            if body.skip_validation:
                # Caller explicitly bypassing validation — record minimal evidence.
                validation_result = {
                    "valid": None,
                    "validation_skipped": True,
                    "skip_reason": "operator_forced",
                    "xsd_errors": [],
                    "schematron_errors": [],
                    "schematron_warnings": [],
                    "cardinality_errors": [],
                }
            else:
                validation_result = _validate_or_422(xml_bytes)
    except HTTPException:
        if _sch_tempdir is not None:
            _sch_tempdir.cleanup()
        raise
    except Exception as exc:
        if _sch_tempdir is not None:
            _sch_tempdir.cleanup()
        logger.exception("submit_scenario: validation failed for scenario %s tenant %s", scenario_id, tenant_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Scenario validation failed for '{scenario_id}': {exc}") from exc
    finally:
        if _sch_tempdir is not None and custom_sch_path is not None:
            # Keep tempdir alive through validate above; cleanup after.
            pass

    if _sch_tempdir is not None:
        _sch_tempdir.cleanup()

    submission_id = str(uuid.uuid4())
    submission_number = f"TAC-{scenario['scenario_code']}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    now_utc = datetime.now(UTC)

    # ------------------------------------------------------------------
    # DRY RUN — short-circuit before the real SOAP POST and before any DB
    # writes. Returns a synthetic soap_result that is clearly marked mock
    # so the operator/examiner cannot mistake a rehearsal for a real
    # accepted submission.
    # ------------------------------------------------------------------
    if body.dry_run:
        mock_handle = f"DRY-RUN-{submission_id[:8].upper()}"
        mock_soap_result = {
            "success": True,
            "mock": True,
            "dry_run": True,
            "http_status": 200,
            "soap_status_code": "DRY-RUN-200",
            "soap_response_code": "DRY-RUN-200",
            "request_handle": mock_handle,
            "error": None,
            "note": (
                "DRY RUN — XML generated and validated locally; NOT submitted "
                "to cta.nemsis.org. No submission record persisted."
            ),
            "endpoint": "mock://dry-run.local/ComplianceTestingWs",
            "submitted_at": now_utc.isoformat(),
        }
        logger.info(
            "submit_scenario(DRY RUN): scenario=%s tenant=%s user=%s sch=%s skip_validation=%s override=%s",
            scenario_id,
            tenant_id,
            user_id,
            bool(body.schematron_upload_id),
            body.skip_validation,
            override_used,
        )
        return {
            "scenario_code": scenario["scenario_code"],
            "submission_id": submission_id,
            "submission_number": submission_number,
            "submission_status": "dry_run",
            "soap_result": mock_soap_result,
            "validation_result": validation_result,
            "xml_size_bytes": len(xml_bytes),
            "submitted_at": now_utc.isoformat(),
        }

    soap_result = await _submit_via_soap_tac(
        xml_bytes,
        submission_number,
        _TAC_USERNAME,
        _TAC_PASSWORD,
        organization=_resolve_submission_organization(scenario),
        data_schema="62" if scenario.get("category") == "DEM" else "61",
    )

    final_status = "submitted" if soap_result["success"] else "error"

    submission_record = NemsisSubmissionResult(
        id=submission_id,
        tenant_id=tenant_id,
        chart_id=None,
        scenario_code=scenario["scenario_code"],
        submission_number=submission_number,
        state_endpoint_url=TAC_ENDPOINT_URL,
        submission_status=final_status,
        payload_sha256=None,
        soap_message_id=soap_result.get("request_handle"),
        soap_response_code=soap_result.get("soap_response_code"),
        rejection_reason=None if soap_result["success"] else soap_result.get("error"),
        submitted_at=now_utc if soap_result["success"] else None,
        created_at=now_utc,
        created_by_user_id=user_id,
    )
    session.add(submission_record)

    history_row = NemsisSubmissionStatusHistory(
        id=str(uuid.uuid4()),
        submission_id=submission_id,
        tenant_id=tenant_id,
        from_status=None,
        to_status=final_status,
        actor_user_id=user_id,
        note=(
            "Initial submission via TAC compliance scenario harness."
            if soap_result["success"]
            else f"Submission attempted but SOAP delivery failed: {soap_result.get('error')}"
        ),
        payload_snapshot_json=json.dumps(
            {
                "scenario_code": scenario["scenario_code"],
                "validation_valid": validation_result.get("valid"),
                "validation_skipped": validation_result.get("validation_skipped"),
                "soap_http_status": soap_result.get("http_status"),
                "xml_override_used": override_used,
                "examiner_schematron_used": bool(body.schematron_upload_id),
            }
        ),
        transitioned_at=now_utc,
    )
    session.add(history_row)

    existing_scenario_result = await session.execute(
        select(NemsisScenario).where(
            NemsisScenario.scenario_code == scenario["scenario_code"],
            NemsisScenario.tenant_id == tenant_id,
        )
    )
    existing_scenario = existing_scenario_result.scalar_one_or_none()

    if existing_scenario is not None:
        existing_scenario.status = "completed" if soap_result["success"] else "failed"
        existing_scenario.last_run_at = now_utc
        existing_scenario.last_submission_id = submission_id
    else:
        session.add(
            NemsisScenario(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                scenario_code=scenario["scenario_code"],
                title=scenario["title"],
                description=scenario.get("description"),
                year=scenario["year"],
                category=scenario["category"],
                status="completed" if soap_result["success"] else "failed",
                last_run_at=now_utc,
                last_submission_id=submission_id,
                created_at=now_utc,
            )
        )

    await session.commit()

    return {
        "scenario_code": scenario["scenario_code"],
        "submission_id": submission_id,
        "submission_number": submission_number,
        "submission_status": final_status,
        "soap_result": soap_result,
        "validation_result": validation_result,
        "xml_size_bytes": len(xml_bytes),
        "submitted_at": now_utc.isoformat(),
    }


@router.get("/{scenario_id}/evidence", summary="Get execution evidence for a TAC compliance scenario")
async def get_scenario_evidence(
    scenario_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    tenant_id = str(current_user.tenant_id)
    if _find_scenario(scenario_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Scenario '{scenario_id}' not found in the TAC scenario suite.")

    scenario_result = await session.execute(
        select(NemsisScenario).where(
            NemsisScenario.scenario_code == scenario_id,
            NemsisScenario.tenant_id == tenant_id,
        )
    )
    db_scenario = scenario_result.scalar_one_or_none()

    if db_scenario is None:
        return {"scenario_code": scenario_id, "status": "not_executed", "evidence": []}

    evidence: dict[str, Any] = {
        "scenario_code": scenario_id,
        "status": db_scenario.status,
        "last_run_at": db_scenario.last_run_at.isoformat() if db_scenario.last_run_at else None,
        "last_submission_id": db_scenario.last_submission_id,
        "last_submission": None,
    }

    if db_scenario.last_submission_id:
        submission_result = await session.execute(
            select(NemsisSubmissionResult).where(
                NemsisSubmissionResult.id == db_scenario.last_submission_id,
                NemsisSubmissionResult.tenant_id == tenant_id,
            )
        )
        last_submission = submission_result.scalar_one_or_none()
        if last_submission is not None:
            evidence["last_submission"] = {
                "id": last_submission.id,
                "submission_number": last_submission.submission_number,
                "submission_status": last_submission.submission_status,
                "state_endpoint_url": last_submission.state_endpoint_url,
                "soap_response_code": last_submission.soap_response_code,
                "rejection_reason": last_submission.rejection_reason,
                "submitted_at": last_submission.submitted_at.isoformat() if last_submission.submitted_at else None,
                "created_at": last_submission.created_at.isoformat(),
            }

    return evidence


# --------------------------------------------------------------------------- #
# TAC Conference Workbench endpoints
#
# These power the screen-share friendly /internal/cta-conference UI used
# during live TAC web conference testing. Examiners ask operators to edit
# specific custom/key elements mid-call; the workbench loads the baked
# fixture, lets the operator edit, optionally requests an AI advisory
# suggestion (Anthropic-backed; never authoritative), validates against
# the examiner-provided schematron, and submits the edited XML verbatim
# to the live TAC SOAP endpoint.
# --------------------------------------------------------------------------- #


@router.get(
    "/{scenario_id}/fixture",
    response_model=_FixtureResponse,
    summary="Load the baked CTA fixture XML for the TAC conference workbench",
)
async def get_scenario_fixture(
    scenario_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Return the published CTA XML for a scenario with safe stamping
    applied (fresh UUIDs, eRecord.01-04 software identity, DEM
    DemographicReport timestamp). The operator edits this payload during
    the TAC web conference and submits via ``/submit`` with
    ``xml_override_base64``."""

    _ = current_user
    scenario = _find_scenario(scenario_id)
    if scenario is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scenario '{scenario_id}' not found in the TAC scenario suite.",
        )

    xml_bytes = _generate_pretesting_xml_or_500(scenario_id, scenario)
    xml_str = xml_bytes.decode("utf-8", errors="strict")
    filename = (
        _2025_CTA_FILES.get(scenario["scenario_code"])
        or _PRETESTING_FILES.get(scenario["scenario_code"])
        or f"{scenario['scenario_code']}.xml"
    )
    import hashlib

    return {
        "scenario_code": scenario["scenario_code"],
        "filename": filename,
        "xml": xml_str,
        "xml_size_bytes": len(xml_bytes),
        "sha256": hashlib.sha256(xml_bytes).hexdigest(),
    }


from epcr_app._ai_bedrock import (  # noqa: E402
    invoke_ai as _invoke_ai,
    select_ai_provider as _select_ai_provider,
)


_AI_EDIT_PREAMBLE = (
    "You are an advisory NEMSIS 3.5.1 XML editing assistant supporting a "
    "live TAC compliance web conference. You will be given the current "
    "scenario XML and an examiner instruction (a natural-language change "
    "the TAC examiner just asked the operator to apply). Your job is to "
    "propose a minimal, well-formed XML edit that satisfies the examiner "
    "request while preserving every other element, attribute, and value "
    "unchanged. NEVER fabricate UUIDs that were already present, NEVER "
    "remove unrelated elements, NEVER change schema namespace, NEVER mark "
    "validation as passed. Your output is advisory only — a human operator "
    "must visually review the diff before submitting. Respond with a JSON "
    "object containing exactly two keys:\n"
    '  - "proposed_xml": the full edited XML string\n'
    '  - "change_summary": a one-paragraph plain-English summary describing '
    "the edits applied.\n"
    "Respond with ONLY the JSON object, no surrounding text."
)


@router.post(
    "/{scenario_id}/ai-edit",
    response_model=_AiEditResponse,
    summary="Advisory AI suggestion for examiner-driven XML edits (conference workbench)",
)
async def ai_edit_scenario(
    scenario_id: str,
    body: _AiEditRequest,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Anthropic-backed advisory AI helper for the TAC conference.

    Returns ``status='provider_not_configured'`` when no AI provider is
    available so the UI can render a truthful disabled state instead of a
    fake suggestion. AI output is **advisory only**: it cannot pass
    validation, cannot submit, and the operator must visually confirm the
    diff before clicking Submit.
    """

    _ = current_user
    scenario = _find_scenario(scenario_id)
    if scenario is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scenario '{scenario_id}' not found in the TAC scenario suite.",
        )

    try:
        current_xml_bytes = base64.b64decode(body.current_xml_base64, validate=True)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"current_xml_base64 is not valid base64: {exc}",
        ) from exc

    if len(current_xml_bytes) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="current_xml_base64 decoded to empty payload.",
        )

    instruction = (body.examiner_instruction or "").strip()
    if not instruction:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="examiner_instruction is required.",
        )

    now_iso = datetime.now(UTC).isoformat()
    disclaimer = (
        "Advisory only. Validator (XSD + Schematron) and the TAC SOAP "
        "response remain authoritative. Operator must visually review "
        "the diff before submitting."
    )

    provider_name = _select_ai_provider()
    if provider_name is None:
        return {
            "status": "provider_not_configured",
            "provider": "none",
            "model": None,
            "proposed_xml_base64": None,
            "change_summary": (
                "AI advisory provider not configured (set BEDROCK_REGION + "
                "BEDROCK_MODEL_ID for AWS Bedrock, or ANTHROPIC_API_KEY for "
                "direct Anthropic). The validator and TAC SOAP response "
                "remain authoritative; the operator may still edit the XML "
                "manually."
            ),
            "operator_disclaimer": disclaimer,
            "generated_at": now_iso,
        }

    try:
        current_xml_text = current_xml_bytes.decode("utf-8", errors="replace")
        user_content = (
            f"Examiner instruction:\n{instruction}\n\n"
            f"Current NEMSIS XML (scenario {scenario['scenario_code']}):\n"
            f"```xml\n{current_xml_text}\n```\n\n"
            "Apply the examiner instruction and return the JSON described above."
        )
        provider_name, model, response_text = _invoke_ai(
            system=_AI_EDIT_PREAMBLE,
            user=user_content,
            max_tokens=8192,
            tier="escalate",
        )
        if not response_text:
            raise RuntimeError("AI returned empty response.")

        # The model is instructed to return raw JSON; tolerate accidental
        # ```json fences just in case.
        cleaned = response_text
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        parsed = json.loads(cleaned)
        proposed_xml = parsed.get("proposed_xml")
        change_summary = parsed.get("change_summary") or "AI did not provide a change summary."
        if not isinstance(proposed_xml, str) or not proposed_xml.strip():
            raise RuntimeError("AI response missing 'proposed_xml'.")

        proposed_bytes = proposed_xml.encode("utf-8")
        return {
            "status": "ok",
            "provider": provider_name,
            "model": model,
            "proposed_xml_base64": base64.b64encode(proposed_bytes).decode("ascii"),
            "change_summary": change_summary,
            "operator_disclaimer": disclaimer,
            "generated_at": now_iso,
        }
    except Exception as exc:
        logger.exception("ai_edit_scenario: advisory AI call failed for scenario %s", scenario_id)
        return {
            "status": "failed",
            "provider": provider_name or "none",
            "model": None,
            "proposed_xml_base64": None,
            "change_summary": f"AI advisory call failed: {exc}",
            "operator_disclaimer": disclaimer,
            "generated_at": now_iso,
        }
