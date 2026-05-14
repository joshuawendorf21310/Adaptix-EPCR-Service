"""Dataset-aware NEMSIS export and visibility API.

This router exposes the new ``NemsisDatasetXmlBuilder`` and
``NemsisVisibilityRulesService`` over HTTP. It is the production-ready
replacement for callers that previously had to consume the legacy
single-file export in ``api_export.py``.

Endpoints:
- ``POST /api/v1/epcr/nemsis/datasets/{chart_id}/build``
    Generate per-dataset XML artifacts (EMSDataSet / DEMDataSet /
    StateDataSet) directly from ``epcr_nemsis_field_values``. Optionally
    runs official XSD validation when ``validate=true``. Optionally
    bundles the artifacts into a deterministic submission archive when
    ``package=true``.
- ``GET  /api/v1/epcr/nemsis/datasets/{chart_id}/visibility``
    Resolve registry-driven visibility/required/disabled decisions for
    every field in every dataset, given a chart context (chart_status,
    workflow flags, active state pack).
- ``POST /api/v1/epcr/nemsis/datasets/{chart_id}/validate-all``
    Run ``validate_chart_all_datasets`` for the chart's saved field
    values across every dataset.

All routes enforce tenant isolation via ``get_current_user``.
"""
from __future__ import annotations

import base64
import io
import logging
import zipfile
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.nemsis_dataset_xml_builder import (
    DatasetBuildError,
    NemsisDatasetXmlBuilder,
)
from epcr_app.nemsis_field_validator import NemsisFieldValidator
from epcr_app.nemsis_registry_service import get_default_registry_service
from epcr_app.nemsis_visibility_rules_service import (
    get_default_visibility_service,
)
from epcr_app.services_nemsis_field_values import NemsisFieldValueService

logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/epcr/nemsis/datasets",
    tags=["nemsis-datasets"],
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class BuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    datasets: list[str] | None = Field(
        default=None,
        description=(
            "Optional restriction. Defaults to all datasets that have "
            "saved values: EMSDataSet, DEMDataSet, StateDataSet."
        ),
    )


class DatasetArtifactPayload(BaseModel):
    dataset: str
    sha256: str
    row_count: int
    section_count: int
    size_bytes: int
    xml_base64: str
    warnings: list[str]
    xsd_valid: bool | None = None
    xsd_errors: list[str] = Field(default_factory=list)
    xsd_path: str | None = None


class BuildResponse(BaseModel):
    chart_id: str
    tenant_id: str
    artifacts: list[DatasetArtifactPayload]
    skipped_rows: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    package_base64: str | None = None
    package_filename: str | None = None
    package_sha256: str | None = None


class VisibilityResponse(BaseModel):
    chart_id: str
    tenant_id: str
    chart_context: dict[str, Any]
    by_dataset: dict[str, list[dict[str, Any]]]


class ValidateAllRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chart_context: dict[str, Any] | None = None
    datasets: list[str] | None = None


class ValidateAllResponse(BaseModel):
    chart_id: str
    tenant_id: str
    valid: bool
    total_issues: int
    total_warnings: int
    by_dataset: dict[str, Any]
    issues: list[dict[str, Any]]
    warnings: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _try_xsd_validate(xml_bytes: bytes) -> tuple[bool | None, list[str], str | None]:
    """Attempt XSD validation. Returns (valid, errors, xsd_path).

    Returns (None, [reason], None) when the local XSD bundle is not
    available — production-ready behavior per Adaptix governance: we
    return a structured "not_validated" verdict, never a fake "valid".

    The validator first tries the official ``OfficialXsdValidator`` (zip
    bundle). If that bundle is missing it falls back to the pre-extracted
    XSD directory at ``backend/nemsis/xsd/``.
    """
    # Strategy 1: official zip bundle.
    try:
        from epcr_app.nemsis.xsd_validator import OfficialXsdValidator

        validator = OfficialXsdValidator()
        result = validator.validate(xml_bytes)
        return result.is_valid, list(result.errors), result.xsd_path
    except FileNotFoundError:
        pass
    except Exception as exc:  # pragma: no cover - defensive
        return False, [f"xsd_validation_error: {exc}"], None

    # Strategy 2: pre-extracted XSD directory shipped under backend/nemsis/xsd.
    try:
        from pathlib import Path

        from lxml import etree
    except Exception as exc:  # pragma: no cover
        return None, [f"lxml_unavailable: {exc}"], None

    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    try:
        document = etree.fromstring(xml_bytes, parser=parser)
    except Exception as exc:
        return False, [f"xml_parse_error: {exc}"], None

    dataset_name = etree.QName(document.tag).localname
    if dataset_name not in {"EMSDataSet", "DEMDataSet", "StateDataSet"}:
        return False, [f"unsupported_dataset_root: {dataset_name}"], None

    candidate_roots = [
        Path(__file__).resolve().parents[1] / "nemsis" / "xsd",
        Path(__file__).resolve().parents[0]
        / "nemsis_resources"
        / "official"
        / "raw"
        / f"xsd_{dataset_name.lower().replace('dataset', '')}",
    ]
    target_name = f"{dataset_name}_v3.xsd"
    for root in candidate_roots:
        if not root.exists():
            continue
        for xsd_path in root.rglob(target_name):
            try:
                schema = etree.XMLSchema(etree.parse(str(xsd_path), parser))
            except Exception as exc:
                return False, [f"xsd_load_error: {exc}"], str(xsd_path)
            doc_tree = etree.ElementTree(document)
            ok = schema.validate(doc_tree)
            errors = (
                [] if ok else [entry.message for entry in schema.error_log]
            )
            return bool(ok), errors, str(xsd_path)

    return None, [f"xsd_bundle_missing: no XSD found for {dataset_name}"], None


def _build_submission_package(
    *,
    chart_id: str,
    tenant_id: str,
    artifacts: list[Any],
) -> tuple[bytes, str]:
    """Bundle every dataset XML into a deterministic ZIP submission.

    Layout:
        EMSDataSet.xml
        DEMDataSet.xml
        StateDataSet.xml
        manifest.json   -- {chart_id, tenant_id, datasets: [{name, sha256, size}]}

    Returns (zip_bytes, filename). Filename includes tenant + chart so
    operators can correlate uploads without opening the archive.
    """
    import json

    buf = io.BytesIO()
    manifest = {
        "chart_id": chart_id,
        "tenant_id": tenant_id,
        "dictionary_version": "3.5.1",
        "datasets": [],
    }
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for art in artifacts:
            name = f"{art.dataset}.xml"
            zf.writestr(name, art.xml_bytes)
            manifest["datasets"].append(
                {
                    "name": art.dataset,
                    "file": name,
                    "sha256": art.sha256,
                    "size_bytes": len(art.xml_bytes),
                    "row_count": art.row_count,
                    "section_count": art.section_count,
                }
            )
        zf.writestr(
            "manifest.json",
            json.dumps(manifest, sort_keys=True, indent=2).encode("utf-8"),
        )
    data = buf.getvalue()
    filename = f"nemsis-{tenant_id}-{chart_id}.zip"
    return data, filename


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/{chart_id}/build", response_model=BuildResponse)
async def build_dataset_artifacts(
    chart_id: str,
    payload: BuildRequest = Body(default_factory=BuildRequest),
    validate: bool = Query(
        default=False,
        description="Run official XSD validation against each artifact.",
    ),
    package: bool = Query(
        default=False,
        description="Bundle artifacts into a single submission ZIP.",
    ),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> BuildResponse:
    """Generate per-dataset NEMSIS XML directly from saved field values.

    Reads exclusively from ``epcr_nemsis_field_values`` — no
    NemsisMappingRecord template path, no fabricated content.
    """
    tenant_id = str(current_user.tenant_id)
    builder = NemsisDatasetXmlBuilder()
    try:
        result = await builder.build_for_chart(
            session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            datasets=payload.datasets,
        )
    except DatasetBuildError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    artifacts_payload: list[DatasetArtifactPayload] = []
    for art in result.artifacts:
        xsd_valid: bool | None = None
        xsd_errors: list[str] = []
        xsd_path: str | None = None
        if validate:
            xsd_valid, xsd_errors, xsd_path = _try_xsd_validate(art.xml_bytes)
        artifacts_payload.append(
            DatasetArtifactPayload(
                dataset=art.dataset,
                sha256=art.sha256,
                row_count=art.row_count,
                section_count=art.section_count,
                size_bytes=len(art.xml_bytes),
                xml_base64=base64.b64encode(art.xml_bytes).decode("ascii"),
                warnings=list(art.warnings),
                xsd_valid=xsd_valid,
                xsd_errors=xsd_errors,
                xsd_path=xsd_path,
            )
        )

    package_b64: str | None = None
    package_filename: str | None = None
    package_sha256: str | None = None
    if package and result.artifacts:
        import hashlib

        zip_bytes, package_filename = _build_submission_package(
            chart_id=chart_id, tenant_id=tenant_id, artifacts=result.artifacts
        )
        package_b64 = base64.b64encode(zip_bytes).decode("ascii")
        package_sha256 = hashlib.sha256(zip_bytes).hexdigest()

    return BuildResponse(
        chart_id=chart_id,
        tenant_id=tenant_id,
        artifacts=artifacts_payload,
        skipped_rows=list(result.skipped_rows),
        warnings=list(result.warnings),
        package_base64=package_b64,
        package_filename=package_filename,
        package_sha256=package_sha256,
    )


@router.get("/{chart_id}/visibility", response_model=VisibilityResponse)
async def get_visibility(
    chart_id: str,
    chart_status: str = Query(default="draft"),
    cardiac_arrest: bool = Query(default=False),
    trauma_injury: bool = Query(default=False),
    medication_administered: bool = Query(default=False),
    procedure_performed: bool = Query(default=False),
    labs_performed: bool = Query(default=False),
    state_pack_id: str | None = Query(default=None),
    scope: str = Query(default="encounter"),
    current_user: CurrentUser = Depends(get_current_user),
) -> VisibilityResponse:
    """Return registry-driven visibility verdicts grouped by dataset."""
    tenant_id = str(current_user.tenant_id)
    chart_context: dict[str, Any] = {
        "chart_status": chart_status,
        "cardiac_arrest": cardiac_arrest,
        "trauma_injury": trauma_injury,
        "medication_administered": medication_administered,
        "procedure_performed": procedure_performed,
        "labs_performed": labs_performed,
        "scope": scope,
    }
    if state_pack_id:
        chart_context["state_pack"] = {"id": state_pack_id}
    svc = get_default_visibility_service()
    by_dataset = svc.evaluate_chart(chart_context=chart_context)
    return VisibilityResponse(
        chart_id=chart_id,
        tenant_id=tenant_id,
        chart_context=chart_context,
        by_dataset=by_dataset,
    )


@router.post("/{chart_id}/validate-all", response_model=ValidateAllResponse)
async def validate_chart_all_datasets_route(
    chart_id: str,
    payload: ValidateAllRequest = Body(default_factory=ValidateAllRequest),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> ValidateAllResponse:
    """Validate the chart's saved values across EMS, DEM, and State."""
    tenant_id = str(current_user.tenant_id)
    rows = await NemsisFieldValueService.list_for_chart(
        session, tenant_id=tenant_id, chart_id=chart_id
    )
    chart_field_values: dict[str, Any] = {}
    for row in rows:
        # Map element_number -> raw value (last write wins for repeating
        # groups; full validation runs through the row-level service).
        # ``list_for_chart`` returns serialized dicts.
        element = row.get("element_number")
        if element:
            chart_field_values[element] = row.get("value")

    validator = NemsisFieldValidator(get_default_registry_service())
    out = validator.validate_chart_all_datasets(
        chart_field_values,
        chart_context=payload.chart_context,
        datasets=payload.datasets,
    )
    return ValidateAllResponse(
        chart_id=chart_id,
        tenant_id=tenant_id,
        valid=bool(out.get("valid")),
        total_issues=int(out.get("total_issues", 0)),
        total_warnings=int(out.get("total_warnings", 0)),
        by_dataset=out.get("by_dataset", {}),
        issues=list(out.get("issues", [])),
        warnings=list(out.get("warnings", [])),
    )
