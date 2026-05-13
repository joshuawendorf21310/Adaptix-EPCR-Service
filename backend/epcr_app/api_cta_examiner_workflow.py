"""CTA Examiner Workflow API — Schematron-gated scenario review, XML revision tracking,
AI-assisted remediation, and TAC submission.

All data is tenant-scoped and kept in in-process dicts (same pattern as
api_cta_testing.py).  No PHI leaves the service boundary.

Endpoints (all under /api/v1/epcr/nemsis/cta):
  POST   /scenarios/{scenario_id}/schematron
  GET    /scenarios/{scenario_id}/schematrons
  GET    /scenarios/{scenario_id}/revisions
  POST   /scenarios/{scenario_id}/revisions
  POST   /scenarios/{scenario_id}/validate
  GET    /scenarios/{scenario_id}/validation-results
  POST   /scenarios/{scenario_id}/ai-fix
  POST   /scenarios/{scenario_id}/revisions/{revision_id}/accept
  POST   /scenarios/{scenario_id}/tac-submit
  GET    /fields/search
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from epcr_app.dependencies import CurrentUser, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/epcr/nemsis/cta",
    tags=["cta-examiner-workflow"],
)

# --------------------------------------------------------------------------- #
# Environment-sourced TAC credentials (same env vars as api_nemsis_scenarios)
# --------------------------------------------------------------------------- #

_TAC_ENDPOINT_URL = os.environ.get(
    "NEMSIS_CTA_ENDPOINT",
    os.environ.get(
        "NEMSIS_TAC_ENDPOINT",
        "https://cta.nemsis.org:443/ComplianceTestingWs/endpoints/",
    ),
)
_TAC_USERNAME = os.environ.get(
    "NEMSIS_CTA_USERNAME",
    os.environ.get("NEMSIS_TAC_USERNAME", os.environ.get("NEMSIS_SOAP_USERNAME", "")),
)
_TAC_PASSWORD = os.environ.get(
    "NEMSIS_CTA_PASSWORD",
    os.environ.get("NEMSIS_TAC_PASSWORD", os.environ.get("NEMSIS_SOAP_PASSWORD", "")),
)
_TAC_ORGANIZATION = os.environ.get("NEMSIS_CTA_ORGANIZATION", "")
_NEMSIS_SCHEMA_VERSION = os.environ.get("NEMSIS_SCHEMA_VERSION", "3.5.1")

# --------------------------------------------------------------------------- #
# Fixture resolution — mirrors api_cta_testing._load_fixture_xml
# --------------------------------------------------------------------------- #

_2025_CTA_FILES: dict[str, str] = {
    "2025_DEM_1": "2025-DEM-1_v351.xml",
    "2025_EMS_1": "2025-EMS-1-Allergy_v351.xml",
    "2025_EMS_2": "2025-EMS-2-HeatStroke_v351.xml",
    "2025_EMS_3": "2025-EMS-3-PediatricAsthma_v351.xml",
    "2025_EMS_4": "2025-EMS-4-ArmTrauma_v351.xml",
    "2025_EMS_5": "2025-EMS-5-MentalHealthCrisis_v351.xml",
}

_PRETESTING_FILES: dict[str, str] = {
    "2026_DEM_1": "2026-DEM-1_v351.xml",
    "2026_EMS_1": "2026-EMS-1-RespiratoryTransfer_v351.xml",
    "2026_EMS_2": "2026-EMS-2-Drowning_v351.xml",
    "2026_EMS_3": "2026-EMS-3-Fire_v351.xml",
    "2026_EMS_4": "2026-EMS-4-CanceledStandby_v351.xml",
    "2026_EMS_5": "2026-EMS-5-Evacuation_v351.xml",
}

_CTA_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1] / "nemsis" / "templates" / "cta"
)
_PRETESTING_DIR = Path(__file__).parent / "nemsis_pretesting_v351" / "national"

_NORMALIZED_RESOURCE_DIR = (
    Path(__file__).parent / "nemsis_resources" / "official" / "normalized"
)


def _load_scenario_fixture_bytes(scenario_id: str) -> bytes | None:
    """Attempt to load fixture XML bytes for a known scenario_id.

    Tries 2025 CTA baked templates first, then 2026 pre-testing files.
    Returns None when no fixture is found (caller must handle).
    """
    # Try resolve_cta_template_path from the template resolver
    filename = _2025_CTA_FILES.get(scenario_id) or _PRETESTING_FILES.get(scenario_id)
    if filename:
        # Try baked CTA template root first
        candidate = _CTA_FIXTURE_ROOT / filename
        if candidate.is_file():
            return candidate.read_bytes()
        # Try pretesting dir
        candidate2 = _PRETESTING_DIR / filename
        if candidate2.is_file():
            return candidate2.read_bytes()
        # Try nemsis_template_resolver
        try:
            from epcr_app.nemsis_template_resolver import resolve_cta_template_path  # noqa: PLC0415
            p = resolve_cta_template_path(filename)
            if p.is_file():
                return p.read_bytes()
        except Exception:
            pass
    return None


# --------------------------------------------------------------------------- #
# In-process stores
# --------------------------------------------------------------------------- #

_XML_REVISIONS: dict[str, dict[str, Any]] = {}
_EXAMINER_SCHEMATRONS: dict[str, dict[str, Any]] = {}
_VALIDATION_RESULTS: dict[str, dict[str, Any]] = {}

# --------------------------------------------------------------------------- #
# Pydantic models
# --------------------------------------------------------------------------- #


class ScenarioXmlRevisionOut(BaseModel):
    id: str
    scenario_id: str
    revision_number: int
    revision_type: str
    xml_content: str
    xml_hash: str
    parent_revision_id: str | None
    created_at: str
    created_by: str
    is_active: bool
    is_immutable: bool


class ExaminerSchematronOut(BaseModel):
    id: str
    scenario_id: str
    dataset_type: str
    file_name: str
    schema_id: str
    schema_version: str
    query_binding: str
    sch_hash: str
    uploaded_at: str
    uploaded_by: str
    is_active: bool


class ValidationFindingOut(BaseModel):
    id: str
    severity: str  # "ERROR" or "WARNING"
    assert_id: str
    rule_id: str
    message: str
    xpath: str | None


class SchematronValidationResultOut(BaseModel):
    id: str
    scenario_id: str
    xml_revision_id: str
    schematron_id: str
    status: str
    error_count: int
    warning_count: int
    findings: list[ValidationFindingOut]
    created_at: str


class NemsisFieldSearchResult(BaseModel):
    field_id: str
    name: str
    dataset: str
    section: str | None
    required_level: str | None


# --------------------------------------------------------------------------- #
# Request bodies
# --------------------------------------------------------------------------- #


class _CreateRevisionBody(BaseModel):
    xml_content: str
    revision_type: str = "manual_edit"  # "examiner_import" | "manual_edit"


class _ValidateBody(BaseModel):
    xml_revision_id: str | None = None
    schematron_id: str | None = None


class _AiFixBody(BaseModel):
    xml_revision_id: str
    schematron_id: str
    validation_result_id: str


class _AcceptProposalBody(BaseModel):
    pass


class _TacSubmitBody(BaseModel):
    xml_revision_id: str
    schematron_id: str
    validation_result_id: str


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _xml_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _sch_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _next_revision_number(scenario_id: str, tenant_id: str) -> int:
    existing = [
        r for r in _XML_REVISIONS.values()
        if r["scenario_id"] == scenario_id and r["tenant_id"] == tenant_id
    ]
    if not existing:
        return 1
    return max(r["revision_number"] for r in existing) + 1


def _get_active_revision(scenario_id: str, tenant_id: str) -> dict[str, Any] | None:
    """Return the active non-immutable revision, or None."""
    for r in _XML_REVISIONS.values():
        if (
            r["scenario_id"] == scenario_id
            and r["tenant_id"] == tenant_id
            and r["is_active"]
            and not r["is_immutable"]
            and r["revision_type"] != "baseline_fixture"
        ):
            return r
    return None


def _get_baseline_revision(scenario_id: str, tenant_id: str) -> dict[str, Any] | None:
    for r in _XML_REVISIONS.values():
        if (
            r["scenario_id"] == scenario_id
            and r["tenant_id"] == tenant_id
            and r["revision_type"] == "baseline_fixture"
        ):
            return r
    return None


def _deactivate_active_non_immutable(scenario_id: str, tenant_id: str) -> None:
    """Deactivate all active non-immutable non-baseline revisions for this scenario+tenant."""
    for r in _XML_REVISIONS.values():
        if (
            r["scenario_id"] == scenario_id
            and r["tenant_id"] == tenant_id
            and r["is_active"]
            and not r["is_immutable"]
            and r["revision_type"] != "baseline_fixture"
        ):
            r["is_active"] = False


def _ensure_baseline_revision(
    scenario_id: str, tenant_id: str, user_id: str
) -> dict[str, Any] | None:
    """Auto-initialize a baseline_fixture revision if none exists. Returns it or None."""
    existing = _get_baseline_revision(scenario_id, tenant_id)
    if existing:
        return existing
    fixture_bytes = _load_scenario_fixture_bytes(scenario_id)
    if fixture_bytes is None:
        return None
    xml_content = fixture_bytes.decode("utf-8", errors="replace")
    rev_id = str(uuid4())
    rev: dict[str, Any] = {
        "id": rev_id,
        "scenario_id": scenario_id,
        "tenant_id": tenant_id,
        "revision_number": _next_revision_number(scenario_id, tenant_id),
        "revision_type": "baseline_fixture",
        "xml_content": xml_content,
        "xml_hash": _xml_hash(xml_content),
        "parent_revision_id": None,
        "created_at": _now_iso(),
        "created_by": user_id,
        "is_active": True,
        "is_immutable": True,
    }
    _XML_REVISIONS[rev_id] = rev
    return rev


def _require_revision(revision_id: str, tenant_id: str) -> dict[str, Any]:
    r = _XML_REVISIONS.get(revision_id)
    if r is None or r["tenant_id"] != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Revision '{revision_id}' not found.",
        )
    return r


def _require_schematron(schematron_id: str, tenant_id: str) -> dict[str, Any]:
    s = _EXAMINER_SCHEMATRONS.get(schematron_id)
    if s is None or s["tenant_id"] != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schematron '{schematron_id}' not found.",
        )
    return s


def _require_validation_result(result_id: str, tenant_id: str) -> dict[str, Any]:
    r = _VALIDATION_RESULTS.get(result_id)
    if r is None or r["tenant_id"] != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Validation result '{result_id}' not found.",
        )
    return r


def _parse_sch_metadata(sch_bytes: bytes) -> dict[str, str]:
    """Extract id, schemaVersion, and queryBinding from a Schematron file."""
    schema_id = ""
    schema_version = ""
    query_binding = ""
    try:
        root = ET.fromstring(sch_bytes)
        # Strip namespace for attribute access
        schema_id = root.get("id", "") or root.get("{http://purl.oclc.org/dsdl/schematron}id", "")
        schema_version = root.get("schemaVersion", "") or root.get("{http://purl.oclc.org/dsdl/schematron}schemaVersion", "")
        query_binding = root.get("queryBinding", "") or root.get("{http://purl.oclc.org/dsdl/schematron}queryBinding", "")

        # Also search for common attribute patterns
        tag = root.tag
        if tag.startswith("{"):
            ns = tag[1:tag.index("}")]
            schema_id = root.get(f"{{{ns}}}id", schema_id) or schema_id
            schema_version = root.get(f"{{{ns}}}schemaVersion", schema_version) or schema_version
            query_binding = root.get(f"{{{ns}}}queryBinding", query_binding) or query_binding
    except ET.ParseError:
        pass
    return {
        "schema_id": schema_id or "unknown",
        "schema_version": schema_version or "unknown",
        "query_binding": query_binding or "xslt2",
    }


def _parse_svrl_findings(svrl_raw: str) -> list[dict[str, Any]]:
    """Parse SVRL XML string into structured findings.

    failed-assert → ERROR
    successful-report with role containing WARNING → WARNING
    """
    findings: list[dict[str, Any]] = []
    if not svrl_raw:
        return findings
    try:
        root = ET.fromstring(svrl_raw)
    except ET.ParseError as exc:
        logger.warning("_parse_svrl_findings: could not parse SVRL: %s", exc)
        return findings

    SVRL_NS = "http://purl.oclc.org/dsdl/svrl"

    for node in root.iter():
        local = node.tag.replace(f"{{{SVRL_NS}}}", "")
        severity: str | None = None
        if local == "failed-assert":
            severity = "ERROR"
        elif local == "successful-report":
            role = (node.get("role") or "").upper()
            if "WARNING" in role:
                severity = "WARNING"
            else:
                severity = "ERROR"
        if severity is None:
            continue

        assert_id = node.get("id", "")
        xpath = node.get("location")
        rule_id = node.get("test", assert_id)

        text_el = node.find(f"{{{SVRL_NS}}}text")
        message = ""
        if text_el is not None and text_el.text:
            message = text_el.text.strip()

        findings.append(
            {
                "id": str(uuid4()),
                "severity": severity,
                "assert_id": assert_id,
                "rule_id": rule_id,
                "message": message,
                "xpath": xpath,
            }
        )
    return findings


# --------------------------------------------------------------------------- #
# Field search cache
# --------------------------------------------------------------------------- #

_fields_cache: list[dict[str, Any]] | None = None


def _load_fields() -> list[dict[str, Any]]:
    global _fields_cache
    if _fields_cache is not None:
        return _fields_cache
    fields_path = _NORMALIZED_RESOURCE_DIR / "fields.json"
    if not fields_path.is_file():
        _fields_cache = []
        return _fields_cache
    try:
        data = json.loads(fields_path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            _fields_cache = data
        else:
            _fields_cache = []
    except Exception as exc:
        logger.warning("_load_fields: could not load fields.json: %s", exc)
        _fields_cache = []
    return _fields_cache


# --------------------------------------------------------------------------- #
# SOAP TAC submission (duplicates the logic from api_nemsis_scenarios to avoid
# coupling; same env vars)
# --------------------------------------------------------------------------- #


async def _submit_via_soap(
    xml_bytes: bytes,
    submission_number: str,
    username: str,
    password: str,
    organization: str = "Adaptix Platform",
    data_schema: str = "61",
) -> dict[str, Any]:
    if not username or not password:
        return {
            "success": False,
            "http_status": None,
            "soap_response_code": None,
            "soap_status_code": None,
            "request_handle": None,
            "error": "TAC SOAP credentials not configured.",
            "endpoint_url": _TAC_ENDPOINT_URL,
        }

    xml_str = xml_bytes.decode("utf-8", errors="strict")
    payload_xml = re.sub(r"<\?xml[^?]*\?>\s*", "", xml_str, count=1)

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
        f"<ws:schemaVersion>{_NEMSIS_SCHEMA_VERSION}</ws:schemaVersion>"
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
            response = await client.post(
                _TAC_ENDPOINT_URL,
                content=soap_envelope.encode("utf-8"),
                headers=headers,
            )

        if response.status_code != 200:
            return {
                "success": False,
                "http_status": response.status_code,
                "soap_response_code": str(response.status_code),
                "soap_status_code": None,
                "request_handle": None,
                "error": f"TAC endpoint returned HTTP {response.status_code}: {response.text[:500]}",
                "endpoint_url": _TAC_ENDPOINT_URL,
            }

        resp_text = response.text
        status_code_val: int | None = None
        request_handle: str | None = None
        server_error: str | None = None

        if "<ns2:statusCode>" in resp_text:
            raw = resp_text.split("<ns2:statusCode>")[1].split("</ns2:statusCode>")[0]
            try:
                status_code_val = int(raw)
            except ValueError:
                status_code_val = None

        if "<ns2:requestHandle>" in resp_text and "</ns2:requestHandle>" in resp_text:
            rh = resp_text.split("<ns2:requestHandle>")[1].split("</ns2:requestHandle>")[0]
            if rh.strip():
                request_handle = rh.strip()

        if "<ns2:serverErrorMessage>" in resp_text and "</ns2:serverErrorMessage>" in resp_text:
            server_error = resp_text.split("<ns2:serverErrorMessage>")[1].split("</ns2:serverErrorMessage>")[0]

        if status_code_val is not None and status_code_val > 0:
            return {
                "success": True,
                "http_status": 200,
                "soap_response_code": str(status_code_val),
                "soap_status_code": status_code_val,
                "request_handle": request_handle,
                "error": None,
                "endpoint_url": _TAC_ENDPOINT_URL,
            }

        error_msg = server_error or request_handle or f"TAC returned statusCode={status_code_val}"
        return {
            "success": False,
            "http_status": 200,
            "soap_response_code": str(status_code_val) if status_code_val is not None else None,
            "soap_status_code": status_code_val,
            "request_handle": request_handle,
            "error": error_msg,
            "endpoint_url": _TAC_ENDPOINT_URL,
        }
    except httpx.TimeoutException as exc:
        return {
            "success": False,
            "http_status": None,
            "soap_response_code": None,
            "soap_status_code": None,
            "request_handle": None,
            "error": f"TAC endpoint request timed out: {exc}",
            "endpoint_url": _TAC_ENDPOINT_URL,
        }
    except Exception as exc:
        logger.exception("_submit_via_soap: unexpected error for %s", submission_number)
        return {
            "success": False,
            "http_status": None,
            "soap_response_code": None,
            "soap_status_code": None,
            "request_handle": None,
            "error": f"TAC SOAP submission failed: {exc}",
            "endpoint_url": _TAC_ENDPOINT_URL,
        }


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


@router.post(
    "/scenarios/{scenario_id}/schematron",
    response_model=ExaminerSchematronOut,
    status_code=status.HTTP_201_CREATED,
    summary="Upload an examiner-provided Schematron file for a scenario",
)
async def upload_examiner_schematron(
    scenario_id: str,
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
) -> ExaminerSchematronOut:
    tenant_id = str(current_user.tenant_id)
    user_id = str(current_user.user_id)

    sch_bytes = await file.read()
    if not sch_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded schematron file is empty.",
        )

    meta = _parse_sch_metadata(sch_bytes)
    schema_id = meta["schema_id"]
    dataset_type = "DEMDataSet" if "DEM" in schema_id.upper() else "EMSDataSet"

    # Deactivate previous active schematron for this scenario+tenant
    for s in _EXAMINER_SCHEMATRONS.values():
        if s["scenario_id"] == scenario_id and s["tenant_id"] == tenant_id and s["is_active"]:
            s["is_active"] = False

    upload_id = str(uuid4())
    record: dict[str, Any] = {
        "id": upload_id,
        "scenario_id": scenario_id,
        "tenant_id": tenant_id,
        "dataset_type": dataset_type,
        "file_name": file.filename or "examiner.sch",
        "schema_id": schema_id,
        "schema_version": meta["schema_version"],
        "query_binding": meta["query_binding"],
        "sch_hash": _sch_hash(sch_bytes),
        "uploaded_at": _now_iso(),
        "uploaded_by": user_id,
        "is_active": True,
        "_bytes": sch_bytes,
    }
    _EXAMINER_SCHEMATRONS[upload_id] = record

    # Auto-initialize baseline fixture revision if none exists
    _ensure_baseline_revision(scenario_id, tenant_id, user_id)

    return ExaminerSchematronOut(
        **{k: v for k, v in record.items() if not k.startswith("_")}
    )


@router.get(
    "/scenarios/{scenario_id}/schematrons",
    response_model=list[ExaminerSchematronOut],
    summary="List examiner schematrons for a scenario",
)
async def list_examiner_schematrons(
    scenario_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> list[ExaminerSchematronOut]:
    tenant_id = str(current_user.tenant_id)
    result = [
        ExaminerSchematronOut(
            **{k: v for k, v in s.items() if not k.startswith("_")}
        )
        for s in _EXAMINER_SCHEMATRONS.values()
        if s["scenario_id"] == scenario_id and s["tenant_id"] == tenant_id
    ]
    return result


@router.get(
    "/scenarios/{scenario_id}/revisions",
    response_model=list[ScenarioXmlRevisionOut],
    summary="List XML revisions for a scenario",
)
async def list_revisions(
    scenario_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> list[ScenarioXmlRevisionOut]:
    tenant_id = str(current_user.tenant_id)
    revs = sorted(
        [
            r for r in _XML_REVISIONS.values()
            if r["scenario_id"] == scenario_id and r["tenant_id"] == tenant_id
        ],
        key=lambda r: r["revision_number"],
    )
    return [ScenarioXmlRevisionOut(**r) for r in revs]


@router.post(
    "/scenarios/{scenario_id}/revisions",
    response_model=ScenarioXmlRevisionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new XML revision for a scenario",
)
async def create_revision(
    scenario_id: str,
    body: _CreateRevisionBody,
    current_user: CurrentUser = Depends(get_current_user),
) -> ScenarioXmlRevisionOut:
    tenant_id = str(current_user.tenant_id)
    user_id = str(current_user.user_id)

    # Validate well-formedness
    try:
        ET.fromstring(body.xml_content)
    except ET.ParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"XML is not well-formed: {exc}",
        ) from exc

    allowed_types = {"examiner_import", "manual_edit"}
    if body.revision_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"revision_type must be one of: {sorted(allowed_types)}",
        )

    # Deactivate previous active non-immutable revision (baseline never deactivated)
    _deactivate_active_non_immutable(scenario_id, tenant_id)

    # Determine parent
    parent_rev = _get_active_revision(scenario_id, tenant_id)

    rev_id = str(uuid4())
    rev: dict[str, Any] = {
        "id": rev_id,
        "scenario_id": scenario_id,
        "tenant_id": tenant_id,
        "revision_number": _next_revision_number(scenario_id, tenant_id),
        "revision_type": body.revision_type,
        "xml_content": body.xml_content,
        "xml_hash": _xml_hash(body.xml_content),
        "parent_revision_id": parent_rev["id"] if parent_rev else None,
        "created_at": _now_iso(),
        "created_by": user_id,
        "is_active": True,
        "is_immutable": False,
    }
    _XML_REVISIONS[rev_id] = rev
    return ScenarioXmlRevisionOut(**rev)


@router.post(
    "/scenarios/{scenario_id}/validate",
    response_model=SchematronValidationResultOut,
    status_code=status.HTTP_201_CREATED,
    summary="Run Schematron validation against a scenario XML revision",
)
async def validate_revision(
    scenario_id: str,
    body: _ValidateBody,
    current_user: CurrentUser = Depends(get_current_user),
) -> SchematronValidationResultOut:
    tenant_id = str(current_user.tenant_id)
    user_id = str(current_user.user_id)

    # Resolve XML revision
    xml_rev: dict[str, Any] | None = None
    if body.xml_revision_id:
        xml_rev = _require_revision(body.xml_revision_id, tenant_id)
        if xml_rev["scenario_id"] != scenario_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Revision does not belong to this scenario.",
            )
    else:
        xml_rev = _get_active_revision(scenario_id, tenant_id)
        if xml_rev is None:
            xml_rev = _get_baseline_revision(scenario_id, tenant_id)
        if xml_rev is None:
            xml_rev = _ensure_baseline_revision(scenario_id, tenant_id, user_id)
        if xml_rev is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"No XML revision found for scenario '{scenario_id}'. "
                    "Upload a schematron or create a revision first."
                ),
            )

    # Resolve schematron
    sch_record: dict[str, Any] | None = None
    if body.schematron_id:
        sch_record = _require_schematron(body.schematron_id, tenant_id)
        if sch_record["scenario_id"] != scenario_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Schematron does not belong to this scenario.",
            )
    else:
        # Find active examiner schematron for this scenario
        for s in _EXAMINER_SCHEMATRONS.values():
            if s["scenario_id"] == scenario_id and s["tenant_id"] == tenant_id and s["is_active"]:
                sch_record = s
                break

    if sch_record is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"No active examiner schematron found for scenario '{scenario_id}'. "
                "Upload one via POST /scenarios/{scenario_id}/schematron."
            ),
        )

    xml_bytes = xml_rev["xml_content"].encode("utf-8")
    sch_bytes: bytes = sch_record["_bytes"]

    # Write schematron to tempfile and run validator
    sch_tempdir = tempfile.TemporaryDirectory()
    sch_path = os.path.join(sch_tempdir.name, sch_record.get("file_name", "examiner.sch"))
    try:
        with open(sch_path, "wb") as fh:
            fh.write(sch_bytes)

        from epcr_app.nemsis.schematron_validator import OfficialSchematronValidator  # noqa: PLC0415

        try:
            validator = OfficialSchematronValidator()
            result = validator.validate(xml_bytes)
            # Build SVRL-derived findings from the structured result
            findings: list[dict[str, Any]] = []
            for issue in result.errors:
                findings.append(
                    {
                        "id": str(uuid4()),
                        "severity": "ERROR",
                        "assert_id": issue.test or "",
                        "rule_id": issue.test or "",
                        "message": issue.text,
                        "xpath": issue.location or None,
                    }
                )
            for issue in result.warnings:
                findings.append(
                    {
                        "id": str(uuid4()),
                        "severity": "WARNING",
                        "assert_id": issue.test or "",
                        "rule_id": issue.test or "",
                        "message": issue.text,
                        "xpath": issue.location or None,
                    }
                )
            # Try to also parse svrl_path for richer assert_id if available
            svrl_path = getattr(result, "svrl_path", None)
            if svrl_path and Path(str(svrl_path)).is_file():
                try:
                    svrl_raw = Path(str(svrl_path)).read_text(encoding="utf-8")
                    parsed_findings = _parse_svrl_findings(svrl_raw)
                    if parsed_findings:
                        findings = parsed_findings
                except Exception:
                    pass  # Keep structured findings

        except RuntimeError as exc:
            if "saxonche" in str(exc).lower():
                logger.warning("validate_revision: saxonche not available, returning empty result")
                findings = []
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Schematron validation failed: {exc}",
                ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Schematron validation failed: {exc}",
            ) from exc
    finally:
        sch_tempdir.cleanup()

    error_count = sum(1 for f in findings if f["severity"] == "ERROR")
    warning_count = sum(1 for f in findings if f["severity"] == "WARNING")

    if error_count > 0:
        val_status = "failed"
    elif warning_count > 0:
        val_status = "passed_with_warnings"
    else:
        val_status = "passed"

    result_id = str(uuid4())
    result_record: dict[str, Any] = {
        "id": result_id,
        "scenario_id": scenario_id,
        "tenant_id": tenant_id,
        "xml_revision_id": xml_rev["id"],
        "schematron_id": sch_record["id"],
        "status": val_status,
        "error_count": error_count,
        "warning_count": warning_count,
        "findings": findings,
        "created_at": _now_iso(),
    }
    _VALIDATION_RESULTS[result_id] = result_record

    return SchematronValidationResultOut(
        id=result_id,
        scenario_id=scenario_id,
        xml_revision_id=xml_rev["id"],
        schematron_id=sch_record["id"],
        status=val_status,
        error_count=error_count,
        warning_count=warning_count,
        findings=[ValidationFindingOut(**f) for f in findings],
        created_at=result_record["created_at"],
    )


@router.get(
    "/scenarios/{scenario_id}/validation-results",
    response_model=list[SchematronValidationResultOut],
    summary="List validation results for a scenario",
)
async def list_validation_results(
    scenario_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> list[SchematronValidationResultOut]:
    tenant_id = str(current_user.tenant_id)
    results = [
        r for r in _VALIDATION_RESULTS.values()
        if r["scenario_id"] == scenario_id and r["tenant_id"] == tenant_id
    ]
    return [
        SchematronValidationResultOut(
            id=r["id"],
            scenario_id=r["scenario_id"],
            xml_revision_id=r["xml_revision_id"],
            schematron_id=r["schematron_id"],
            status=r["status"],
            error_count=r["error_count"],
            warning_count=r["warning_count"],
            findings=[ValidationFindingOut(**f) for f in r["findings"]],
            created_at=r["created_at"],
        )
        for r in results
    ]


_AI_FIX_PREAMBLE = (
    "You are an advisory NEMSIS 3.5.1 XML compliance assistant. You will be given "
    "the current NEMSIS XML and a list of Schematron compliance findings (errors and "
    "warnings). Your job is to propose minimal, well-formed XML edits that resolve "
    "the listed findings while preserving every other element, attribute, and value "
    "unchanged. NEVER fabricate UUIDs already present. NEVER remove unrelated "
    "elements. NEVER change the schema namespace. Your output is advisory — a human "
    "operator must review the diff before accepting. Respond with ONLY a JSON object "
    "containing exactly two keys:\n"
    '  "proposed_xml": the full edited XML string\n'
    '  "change_summary": a one-paragraph plain-English summary of edits applied.'
)


@router.post(
    "/scenarios/{scenario_id}/ai-fix",
    response_model=ScenarioXmlRevisionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Request an AI-proposed XML fix for Schematron findings",
)
async def ai_fix_revision(
    scenario_id: str,
    body: _AiFixBody,
    current_user: CurrentUser = Depends(get_current_user),
) -> ScenarioXmlRevisionOut:
    tenant_id = str(current_user.tenant_id)
    user_id = str(current_user.user_id)

    rev = _require_revision(body.xml_revision_id, tenant_id)
    if rev["scenario_id"] != scenario_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Revision does not belong to this scenario.")

    val_result = _require_validation_result(body.validation_result_id, tenant_id)
    if val_result["scenario_id"] != scenario_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Validation result does not belong to this scenario.")

    findings = val_result.get("findings", [])
    instruction_lines = ["Fix these compliance-active Schematron issues:"]
    for f in findings:
        instruction_lines.append(
            f"{f['severity']}: {f['message']}"
            + (f" [xpath: {f['xpath']}]" if f.get("xpath") else "")
        )
    instruction = "\n".join(instruction_lines)

    from epcr_app._ai_bedrock import invoke_ai as _invoke_ai, select_ai_provider as _select_ai_provider  # noqa: PLC0415, E501

    provider_name = _select_ai_provider()
    disclaimer = (
        "Advisory only. Schematron validator and TAC SOAP response remain "
        "authoritative. Operator must visually review the diff before accepting."
    )
    now_iso = _now_iso()

    if provider_name is None:
        # No AI configured — return placeholder proposal with same XML
        proposal_xml = rev["xml_content"]
        change_summary = (
            "AI advisory provider not configured. No changes proposed. "
            "Set BEDROCK_REGION + BEDROCK_MODEL_ID or ANTHROPIC_API_KEY."
        )
    else:
        try:
            current_xml_text = rev["xml_content"]
            user_content = (
                f"{instruction}\n\n"
                f"Current NEMSIS XML (scenario {scenario_id}):\n"
                f"```xml\n{current_xml_text}\n```\n\n"
                "Apply the fixes and return the JSON described above."
            )
            _provider, _model, response_text = _invoke_ai(
                system=_AI_FIX_PREAMBLE,
                user=user_content,
                max_tokens=8192,
                tier="escalate",
            )
            if not response_text:
                raise RuntimeError("AI returned empty response.")

            cleaned = response_text
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
                cleaned = re.sub(r"\s*```$", "", cleaned)
            parsed = json.loads(cleaned)
            proposal_xml = parsed.get("proposed_xml")
            change_summary = parsed.get("change_summary") or "AI did not provide a change summary."
            if not isinstance(proposal_xml, str) or not proposal_xml.strip():
                raise RuntimeError("AI response missing 'proposed_xml'.")
        except Exception as exc:
            logger.exception("ai_fix_revision: advisory AI call failed for scenario %s", scenario_id)
            proposal_xml = rev["xml_content"]
            change_summary = f"AI advisory call failed: {exc}. Original XML returned unchanged."

    # Create ai_proposal revision (is_active=False, is_immutable=False)
    proposal_id = str(uuid4())
    proposal_rev: dict[str, Any] = {
        "id": proposal_id,
        "scenario_id": scenario_id,
        "tenant_id": tenant_id,
        "revision_number": _next_revision_number(scenario_id, tenant_id),
        "revision_type": "ai_proposal",
        "xml_content": proposal_xml,
        "xml_hash": _xml_hash(proposal_xml),
        "parent_revision_id": rev["id"],
        "created_at": now_iso,
        "created_by": f"ai:{user_id}",
        "is_active": False,
        "is_immutable": False,
        "_change_summary": change_summary,
        "_disclaimer": disclaimer,
    }
    _XML_REVISIONS[proposal_id] = proposal_rev

    return ScenarioXmlRevisionOut(
        **{k: v for k, v in proposal_rev.items() if not k.startswith("_")}
    )


@router.post(
    "/scenarios/{scenario_id}/revisions/{revision_id}/accept",
    response_model=ScenarioXmlRevisionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Accept an AI-proposed revision, promoting it to the active revision",
)
async def accept_proposal(
    scenario_id: str,
    revision_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> ScenarioXmlRevisionOut:
    tenant_id = str(current_user.tenant_id)
    user_id = str(current_user.user_id)

    proposal_rev = _require_revision(revision_id, tenant_id)
    if proposal_rev["scenario_id"] != scenario_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Revision does not belong to this scenario.")
    if proposal_rev["revision_type"] != "ai_proposal":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Revision '{revision_id}' is not an ai_proposal (type={proposal_rev['revision_type']}).",
        )

    # Deactivate previous active non-immutable revision
    _deactivate_active_non_immutable(scenario_id, tenant_id)

    accepted_id = str(uuid4())
    accepted_rev: dict[str, Any] = {
        "id": accepted_id,
        "scenario_id": scenario_id,
        "tenant_id": tenant_id,
        "revision_number": _next_revision_number(scenario_id, tenant_id),
        "revision_type": "ai_accepted",
        "xml_content": proposal_rev["xml_content"],
        "xml_hash": proposal_rev["xml_hash"],
        "parent_revision_id": proposal_rev["id"],
        "created_at": _now_iso(),
        "created_by": user_id,
        "is_active": True,
        "is_immutable": False,
    }
    _XML_REVISIONS[accepted_id] = accepted_rev
    return ScenarioXmlRevisionOut(**accepted_rev)


@router.post(
    "/scenarios/{scenario_id}/tac-submit",
    summary="Submit a validated XML revision to the TAC NEMSIS SOAP endpoint",
)
async def tac_submit(
    scenario_id: str,
    body: _TacSubmitBody,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    tenant_id = str(current_user.tenant_id)
    user_id = str(current_user.user_id)

    val_result = _require_validation_result(body.validation_result_id, tenant_id)
    if val_result["scenario_id"] != scenario_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Validation result does not belong to this scenario.")

    error_count = val_result.get("error_count", 0)
    if error_count > 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Cannot submit: validation has {error_count} error(s). Resolve all errors before submitting.",
        )

    xml_rev = _require_revision(body.xml_revision_id, tenant_id)
    if xml_rev["scenario_id"] != scenario_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Revision does not belong to this scenario.")

    xml_bytes = xml_rev["xml_content"].encode("utf-8")

    if not (_TAC_USERNAME and _TAC_PASSWORD):
        raise HTTPException(
            status_code=status.HTTP_424_FAILED_DEPENDENCY,
            detail="CTA credentials not configured (NEMSIS_CTA_USERNAME / NEMSIS_CTA_PASSWORD).",
        )

    # Determine data_schema from schematron dataset_type
    sch_record = _EXAMINER_SCHEMATRONS.get(body.schematron_id)
    dataset_type = "EMSDataSet"
    if sch_record and sch_record.get("tenant_id") == tenant_id:
        dataset_type = sch_record.get("dataset_type", "EMSDataSet")
    data_schema = "62" if "DEM" in dataset_type.upper() else "61"

    submission_number = f"EXAMINER-{scenario_id}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    organization = _TAC_ORGANIZATION or "Adaptix Platform"

    soap_result = await _submit_via_soap(
        xml_bytes,
        submission_number,
        _TAC_USERNAME,
        _TAC_PASSWORD,
        organization=organization,
        data_schema=data_schema,
    )

    # Create immutable submitted snapshot
    submitted_id = str(uuid4())
    submitted_rev: dict[str, Any] = {
        "id": submitted_id,
        "scenario_id": scenario_id,
        "tenant_id": tenant_id,
        "revision_number": _next_revision_number(scenario_id, tenant_id),
        "revision_type": "submitted",
        "xml_content": xml_rev["xml_content"],
        "xml_hash": xml_rev["xml_hash"],
        "parent_revision_id": xml_rev["id"],
        "created_at": _now_iso(),
        "created_by": user_id,
        "is_active": False,
        "is_immutable": True,
    }
    _XML_REVISIONS[submitted_id] = submitted_rev

    return {
        "submitted": soap_result.get("success", False),
        "status_code": str(soap_result.get("soap_status_code") or ""),
        "request_handle": str(soap_result.get("request_handle") or ""),
        "message": str(soap_result.get("error") or ""),
        "endpoint": str(soap_result.get("endpoint_url") or _TAC_ENDPOINT_URL),
        "submitted_at": _now_iso(),
        "submitted_revision_id": submitted_id,
        "soap_result": soap_result,
    }


@router.get(
    "/fields/search",
    response_model=list[NemsisFieldSearchResult],
    summary="Search NEMSIS field metadata by field_id or name",
)
async def search_fields(
    q: str = "",
    limit: int = 20,
    current_user: CurrentUser = Depends(get_current_user),
) -> list[NemsisFieldSearchResult]:
    _ = current_user
    if not q.strip():
        return []

    q_lower = q.strip().lower()
    fields = _load_fields()
    results: list[NemsisFieldSearchResult] = []

    for field in fields:
        field_id = str(field.get("field_id") or field.get("element_id") or "")
        name = str(
            field.get("label")
            or field.get("official_name")
            or field.get("name")
            or field_id
        )
        definition = str(field.get("definition") or "")
        searchable = " ".join([field_id, name, definition]).lower()

        if q_lower in searchable:
            results.append(
                NemsisFieldSearchResult(
                    field_id=field_id,
                    name=name,
                    dataset=str(field.get("dataset") or ""),
                    section=field.get("section"),
                    required_level=field.get("required_level") or field.get("usage"),
                )
            )
        if len(results) >= limit:
            break

    return results


# --------------------------------------------------------------------------- #
# Test seam
# --------------------------------------------------------------------------- #


def _reset_state_for_tests() -> None:
    _XML_REVISIONS.clear()
    _EXAMINER_SCHEMATRONS.clear()
    _VALIDATION_RESULTS.clear()
    global _fields_cache
    _fields_cache = None
