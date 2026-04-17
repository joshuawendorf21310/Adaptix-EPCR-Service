"""NEMSIS compliance studio scenario management and execution API routes.

Provides routes for managing and executing 2026 TAC compliance studio
scenarios. Scenarios define the test cases required for NEMSIS TAC
certification. Execution generates real NEMSIS XML, runs validation,
persists evidence, and optionally submits through the live submission path.

The 2026 scenario suite includes:
- DEM 1: Demographic dataset compliance scenario
- EMS 1 Crash: Motor vehicle crash response
- EMS 2 Stroke: Stroke response
- EMS 3 CHF: Congestive heart failure response
- EMS 4 Seizure: Seizure response
- EMS 5 Delirium: Delirium response

Routes:
- GET    /api/v1/epcr/nemsis/scenarios                              — list scenarios
- GET    /api/v1/epcr/nemsis/scenarios/{scenario_id}               — get scenario
- POST   /api/v1/epcr/nemsis/scenarios/{scenario_id}/generate      — generate XML
- POST   /api/v1/epcr/nemsis/scenarios/{scenario_id}/validate      — validate XML
- POST   /api/v1/epcr/nemsis/scenarios/{scenario_id}/submit        — submit to TAC
- GET    /api/v1/epcr/nemsis/scenarios/{scenario_id}/evidence      — get evidence
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.models_nemsis_core import (
    NemsisScenario,
    NemsisSubmissionResult,
    NemsisSubmissionStatusHistory,
)
from epcr_app.nemsis_exporter import NEMSISExporter
from epcr_app.nemsis_xsd_validator import NemsisXSDValidator

logger = logging.getLogger(__name__)

TAC_ENDPOINT_URL = (
    "https://cta.nemsis.org/ComplianceTestingWs/endpoints/compliancetestingws"
)

_TAC_USERNAME = os.environ.get(
    "NEMSIS_TAC_USERNAME", os.environ.get("NEMSIS_SOAP_USERNAME", "")
)
_TAC_PASSWORD = os.environ.get(
    "NEMSIS_TAC_PASSWORD", os.environ.get("NEMSIS_SOAP_PASSWORD", "")
)

_2026_SCENARIOS: list[dict[str, Any]] = [
    {
        "scenario_code": "2026_DEM_1",
        "title": "2026 DEM 1 — Demographic Dataset Compliance",
        "description": (
            "Validates agency demographic dataset fields against NEMSIS 3.5.1 requirements."
        ),
        "year": 2026,
        "category": "DEM",
        "agency_info": {
            "state_code": "55",
            "agency_number": "WI-FQ-001",
            "agency_name": "FusionEMSQuantum",
        },
        "chart": {
            "id": "DEM1-CHART-0001",
            "report_number": "2026-DEM-001",
            "call_type": "9902001",
            "priority": "2205001",
            "call_received_at": "2026-01-15T10:00:00",
            "dispatched_at": "2026-01-15T10:01:00",
            "en_route_at": "2026-01-15T10:02:00",
            "on_scene_at": "2026-01-15T10:08:00",
            "transport_at": "2026-01-15T10:25:00",
            "cleared_at": "2026-01-15T10:45:00",
            "patient_first_name": "DEMO",
            "patient_last_name": "PATIENT",
            "patient_dob": "1965-01-01",
            "patient_gender": "male",
            "chief_complaint": "Demographic compliance test",
            "narrative": (
                "This record is generated for NEMSIS 2026 DEM 1 TAC compliance testing."
            ),
            "destination_facility": "General Hospital",
            "incident_number": "DEM-2026-001",
        },
    },
    {
        "scenario_code": "2026_EMS_1_CRASH",
        "title": "2026 EMS 1 — Motor Vehicle Crash",
        "description": (
            "Motor vehicle crash response scenario for NEMSIS 3.5.1 TAC 2026 EMS 1."
        ),
        "year": 2026,
        "category": "EMS",
        "agency_info": {
            "state_code": "55",
            "agency_number": "WI-FQ-001",
            "agency_name": "FusionEMSQuantum",
        },
        "chart": {
            "id": "EMS1-CHART-0001",
            "report_number": "2026-EMS-001",
            "call_type": "9902003",
            "priority": "2205003",
            "call_received_at": "2026-01-15T14:00:00",
            "dispatched_at": "2026-01-15T14:01:30",
            "en_route_at": "2026-01-15T14:02:00",
            "on_scene_at": "2026-01-15T14:09:00",
            "transport_at": "2026-01-15T14:35:00",
            "cleared_at": "2026-01-15T14:55:00",
            "patient_first_name": "CRASH",
            "patient_last_name": "VICTIM",
            "patient_dob": "1990-06-15",
            "patient_gender": "male",
            "chief_complaint": "Motor vehicle crash with multiple trauma",
            "narrative": (
                "Patient involved in MVC with significant mechanism. Responsive on scene, "
                "GCS 14. IV access established. Transported emergent to trauma center."
            ),
            "destination_facility": "Trauma Center",
            "incident_number": "MVC-2026-001",
            "transport_mode": "emergent",
            "level_of_care": "als",
            "vitals": [
                {
                    "time": "2026-01-15T14:12:00",
                    "systolic_bp": "94",
                    "diastolic_bp": "60",
                    "heart_rate": "112",
                    "respiratory_rate": "22",
                    "spo2": "97",
                    "gcs_total": "14",
                },
                {
                    "time": "2026-01-15T14:25:00",
                    "systolic_bp": "108",
                    "diastolic_bp": "70",
                    "heart_rate": "98",
                    "respiratory_rate": "18",
                    "spo2": "99",
                    "gcs_total": "15",
                },
            ],
            "procedures": [
                {
                    "time": "2026-01-15T14:15:00",
                    "procedure": "IV Access",
                    "attempts": 1,
                    "successful": True,
                },
                {
                    "time": "2026-01-15T14:18:00",
                    "procedure": "Spinal Motion Restriction",
                    "attempts": 1,
                    "successful": True,
                },
            ],
        },
    },
    {
        "scenario_code": "2026_EMS_2_STROKE",
        "title": "2026 EMS 2 — Stroke Response",
        "description": (
            "Stroke response scenario for NEMSIS 3.5.1 TAC 2026 EMS 2."
        ),
        "year": 2026,
        "category": "EMS",
        "agency_info": {
            "state_code": "55",
            "agency_number": "WI-FQ-001",
            "agency_name": "FusionEMSQuantum",
        },
        "chart": {
            "id": "EMS2-CHART-0001",
            "report_number": "2026-EMS-002",
            "call_type": "9902001",
            "priority": "2205003",
            "call_received_at": "2026-02-10T09:00:00",
            "dispatched_at": "2026-02-10T09:01:00",
            "en_route_at": "2026-02-10T09:02:00",
            "on_scene_at": "2026-02-10T09:09:00",
            "transport_at": "2026-02-10T09:28:00",
            "cleared_at": "2026-02-10T09:50:00",
            "patient_first_name": "STROKE",
            "patient_last_name": "PATIENT",
            "patient_dob": "1952-03-22",
            "patient_gender": "female",
            "chief_complaint": "Facial droop and arm weakness, onset 30 minutes prior",
            "narrative": (
                "76yo female presenting with sudden onset facial droop, left arm weakness, "
                "slurred speech. FAST positive. Last known well 30 minutes prior. "
                "Transported emergent to stroke center."
            ),
            "destination_facility": "Stroke Center",
            "incident_number": "STR-2026-001",
            "transport_mode": "emergent",
            "level_of_care": "als",
            "vitals": [
                {
                    "time": "2026-02-10T09:11:00",
                    "systolic_bp": "168",
                    "diastolic_bp": "98",
                    "heart_rate": "88",
                    "respiratory_rate": "16",
                    "spo2": "96",
                    "glucose": "132",
                },
            ],
            "history": ["Hypertension", "Atrial fibrillation"],
            "medications": [
                {
                    "time": "2026-02-10T09:15:00",
                    "drug": "Normal Saline",
                    "dose": "250",
                    "dose_unit": "mL",
                    "route": "IV",
                    "prior_to_our_care": False,
                },
            ],
        },
    },
    {
        "scenario_code": "2026_EMS_3_CHF",
        "title": "2026 EMS 3 — Congestive Heart Failure",
        "description": (
            "CHF response scenario for NEMSIS 3.5.1 TAC 2026 EMS 3."
        ),
        "year": 2026,
        "category": "EMS",
        "agency_info": {
            "state_code": "55",
            "agency_number": "WI-FQ-001",
            "agency_name": "FusionEMSQuantum",
        },
        "chart": {
            "id": "EMS3-CHART-0001",
            "report_number": "2026-EMS-003",
            "call_type": "9902001",
            "priority": "2205003",
            "call_received_at": "2026-03-05T20:00:00",
            "dispatched_at": "2026-03-05T20:01:00",
            "en_route_at": "2026-03-05T20:02:00",
            "on_scene_at": "2026-03-05T20:10:00",
            "transport_at": "2026-03-05T20:35:00",
            "cleared_at": "2026-03-05T20:55:00",
            "patient_first_name": "CHF",
            "patient_last_name": "PATIENT",
            "patient_dob": "1948-11-08",
            "patient_gender": "male",
            "chief_complaint": "Severe shortness of breath, orthopnea, bilateral leg swelling",
            "narrative": (
                "78yo male with known CHF presenting with acute exacerbation. "
                "Significant respiratory distress, BiPAP applied, furosemide administered IV. "
                "Transported to cardiac center."
            ),
            "destination_facility": "Cardiac Center",
            "incident_number": "CHF-2026-001",
            "transport_mode": "emergent",
            "level_of_care": "als",
            "vitals": [
                {
                    "time": "2026-03-05T20:12:00",
                    "systolic_bp": "186",
                    "diastolic_bp": "102",
                    "heart_rate": "106",
                    "respiratory_rate": "28",
                    "spo2": "86",
                    "etco2": "32",
                },
                {
                    "time": "2026-03-05T20:25:00",
                    "systolic_bp": "162",
                    "diastolic_bp": "90",
                    "heart_rate": "94",
                    "respiratory_rate": "20",
                    "spo2": "93",
                    "etco2": "38",
                },
            ],
            "history": [
                "Congestive heart failure",
                "Hypertension",
                "Diabetes mellitus type 2",
            ],
            "medications": [
                {
                    "time": "2026-03-05T20:18:00",
                    "drug": "Furosemide",
                    "dose": "40",
                    "dose_unit": "mg",
                    "route": "IV",
                    "prior_to_our_care": False,
                },
                {
                    "time": "2026-03-05T20:20:00",
                    "drug": "Nitroglycerin",
                    "dose": "0.4",
                    "dose_unit": "mg",
                    "route": "SL",
                    "prior_to_our_care": False,
                },
            ],
        },
    },
    {
        "scenario_code": "2026_EMS_4_SEIZURE",
        "title": "2026 EMS 4 — Seizure",
        "description": (
            "Seizure response scenario for NEMSIS 3.5.1 TAC 2026 EMS 4."
        ),
        "year": 2026,
        "category": "EMS",
        "agency_info": {
            "state_code": "55",
            "agency_number": "WI-FQ-001",
            "agency_name": "FusionEMSQuantum",
        },
        "chart": {
            "id": "EMS4-CHART-0001",
            "report_number": "2026-EMS-004",
            "call_type": "9902001",
            "priority": "2205003",
            "call_received_at": "2026-04-12T16:00:00",
            "dispatched_at": "2026-04-12T16:01:00",
            "en_route_at": "2026-04-12T16:02:00",
            "on_scene_at": "2026-04-12T16:08:00",
            "transport_at": "2026-04-12T16:30:00",
            "cleared_at": "2026-04-12T16:50:00",
            "patient_first_name": "SEIZURE",
            "patient_last_name": "PATIENT",
            "patient_dob": "2005-07-04",
            "patient_gender": "female",
            "chief_complaint": "Generalized tonic-clonic seizure, second episode today",
            "narrative": (
                "21yo female with history of epilepsy presenting with generalized "
                "tonic-clonic seizure, second episode within 4 hours. Midazolam administered "
                "IM with cessation of seizure activity. Transported to ED."
            ),
            "destination_facility": "Emergency Department",
            "incident_number": "SEZ-2026-001",
            "transport_mode": "emergent",
            "level_of_care": "als",
            "vitals": [
                {
                    "time": "2026-04-12T16:10:00",
                    "systolic_bp": "138",
                    "diastolic_bp": "82",
                    "heart_rate": "118",
                    "respiratory_rate": "18",
                    "spo2": "95",
                    "gcs_total": "8",
                },
                {
                    "time": "2026-04-12T16:22:00",
                    "systolic_bp": "122",
                    "diastolic_bp": "74",
                    "heart_rate": "96",
                    "respiratory_rate": "16",
                    "spo2": "98",
                    "gcs_total": "14",
                },
            ],
            "history": ["Epilepsy"],
            "medications": [
                {
                    "time": "2026-04-12T16:12:00",
                    "drug": "Midazolam",
                    "dose": "5",
                    "dose_unit": "mg",
                    "route": "IM",
                    "prior_to_our_care": False,
                },
            ],
        },
    },
    {
        "scenario_code": "2026_EMS_5_DELIRIUM",
        "title": "2026 EMS 5 — Delirium",
        "description": (
            "Delirium response scenario for NEMSIS 3.5.1 TAC 2026 EMS 5."
        ),
        "year": 2026,
        "category": "EMS",
        "agency_info": {
            "state_code": "55",
            "agency_number": "WI-FQ-001",
            "agency_name": "FusionEMSQuantum",
        },
        "chart": {
            "id": "EMS5-CHART-0001",
            "report_number": "2026-EMS-005",
            "call_type": "9902001",
            "priority": "2205001",
            "call_received_at": "2026-05-20T08:00:00",
            "dispatched_at": "2026-05-20T08:01:00",
            "en_route_at": "2026-05-20T08:02:00",
            "on_scene_at": "2026-05-20T08:10:00",
            "transport_at": "2026-05-20T08:40:00",
            "cleared_at": "2026-05-20T09:00:00",
            "patient_first_name": "DELIRIUM",
            "patient_last_name": "PATIENT",
            "patient_dob": "1935-04-18",
            "patient_gender": "male",
            "chief_complaint": "Acute onset confusion and agitation, possible UTI",
            "narrative": (
                "90yo male nursing home resident with acute onset delirium. Agitated and "
                "disoriented. History of dementia. Afebrile on scene. IV access established "
                "and transported to ED for workup."
            ),
            "destination_facility": "Emergency Department",
            "incident_number": "DEL-2026-001",
            "transport_mode": "non_emergent",
            "level_of_care": "bls",
            "vitals": [
                {
                    "time": "2026-05-20T08:12:00",
                    "systolic_bp": "146",
                    "diastolic_bp": "88",
                    "heart_rate": "92",
                    "respiratory_rate": "18",
                    "spo2": "96",
                    "glucose": "98",
                },
            ],
            "history": [
                "Dementia",
                "Hypertension",
                "Benign prostatic hyperplasia",
            ],
        },
    },
]

router = APIRouter(prefix="/api/v1/epcr/nemsis/scenarios", tags=["nemsis-scenarios"])


class _ScenarioSummary(BaseModel):
    """Summary representation of a single TAC compliance scenario."""

    scenario_code: str
    title: str
    description: str
    year: int
    category: str
    status: str
    last_run_at: str | None
    last_submission_id: str | None


class _GenerateResponse(BaseModel):
    """Response body for the XML generation route."""

    scenario_code: str
    xml_size_bytes: int
    xml_preview: str
    generated_at: str


class _ValidateResponse(BaseModel):
    """Response body for the XML validation route."""

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
    """Response body for the TAC submission route."""

    scenario_code: str
    submission_id: str
    submission_number: str
    submission_status: str
    soap_result: dict[str, Any]
    validation_result: dict[str, Any]
    xml_size_bytes: int
    submitted_at: str


def _find_scenario(scenario_code: str) -> dict[str, Any] | None:
    """Return the scenario definition dict for a given scenario_code, or None.

    Args:
        scenario_code: The TAC-assigned code to look up (e.g. '2026_DEM_1').

    Returns:
        The matching scenario dict from _2026_SCENARIOS, or None if not found.
    """
    for scenario in _2026_SCENARIOS:
        if scenario["scenario_code"] == scenario_code:
            return scenario
    return None


async def _submit_via_soap_tac(
    xml_content: bytes,
    submission_number: str,
    username: str,
    password: str,
) -> dict[str, Any]:
    """Attempt a SOAP submission of NEMSIS XML to the TAC compliance endpoint.

    Constructs and POSTs a minimal SOAP 1.1 envelope wrapping the NEMSIS
    XML payload to TAC_ENDPOINT_URL. Returns a structured dict describing
    the outcome. Never silently swallows failure.

    Args:
        xml_content: Raw UTF-8 NEMSIS XML bytes to submit.
        submission_number: Unique submission tracking number.
        username: TAC SOAP username credential.
        password: TAC SOAP password credential.

    Returns:
        Dict with keys: success (bool), http_status (int | None),
        soap_response_code (str | None), error (str | None),
        endpoint_url (str).
    """
    if not username or not password:
        logger.error(
            "TAC SOAP submission aborted for %s: credentials not configured",
            submission_number,
        )
        return {
            "success": False,
            "http_status": None,
            "soap_response_code": None,
            "error": (
                "TAC SOAP credentials not configured. "
                "Set NEMSIS_TAC_USERNAME and NEMSIS_TAC_PASSWORD environment variables."
            ),
            "endpoint_url": TAC_ENDPOINT_URL,
        }

    xml_str = xml_content.decode("utf-8", errors="replace")
    soap_envelope = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"'
        ' xmlns:cta="http://cta.nemsis.org/">'
        "<soapenv:Header/>"
        "<soapenv:Body>"
        "<cta:submitEMSData>"
        f"<cta:submissionNumber>{submission_number}</cta:submissionNumber>"
        f"<cta:username>{username}</cta:username>"
        f"<cta:password>{password}</cta:password>"
        f"<cta:emsData><![CDATA[{xml_str}]]></cta:emsData>"
        "</cta:submitEMSData>"
        "</soapenv:Body>"
        "</soapenv:Envelope>"
    )

    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "submitEMSData",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                TAC_ENDPOINT_URL,
                content=soap_envelope.encode("utf-8"),
                headers=headers,
            )

        logger.info(
            "TAC SOAP submission %s: HTTP %d",
            submission_number,
            response.status_code,
        )

        if response.status_code == 200:
            return {
                "success": True,
                "http_status": response.status_code,
                "soap_response_code": "200",
                "error": None,
                "endpoint_url": TAC_ENDPOINT_URL,
            }

        logger.error(
            "TAC SOAP submission %s failed: HTTP %d — %s",
            submission_number,
            response.status_code,
            response.text[:500],
        )
        return {
            "success": False,
            "http_status": response.status_code,
            "soap_response_code": str(response.status_code),
            "error": f"TAC endpoint returned HTTP {response.status_code}: {response.text[:500]}",
            "endpoint_url": TAC_ENDPOINT_URL,
        }

    except httpx.TimeoutException as exc:
        logger.error(
            "TAC SOAP submission %s timed out: %s", submission_number, exc
        )
        return {
            "success": False,
            "http_status": None,
            "soap_response_code": None,
            "error": f"TAC endpoint request timed out: {exc}",
            "endpoint_url": TAC_ENDPOINT_URL,
        }
    except Exception as exc:
        logger.exception(
            "TAC SOAP submission %s raised unexpected error", submission_number
        )
        return {
            "success": False,
            "http_status": None,
            "soap_response_code": None,
            "error": f"TAC SOAP submission failed: {exc}",
            "endpoint_url": TAC_ENDPOINT_URL,
        }


@router.get(
    "/",
    response_model=list[_ScenarioSummary],
    summary="List all 2026 TAC compliance scenarios",
)
async def list_scenarios(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """Return all 2026 TAC compliance scenario summaries.

    If X-Tenant-ID is provided, the database is queried for the most recent
    run state (last_run_at, last_submission_id, status) for each scenario
    under that tenant. Without X-Tenant-ID, static metadata is returned with
    status set to 'available'.

    Args:
        x_tenant_id: Optional tenant identifier from the X-Tenant-ID header.
        session: Injected async database session.

    Returns:
        List of scenario summary dicts.
    """
    db_states: dict[str, NemsisScenario] = {}

    if x_tenant_id:
        result = await session.execute(
            select(NemsisScenario).where(
                NemsisScenario.tenant_id == x_tenant_id
            )
        )
        rows = result.scalars().all()
        for row in rows:
            db_states[row.scenario_code] = row

    summaries: list[dict[str, Any]] = []
    for scenario in _2026_SCENARIOS:
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
                "last_run_at": (
                    db_row.last_run_at.isoformat() if db_row and db_row.last_run_at else None
                ),
                "last_submission_id": (
                    db_row.last_submission_id if db_row else None
                ),
            }
        )

    return summaries


@router.get(
    "/{scenario_id}",
    summary="Get a single 2026 TAC compliance scenario by code",
)
async def get_scenario(scenario_id: str) -> dict[str, Any]:
    """Return the full scenario definition for the given scenario_code.

    Args:
        scenario_id: The TAC scenario code (e.g. '2026_DEM_1').

    Returns:
        Complete scenario dict including chart data and agency info.

    Raises:
        HTTPException 404: If the scenario_code is not found.
    """
    scenario = _find_scenario(scenario_id)
    if scenario is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scenario '{scenario_id}' not found in 2026 TAC scenario suite.",
        )
    return scenario


@router.post(
    "/{scenario_id}/generate",
    response_model=_GenerateResponse,
    summary="Generate NEMSIS XML for a TAC compliance scenario",
)
async def generate_scenario_xml(
    scenario_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """Generate NEMSIS 3.5.1 XML for the specified scenario without persisting it.

    Builds XML using NEMSISExporter from the scenario's embedded chart and
    agency data. Returns a size report and a preview of the first 2000 characters
    of the generated XML.

    Args:
        scenario_id: The TAC scenario code to generate XML for.
        x_tenant_id: Tenant identifier from the X-Tenant-ID header (required).

    Returns:
        Dict with scenario_code, xml_size_bytes, xml_preview, generated_at.

    Raises:
        HTTPException 404: Scenario not found.
        HTTPException 500: XML generation failed.
    """
    scenario = _find_scenario(scenario_id)
    if scenario is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scenario '{scenario_id}' not found in 2026 TAC scenario suite.",
        )

    try:
        exporter = NEMSISExporter()
        xml_bytes: bytes = exporter.export_chart(
            scenario["chart"], scenario["agency_info"]
        )
    except Exception as exc:
        logger.exception(
            "generate_scenario_xml: XML generation failed for scenario %s tenant %s",
            scenario_id,
            x_tenant_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"NEMSIS XML generation failed for scenario '{scenario_id}': {exc}",
        ) from exc

    xml_str = xml_bytes.decode("utf-8", errors="replace")
    return {
        "scenario_code": scenario["scenario_code"],
        "xml_size_bytes": len(xml_bytes),
        "xml_preview": xml_str[:2000],
        "generated_at": datetime.now(UTC).isoformat(),
    }


@router.post(
    "/{scenario_id}/validate",
    response_model=_ValidateResponse,
    summary="Generate and validate NEMSIS XML for a TAC compliance scenario",
)
async def validate_scenario_xml(
    scenario_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """Generate and validate NEMSIS 3.5.1 XML for the specified scenario.

    Generates XML via NEMSISExporter then validates it against XSD and
    Schematron rules using NemsisXSDValidator. Returns the full validation
    result including any errors or warnings. Validation_skipped will be True
    when lxml or asset paths are unavailable; this is reported explicitly.

    Args:
        scenario_id: The TAC scenario code to validate.
        x_tenant_id: Tenant identifier from the X-Tenant-ID header (required).

    Returns:
        Dict with scenario_code, valid, validation_skipped, xsd_errors,
        schematron_errors, schematron_warnings, cardinality_errors,
        xml_size_bytes, validated_at.

    Raises:
        HTTPException 404: Scenario not found.
        HTTPException 500: XML generation or validation raised an unexpected error.
    """
    scenario = _find_scenario(scenario_id)
    if scenario is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scenario '{scenario_id}' not found in 2026 TAC scenario suite.",
        )

    try:
        exporter = NEMSISExporter()
        xml_bytes: bytes = exporter.export_chart(
            scenario["chart"], scenario["agency_info"]
        )
    except Exception as exc:
        logger.exception(
            "validate_scenario_xml: XML generation failed for scenario %s tenant %s",
            scenario_id,
            x_tenant_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"NEMSIS XML generation failed for scenario '{scenario_id}': {exc}",
        ) from exc

    try:
        validator = NemsisXSDValidator()
        validation_result = validator.validate_xml(xml_bytes)
    except Exception as exc:
        logger.exception(
            "validate_scenario_xml: validation raised unexpected error for scenario %s",
            scenario_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"NEMSIS validation failed unexpectedly for scenario '{scenario_id}': {exc}",
        ) from exc

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


@router.post(
    "/{scenario_id}/submit",
    response_model=_SubmitResponse,
    summary="Generate, validate, and submit a TAC compliance scenario to the NEMSIS TAC endpoint",
)
async def submit_scenario(
    scenario_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_user_id: str = Header(..., alias="X-User-ID"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Generate, validate, and submit NEMSIS XML for a TAC compliance scenario.

    Generates XML, runs validation (non-blocking on failure), creates a
    NemsisSubmissionResult record, attempts SOAP delivery to the TAC endpoint,
    updates submission status based on the SOAP result, writes the initial
    history row, and upserts the NemsisScenario run state. All outcomes are
    persisted and returned honestly.

    Args:
        scenario_id: The TAC scenario code to submit.
        x_tenant_id: Tenant identifier from the X-Tenant-ID header (required).
        x_user_id: User identifier from the X-User-ID header (required).
        session: Injected async database session.

    Returns:
        Dict with scenario_code, submission_id, submission_number,
        submission_status, soap_result, validation_result,
        xml_size_bytes, submitted_at.

    Raises:
        HTTPException 404: Scenario not found.
        HTTPException 500: XML generation failed.
    """
    scenario = _find_scenario(scenario_id)
    if scenario is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scenario '{scenario_id}' not found in 2026 TAC scenario suite.",
        )

    try:
        exporter = NEMSISExporter()
        xml_bytes: bytes = exporter.export_chart(
            scenario["chart"], scenario["agency_info"]
        )
    except Exception as exc:
        logger.exception(
            "submit_scenario: XML generation failed for scenario %s tenant %s",
            scenario_id,
            x_tenant_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"NEMSIS XML generation failed for scenario '{scenario_id}': {exc}",
        ) from exc

    try:
        validator = NemsisXSDValidator()
        validation_result: dict[str, Any] = validator.validate_xml(xml_bytes)
    except Exception as exc:
        logger.exception(
            "submit_scenario: validation raised unexpected error for scenario %s",
            scenario_id,
        )
        validation_result = {
            "valid": False,
            "validation_skipped": False,
            "xsd_errors": [f"Validation raised unexpected error: {exc}"],
            "schematron_errors": [],
            "schematron_warnings": [],
            "cardinality_errors": [],
        }

    submission_id = str(uuid.uuid4())
    submission_number = (
        f"TAC-{scenario['scenario_code']}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    )
    now_utc = datetime.now(UTC)

    submission_record = NemsisSubmissionResult(
        id=submission_id,
        tenant_id=x_tenant_id,
        chart_id=scenario["chart"]["id"],
        submission_number=submission_number,
        state_endpoint_url=TAC_ENDPOINT_URL,
        submission_status="pending",
        created_at=now_utc,
        created_by_user_id=x_user_id,
    )
    session.add(submission_record)

    soap_result = await _submit_via_soap_tac(
        xml_bytes, submission_number, _TAC_USERNAME, _TAC_PASSWORD
    )

    if soap_result["success"]:
        submission_record.submission_status = "submitted"
        submission_record.submitted_at = datetime.now(UTC)
        submission_record.soap_response_code = soap_result.get("soap_response_code")
        final_status = "submitted"
        logger.info(
            "submit_scenario: scenario %s submitted successfully as %s tenant %s",
            scenario_id,
            submission_number,
            x_tenant_id,
        )
    else:
        submission_record.rejection_reason = soap_result.get("error")
        final_status = "pending"
        logger.error(
            "submit_scenario: TAC SOAP submission failed for scenario %s tenant %s: %s",
            scenario_id,
            x_tenant_id,
            soap_result.get("error"),
        )

    history_row = NemsisSubmissionStatusHistory(
        id=str(uuid.uuid4()),
        submission_id=submission_id,
        tenant_id=x_tenant_id,
        from_status=None,
        to_status=final_status,
        actor_user_id=x_user_id,
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
            }
        ),
        transitioned_at=datetime.now(UTC),
    )
    session.add(history_row)

    existing_scenario_result = await session.execute(
        select(NemsisScenario).where(
            NemsisScenario.scenario_code == scenario["scenario_code"],
            NemsisScenario.tenant_id == x_tenant_id,
        )
    )
    existing_scenario = existing_scenario_result.scalar_one_or_none()

    if existing_scenario is not None:
        existing_scenario.status = "completed" if soap_result["success"] else "failed"
        existing_scenario.last_run_at = now_utc
        existing_scenario.last_submission_id = submission_id
    else:
        new_scenario_record = NemsisScenario(
            id=str(uuid.uuid4()),
            tenant_id=x_tenant_id,
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
        session.add(new_scenario_record)

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


@router.get(
    "/{scenario_id}/evidence",
    summary="Get execution evidence for a TAC compliance scenario",
)
async def get_scenario_evidence(
    scenario_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Return execution evidence for the specified scenario under the given tenant.

    Queries the database for the NemsisScenario record matching scenario_code
    and tenant_id. If not found, reports not_executed. If found, also fetches
    the last NemsisSubmissionResult for last_submission_id when set.

    Args:
        scenario_id: The TAC scenario code to retrieve evidence for.
        x_tenant_id: Tenant identifier from the X-Tenant-ID header (required).
        session: Injected async database session.

    Returns:
        Dict with scenario_code, status, last_run_at, last_submission_id,
        and last_submission detail if available.

    Raises:
        HTTPException 404: If scenario_id is not a known 2026 TAC scenario code.
    """
    if _find_scenario(scenario_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scenario '{scenario_id}' not found in 2026 TAC scenario suite.",
        )

    scenario_result = await session.execute(
        select(NemsisScenario).where(
            NemsisScenario.scenario_code == scenario_id,
            NemsisScenario.tenant_id == x_tenant_id,
        )
    )
    db_scenario = scenario_result.scalar_one_or_none()

    if db_scenario is None:
        return {
            "scenario_code": scenario_id,
            "status": "not_executed",
            "evidence": [],
        }

    evidence: dict[str, Any] = {
        "scenario_code": scenario_id,
        "status": db_scenario.status,
        "last_run_at": (
            db_scenario.last_run_at.isoformat() if db_scenario.last_run_at else None
        ),
        "last_submission_id": db_scenario.last_submission_id,
        "last_submission": None,
    }

    if db_scenario.last_submission_id:
        submission_result = await session.execute(
            select(NemsisSubmissionResult).where(
                NemsisSubmissionResult.id == db_scenario.last_submission_id,
                NemsisSubmissionResult.tenant_id == x_tenant_id,
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
                "submitted_at": (
                    last_submission.submitted_at.isoformat()
                    if last_submission.submitted_at
                    else None
                ),
                "created_at": last_submission.created_at.isoformat(),
            }

    return evidence
