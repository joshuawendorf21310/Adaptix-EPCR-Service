"""Internal CTA Testing Workbench API (NEMSIS 3.5.1 rehearsal harness).

This module exposes the **internal** CTA testing endpoints used by the
Adaptix CTA Testing Workbench to rehearse the NEMSIS 3.5.1 CTA workflow
before the live web conference.

It is NOT:

* a public endpoint
* an auth bypass
* an official CTA pass/fail authority
* a way to mutate validator verdicts via AI

It IS:

* an authenticated, tenant-scoped harness
* backed by the same XSD + Schematron stack that production uses
* able to validate uploaded XML, generated chart XML, or baked CTA
  fixture XML
* able to run an advisory Bedrock AI review on a persisted result
* able to emit an evidence packet bundling the validator output with
  the deployed registry/asset version proof

Endpoints (all under ``/api/v1/epcr/internal/cta-testing``):

* ``GET    /test-cases``
* ``POST   /uploads``
* ``POST   /validation-runs``
* ``GET    /validation-runs/{id}``
* ``POST   /validation-runs/{id}/ai-review``
* ``POST   /evidence-packets``
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.nemsis_xsd_validator import NemsisXSDValidator

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/epcr/internal/cta-testing",
    tags=["cta-testing-internal"],
)


# --------------------------------------------------------------------------- #
# Limits and allow-lists
# --------------------------------------------------------------------------- #

_DEFAULT_MAX_BYTES = 16 * 1024 * 1024  # 16 MiB ample for asset bundles
try:
    _UPLOAD_MAX_BYTES = int(os.environ.get("CTA_UPLOAD_MAX_BYTES", _DEFAULT_MAX_BYTES))
except ValueError:
    _UPLOAD_MAX_BYTES = _DEFAULT_MAX_BYTES

_ALLOWED_UPLOAD_SUFFIXES: tuple[str, ...] = (
    ".xml",
    ".xsd",
    ".sch",
    ".xsl",
    ".xslt",
    ".zip",
    ".txt",
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
)


# --------------------------------------------------------------------------- #
# CTA test cases (single source of truth for the six 2025 cases)
# --------------------------------------------------------------------------- #

_CTA_2025_TEST_CASES: list[dict[str, str]] = [
    {
        "test_case_id": "2025-DEM1",
        "scenario_code": "2025_DEM_1",
        "dataset_type": "DEM",
        "label": "2025-DEM1 — Agency Demographics",
        "fixture_filename": "2025-DEM-1_v351.xml",
    },
    {
        "test_case_id": "2025-EMS 1-Allergy",
        "scenario_code": "2025_EMS_1",
        "dataset_type": "EMS",
        "label": "2025-EMS 1 — Allergy / Anaphylaxis",
        "fixture_filename": "2025-EMS-1-Allergy_v351.xml",
    },
    {
        "test_case_id": "2025-EMS 2-Heat Stroke",
        "scenario_code": "2025_EMS_2",
        "dataset_type": "EMS",
        "label": "2025-EMS 2 — Heat Stroke",
        "fixture_filename": "2025-EMS-2-HeatStroke_v351.xml",
    },
    {
        "test_case_id": "2025-EMS 3-Pediatric Asthma",
        "scenario_code": "2025_EMS_3",
        "dataset_type": "EMS",
        "label": "2025-EMS 3 — Pediatric Asthma",
        "fixture_filename": "2025-EMS-3-PediatricAsthma_v351.xml",
    },
    {
        "test_case_id": "2025-EMS 4-Arm Trauma",
        "scenario_code": "2025_EMS_4",
        "dataset_type": "EMS",
        "label": "2025-EMS 4 — Arm Trauma",
        "fixture_filename": "2025-EMS-4-ArmTrauma_v351.xml",
    },
    {
        "test_case_id": "2025-EMS 5-Mental Health Crisis",
        "scenario_code": "2025_EMS_5",
        "dataset_type": "EMS",
        "label": "2025-EMS 5 — Mental Health Crisis",
        "fixture_filename": "2025-EMS-5-MentalHealthCrisis_v351.xml",
    },
]
_VALID_TEST_CASE_IDS = {c["test_case_id"] for c in _CTA_2025_TEST_CASES}
_TEST_CASE_BY_ID = {c["test_case_id"]: c for c in _CTA_2025_TEST_CASES}

_FIXTURE_ROOT_DEFAULT = (
    Path(__file__).resolve().parents[1] / "nemsis" / "templates" / "cta"
)


def _fixture_root() -> Path:
    override = os.environ.get("CTA_FIXTURE_ROOT", "").strip()
    return Path(override) if override else _FIXTURE_ROOT_DEFAULT


# --------------------------------------------------------------------------- #
# Tenant-scoped in-process stores
# --------------------------------------------------------------------------- #
# Process-local. Validator output is also returned synchronously so a
# restart never loses the evidence the operator already saw. Cross-tenant
# reads are blocked by always filtering on tenant_id.

_UPLOADS: dict[str, dict[str, Any]] = {}
_VALIDATION_RUNS: dict[str, dict[str, Any]] = {}
_AI_REVIEWS: dict[str, dict[str, Any]] = {}


# --------------------------------------------------------------------------- #
# Pydantic models
# --------------------------------------------------------------------------- #


class CtaTestCase(BaseModel):
    test_case_id: str
    scenario_code: str
    dataset_type: str
    label: str
    fixture_filename: str
    fixture_available: bool


class CtaTestCasesResponse(BaseModel):
    test_cases: list[CtaTestCase]
    nemsis_version: str = "3.5.1"
    nemsis_asset_version: str = "3.5.1.251001CP2"


class CtaUploadResponse(BaseModel):
    upload_id: str
    tenant_id: str
    filename: str
    content_type: str | None
    size_bytes: int
    suffix: str
    checksum_sha256: str
    test_case_id: str | None
    purpose: Literal["xml_input", "xsd_asset", "schematron_asset", "other"]
    created_at: str
    created_by_user_id: str


class CtaValidationRunRequest(BaseModel):
    test_case_id: str | None = None
    mode: Literal["uploaded_xml", "generated_chart_xml", "fixture_xml"] = "fixture_xml"
    xml_upload_id: str | None = None
    chart_id: str | None = None
    use_deployed_assets: bool = True
    xsd_asset_upload_id: str | None = None
    schematron_asset_upload_id: str | None = None


class CtaValidationRunResponse(BaseModel):
    validation_run_id: str
    tenant_id: str
    test_case_id: str
    mode: Literal["uploaded_xml", "generated_chart_xml", "fixture_xml"]
    source_label: str
    use_deployed_assets: bool
    xml_upload_id: str | None
    chart_id: str | None
    xsd_asset_upload_id: str | None
    schematron_asset_upload_id: str | None
    xsd_valid: bool
    schematron_valid: bool
    schematron_skipped: bool = False
    validation_skipped: bool
    blocking_reason: str | None = None
    xsd_errors: list[str] = Field(default_factory=list)
    schematron_errors: list[str] = Field(default_factory=list)
    schematron_warnings: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    checksum_sha256: str
    validator_asset_version: str | None
    nemsis_version: str = "3.5.1"
    execution_ms: int
    created_at: str
    created_by_user_id: str


class CtaAiReviewResponse(BaseModel):
    status: Literal[
        "completed",
        "provider_not_configured",
        "failed",
    ]
    provider: str
    summary: str
    blocking_findings_summary: list[str] = Field(default_factory=list)
    warning_findings_summary: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    resubmission_notes: list[str] = Field(default_factory=list)
    operator_next_steps: list[str] = Field(default_factory=list)
    authority_notice: str = (
        "XSD and Schematron validation results remain authoritative."
    )
    validation_run_id: str
    tenant_id: str
    generated_at: str


class CtaEvidencePacketRequest(BaseModel):
    validation_run_id: str
    include_ai_review: bool = True


class CtaEvidencePacketResponse(BaseModel):
    evidence_packet_id: str
    tenant_id: str
    test_case_id: str
    validation_run_id: str
    mode: str
    nemsis_version: str
    asset_version: str | None
    registry_version: str | None
    source_commit: str | None
    xml_checksum: str
    xsd_valid: bool
    schematron_valid: bool
    xsd_errors_count: int
    schematron_errors_count: int
    warnings_count: int
    validation_skipped: bool
    blocking_reason: str | None
    bedrock_summary: str | None
    resubmission_ready: bool
    generated_at: str
    generated_by_user_id: str
    authority_notice: str = (
        "Internal CTA rehearsal evidence. Not an official CTA pass."
    )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _classify_purpose(suffix: str) -> str:
    if suffix == ".xml":
        return "xml_input"
    if suffix == ".xsd":
        return "xsd_asset"
    if suffix in (".sch", ".xsl", ".xslt"):
        return "schematron_asset"
    return "other"


def _require_test_case(test_case_id: str) -> dict[str, str]:
    case = _TEST_CASE_BY_ID.get(test_case_id)
    if case is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported CTA test case: {test_case_id}",
        )
    return case


def _require_upload(upload_id: str, tenant_id: str) -> dict[str, Any]:
    record = _UPLOADS.get(upload_id)
    if record is None or record["tenant_id"] != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload not found.",
        )
    return record


def _require_run(run_id: str, tenant_id: str) -> dict[str, Any]:
    record = _VALIDATION_RUNS.get(run_id)
    if record is None or record["tenant_id"] != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Validation run not found.",
        )
    return record


def _load_chart_xml(chart_id: str) -> bytes:
    """Materialize XML for ``mode='generated_chart_xml'``.

    Real chart export wiring belongs in the chart workspace service. The
    workbench surfaces an honest blocking reason when chart export is not
    available in this environment, instead of inventing a payload.
    """

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=(
            "generated_chart_xml mode requires the chart export pipeline; "
            "use uploaded_xml or fixture_xml in this environment."
        ),
    )


def _load_fixture_xml(test_case: dict[str, str]) -> bytes:
    fixture_path = _fixture_root() / test_case["fixture_filename"]
    if not fixture_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Fixture XML not bundled for {test_case['test_case_id']}.",
        )
    return fixture_path.read_bytes()


def _bedrock_configured() -> bool:
    region = os.environ.get("BEDROCK_REGION", "").strip()
    model = os.environ.get("BEDROCK_MODEL_ID", "").strip()
    return bool(region and model)


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


@router.get("/test-cases", response_model=CtaTestCasesResponse)
async def list_test_cases(
    current_user: CurrentUser = Depends(get_current_user),
) -> CtaTestCasesResponse:
    _ = current_user
    fixture_root = _fixture_root()
    cases = [
        CtaTestCase(
            test_case_id=c["test_case_id"],
            scenario_code=c["scenario_code"],
            dataset_type=c["dataset_type"],
            label=c["label"],
            fixture_filename=c["fixture_filename"],
            fixture_available=(fixture_root / c["fixture_filename"]).is_file(),
        )
        for c in _CTA_2025_TEST_CASES
    ]
    return CtaTestCasesResponse(test_cases=cases)


@router.post(
    "/uploads",
    response_model=CtaUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_upload(
    file: UploadFile = File(...),
    test_case_id: str | None = Form(default=None),
    purpose: str | None = Form(default=None),
    current_user: CurrentUser = Depends(get_current_user),
) -> CtaUploadResponse:
    """Persist an upload (xml/xsd/sch/xsl/xslt/zip/txt/pdf/png/jpg).

    Files are NEVER executed. The upload is stored in tenant-scoped
    in-process metadata so it can be referenced by a later validation
    run. The raw bytes for ``.xml`` uploads are kept so a subsequent
    ``validation-runs`` request can validate them.
    """

    if test_case_id is not None and test_case_id not in _VALID_TEST_CASE_IDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported CTA test case: {test_case_id}",
        )

    filename = (file.filename or "upload.bin").strip() or "upload.bin"
    suffix = os.path.splitext(filename)[1].lower()
    if suffix not in _ALLOWED_UPLOAD_SUFFIXES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type: {suffix or '<none>'}",
        )

    payload = await file.read()
    size = len(payload)
    if size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )
    if size > _UPLOAD_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Uploaded file exceeds {_UPLOAD_MAX_BYTES} bytes.",
        )

    classified = _classify_purpose(suffix)
    if purpose and purpose not in {"xml_input", "xsd_asset", "schematron_asset", "other"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid purpose.",
        )
    final_purpose = purpose or classified

    upload_id = str(uuid4())
    record: dict[str, Any] = {
        "upload_id": upload_id,
        "tenant_id": str(current_user.tenant_id),
        "filename": filename,
        "content_type": file.content_type,
        "size_bytes": size,
        "suffix": suffix,
        "checksum_sha256": hashlib.sha256(payload).hexdigest(),
        "test_case_id": test_case_id,
        "purpose": final_purpose,
        "created_at": _now_iso(),
        "created_by_user_id": str(current_user.user_id),
        # Bytes retained for XML and Schematron assets so they can be used in validation runs.
        "_bytes": payload if suffix in (".xml", ".sch", ".xsl", ".xslt") else None,
    }
    _UPLOADS[upload_id] = record
    return CtaUploadResponse(
        **{k: v for k, v in record.items() if not k.startswith("_")}
    )


@router.post(
    "/validation-runs",
    response_model=CtaValidationRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_validation_run(
    body: CtaValidationRunRequest,
    current_user: CurrentUser = Depends(get_current_user),
) -> CtaValidationRunResponse:
    # test_case_id is optional when mode=uploaded_xml with a custom schematron
    if body.test_case_id:
        test_case = _require_test_case(body.test_case_id)
    else:
        # Default to first EMS case for metadata purposes; XML is supplied externally
        test_case = _CTA_2025_TEST_CASES[1]
    tenant_id = str(current_user.tenant_id)

    # Resolve XML bytes from selected mode.
    source_label: str
    xml_upload_id: str | None = body.xml_upload_id
    chart_id: str | None = body.chart_id
    if body.mode == "uploaded_xml":
        if not body.xml_upload_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="xml_upload_id is required for mode=uploaded_xml.",
            )
        upload = _require_upload(body.xml_upload_id, tenant_id)
        if upload["suffix"] != ".xml" or upload["_bytes"] is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Referenced upload is not an XML input.",
            )
        xml_bytes = bytes(upload["_bytes"])
        source_label = upload["filename"]
    elif body.mode == "fixture_xml":
        xml_bytes = _load_fixture_xml(test_case)
        source_label = f"fixture:{test_case['fixture_filename']}"
    elif body.mode == "generated_chart_xml":
        if not body.chart_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="chart_id is required for mode=generated_chart_xml.",
            )
        xml_bytes = _load_chart_xml(body.chart_id)
        source_label = f"chart:{body.chart_id}"
    else:  # pragma: no cover - validated by Pydantic
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported mode: {body.mode}",
        )

    # Optional asset overrides — only for rehearsal.
    if body.xsd_asset_upload_id:
        _require_upload(body.xsd_asset_upload_id, tenant_id)

    # Resolve custom schematron path from uploaded .sch file
    custom_sch_path: str | None = None
    _sch_tempdir: tempfile.TemporaryDirectory[str] | None = None
    if body.schematron_asset_upload_id:
        sch_record = _require_upload(body.schematron_asset_upload_id, tenant_id)
        sch_bytes = sch_record.get("_bytes")
        if sch_bytes:
            _sch_tempdir = tempfile.TemporaryDirectory()
            sch_filename = sch_record.get("filename", "custom.sch")
            custom_sch_path = os.path.join(_sch_tempdir.name, sch_filename)
            with open(custom_sch_path, "wb") as f:
                f.write(bytes(sch_bytes))

    validator = NemsisXSDValidator()
    try:
        result = validator.validate_xml(xml_bytes, custom_sch_path=custom_sch_path)
    finally:
        validator.close()
        if _sch_tempdir is not None:
            _sch_tempdir.cleanup()

    run_id = str(uuid4())
    record = {
        "validation_run_id": run_id,
        "tenant_id": tenant_id,
        "test_case_id": body.test_case_id,
        "mode": body.mode,
        "source_label": source_label,
        "use_deployed_assets": body.use_deployed_assets,
        "xml_upload_id": xml_upload_id,
        "chart_id": chart_id,
        "xsd_asset_upload_id": body.xsd_asset_upload_id,
        "schematron_asset_upload_id": body.schematron_asset_upload_id,
        "xsd_valid": bool(result.get("xsd_valid")),
        "schematron_valid": bool(result.get("schematron_valid")),
        "schematron_skipped": bool(result.get("schematron_skipped", False)),
        "validation_skipped": bool(result.get("validation_skipped", False)),
        "blocking_reason": result.get("blocking_reason"),
        "xsd_errors": list(result.get("xsd_errors") or []),
        "schematron_errors": list(result.get("schematron_errors") or []),
        "schematron_warnings": list(result.get("schematron_warnings") or []),
        "warnings": list(result.get("warnings") or []),
        "checksum_sha256": result.get("checksum_sha256")
        or hashlib.sha256(xml_bytes).hexdigest(),
        "validator_asset_version": result.get("validator_asset_version"),
        "nemsis_version": "3.5.1",
        "execution_ms": int(result.get("execution_ms") or 0),
        "created_at": _now_iso(),
        "created_by_user_id": str(current_user.user_id),
    }
    _VALIDATION_RUNS[run_id] = record
    return CtaValidationRunResponse(**record)


@router.get(
    "/validation-runs/{run_id}",
    response_model=CtaValidationRunResponse,
)
async def get_validation_run(
    run_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> CtaValidationRunResponse:
    record = _require_run(run_id, str(current_user.tenant_id))
    return CtaValidationRunResponse(**record)


@router.post(
    "/validation-runs/{run_id}/ai-review",
    response_model=CtaAiReviewResponse,
)
async def create_ai_review(
    run_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> CtaAiReviewResponse:
    """Advisory Bedrock AI review of a persisted validation run.

    Bedrock NEVER mutates ``xsd_valid``/``schematron_valid``. When
    ``BEDROCK_REGION`` / ``BEDROCK_MODEL_ID`` are not configured this
    returns ``status='provider_not_configured'`` truthfully instead of
    fabricating a result.
    """

    run = _require_run(run_id, str(current_user.tenant_id))
    tenant_id = str(current_user.tenant_id)
    now = _now_iso()

    if not _bedrock_configured():
        review = {
            "status": "provider_not_configured",
            "provider": "aws_bedrock",
            "summary": (
                "Bedrock is not configured in this environment "
                "(BEDROCK_REGION / BEDROCK_MODEL_ID not set). "
                "Validator results above remain authoritative."
            ),
            "blocking_findings_summary": [],
            "warning_findings_summary": [],
            "missing_information": [],
            "resubmission_notes": [],
            "operator_next_steps": [
                "Configure BEDROCK_REGION and BEDROCK_MODEL_ID to enable advisory review.",
            ],
            "validation_run_id": run_id,
            "tenant_id": tenant_id,
            "generated_at": now,
        }
        _AI_REVIEWS[run_id] = review
        return CtaAiReviewResponse(**review)

    # Live Bedrock invocation belongs in a dedicated PHI-safe service that
    # is not yet enabled in this environment. Surface that honestly rather
    # than fabricating a Bedrock response.
    review = {
        "status": "failed",
        "provider": "aws_bedrock",
        "summary": (
            "Bedrock advisory review pipeline is not yet enabled in this "
            "environment. Validator results above remain authoritative."
        ),
        "blocking_findings_summary": [
            f"{len(run['xsd_errors'])} XSD error(s)",
            f"{len(run['schematron_errors'])} Schematron error(s)",
        ],
        "warning_findings_summary": [
            f"{len(run['schematron_warnings'])} Schematron warning(s)",
        ],
        "missing_information": [],
        "resubmission_notes": [],
        "operator_next_steps": [
            "Enable PHI-safe Bedrock pipeline before relying on advisory review.",
        ],
        "validation_run_id": run_id,
        "tenant_id": tenant_id,
        "generated_at": now,
    }
    _AI_REVIEWS[run_id] = review
    return CtaAiReviewResponse(**review)


@router.post(
    "/evidence-packets",
    response_model=CtaEvidencePacketResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_evidence_packet(
    body: CtaEvidencePacketRequest,
    current_user: CurrentUser = Depends(get_current_user),
) -> CtaEvidencePacketResponse:
    tenant_id = str(current_user.tenant_id)
    run = _require_run(body.validation_run_id, tenant_id)

    # Pull registry truth from the deployed registry service. Failures
    # are surfaced as ``None`` fields rather than fabricated values.
    registry_version: str | None = None
    source_commit: str | None = None
    try:
        from epcr_app.api_nemsis_registry import _service as _registry_service

        snap = _registry_service().get_snapshot()
        registry_version = snap.get("target_version")
        source_commit = snap.get("source_commit")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Registry snapshot unavailable for evidence packet: %s", exc)

    bedrock_summary: str | None = None
    if body.include_ai_review:
        review = _AI_REVIEWS.get(body.validation_run_id)
        if review is not None:
            bedrock_summary = review.get("summary")

    resubmission_ready = (
        run["xsd_valid"]
        and run["schematron_valid"]
        and not run["validation_skipped"]
    )
    return CtaEvidencePacketResponse(
        evidence_packet_id=str(uuid4()),
        tenant_id=tenant_id,
        test_case_id=run["test_case_id"],
        validation_run_id=run["validation_run_id"],
        mode=run["mode"],
        nemsis_version=run["nemsis_version"],
        asset_version=run["validator_asset_version"],
        registry_version=registry_version,
        source_commit=source_commit,
        xml_checksum=run["checksum_sha256"],
        xsd_valid=run["xsd_valid"],
        schematron_valid=run["schematron_valid"],
        xsd_errors_count=len(run["xsd_errors"]),
        schematron_errors_count=len(run["schematron_errors"]),
        warnings_count=len(run["schematron_warnings"]),
        validation_skipped=run["validation_skipped"],
        blocking_reason=run["blocking_reason"],
        bedrock_summary=bedrock_summary,
        resubmission_ready=resubmission_ready,
        generated_at=_now_iso(),
        generated_by_user_id=str(current_user.user_id),
    )


# --------------------------------------------------------------------------- #
# Uploads list
# --------------------------------------------------------------------------- #


@router.get("/uploads")
async def list_uploads(
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    tenant_id = str(current_user.tenant_id)
    records = [
        {k: v for k, v in rec.items() if not k.startswith("_")}
        for rec in _UPLOADS.values()
        if rec["tenant_id"] == tenant_id
    ]
    return {"uploads": records, "count": len(records)}


# --------------------------------------------------------------------------- #
# Credentials status
# --------------------------------------------------------------------------- #


@router.get("/credentials/status")
async def get_credentials_status(
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    _ = current_user
    endpoint = (
        os.environ.get("NEMSIS_CTA_ENDPOINT")
        or os.environ.get("NEMSIS_TAC_ENDPOINT")
        or "https://cta.nemsis.org:443/ComplianceTestingWs/endpoints/"
    )
    username = (
        os.environ.get("NEMSIS_CTA_USERNAME")
        or os.environ.get("NEMSIS_TAC_USERNAME")
        or ""
    )
    password = (
        os.environ.get("NEMSIS_CTA_PASSWORD")
        or os.environ.get("NEMSIS_TAC_PASSWORD")
        or ""
    )
    configured = bool(username and password)
    masked: str | None = None
    if username:
        if len(username) <= 4:
            masked = username[0] + "***"
        else:
            masked = username[:2] + "***" + username[-2:]
    return {"configured": configured, "username_masked": masked, "endpoint": endpoint}


# --------------------------------------------------------------------------- #
# CTA direct submission
# --------------------------------------------------------------------------- #


class CtaSubmitRequest(BaseModel):
    validation_run_id: str
    dataset_type: Literal["EMS", "DEM"] = "EMS"
    label: str = ""
    force: bool = False


@router.post("/cta-submit")
async def cta_submit(
    body: CtaSubmitRequest,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    tenant_id = str(current_user.tenant_id)
    run = _require_run(body.validation_run_id, tenant_id)

    # Resolve the XML bytes from the run's source
    xml_bytes: bytes | None = None
    xml_upload_id = run.get("xml_upload_id")
    if xml_upload_id:
        upload = _UPLOADS.get(xml_upload_id)
        if upload and upload.get("_bytes"):
            xml_bytes = bytes(upload["_bytes"])

    if xml_bytes is None:
        # Fall back to fixture XML
        test_case_id = run.get("test_case_id")
        test_case = _TEST_CASE_BY_ID.get(test_case_id or "") or _CTA_2025_TEST_CASES[1]
        try:
            xml_bytes = _load_fixture_xml(test_case)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot resolve XML for submission — re-upload and revalidate.",
            )

    # Resolve CTA credentials
    endpoint = (
        os.environ.get("NEMSIS_CTA_ENDPOINT")
        or os.environ.get("NEMSIS_TAC_ENDPOINT")
        or "https://cta.nemsis.org:443/ComplianceTestingWs/endpoints/"
    )
    username = os.environ.get("NEMSIS_CTA_USERNAME") or os.environ.get("NEMSIS_TAC_USERNAME") or ""
    password = os.environ.get("NEMSIS_CTA_PASSWORD") or os.environ.get("NEMSIS_TAC_PASSWORD") or ""
    organization = os.environ.get("NEMSIS_CTA_ORGANIZATION") or os.environ.get("NEMSIS_TAC_ORGANIZATION") or ""

    if not (username and password):
        raise HTTPException(
            status_code=status.HTTP_424_FAILED_DEPENDENCY,
            detail="CTA credentials not configured (NEMSIS_CTA_USERNAME / NEMSIS_CTA_PASSWORD).",
        )

    data_schema = "62" if body.dataset_type == "DEM" else "61"
    label = body.label or f"Adaptix {body.dataset_type} TAC submission"

    try:
        from epcr_app.nemsis.cta_client import CtaSubmissionClient
        client = CtaSubmissionClient(
            endpoint=endpoint,
            username=username,
            password=password,
            organization=organization,
        )
        result = client.submit(
            xml_bytes=xml_bytes,
            request_data_schema=data_schema,
            additional_info=label,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"CTA submission failed: {exc}",
        )

    return {
        "submitted": result.submitted,
        "status_code": str(result.status_code or ""),
        "request_handle": str(result.request_handle or ""),
        "message": str(result.message or ""),
        "request_body": str(result.request_body or ""),
        "response_body": str(result.response_body or ""),
        "endpoint": endpoint,
        "submitted_at": _now_iso(),
    }


# --------------------------------------------------------------------------- #
# Test seam
# --------------------------------------------------------------------------- #


def _reset_state_for_tests() -> None:
    _UPLOADS.clear()
    _VALIDATION_RUNS.clear()
    _AI_REVIEWS.clear()
