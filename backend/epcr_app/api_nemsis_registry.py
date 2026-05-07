"""Read-only HTTP routes over the NEMSIS official-source registry.

Endpoints expose the normalized artifacts produced by
``nemsis_registry_importer`` and stored under
``nemsis_resources/official/normalized/``.

No route in this module performs CTA submission, XML emission, network I/O,
or PHI persistence. The ``evaluate`` route is read-only and returns coverage
analysis without mutating its input or storing the chart-state.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.nemsis_registry_service import (
    NemsisRegistryService,
    get_default_registry_service,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/epcr/nemsis-registry",
    tags=["nemsis-registry"],
)


# --------------------------------------------------------------------------- #
# Response models
# --------------------------------------------------------------------------- #


class RegistrySnapshotResponse(BaseModel):
    source_mode: str
    source_repo: str
    source_commit: str
    source_branch: str | None = None
    target_version: str
    dictionary_version: str | None = None
    retrieved_at: str | None = None
    field_count: int
    baseline_total_expected: int | None = None
    baseline_total_actual: int | None = None
    baseline_counts_expected: dict[str, int] = Field(default_factory=dict)
    baseline_counts_actual: dict[str, int] = Field(default_factory=dict)
    baseline_counts_match: bool | None = None
    element_enumeration_count: int
    attribute_enumeration_count: int
    defined_list_count: int
    defined_list_field_count: int = 0
    official_artifact_count: int
    local_seed_fallback_count: int
    coverage_warnings: list[str] = Field(default_factory=list)


class RegistryArtifactPayload(BaseModel):
    name: str
    artifact_type: str
    dataset: str
    source_repo_path: str
    local_path: str
    sha256: str
    source_commit: str


class RegistryManifestResponse(BaseModel):
    source_family: str
    source_repo: str
    source_commit: str
    source_branch: str | None = None
    target_version: str
    retrieved_at: str | None = None
    artifacts: list[RegistryArtifactPayload]
    coverage_warnings: list[str] = Field(default_factory=list)


class RegistryFieldPayload(BaseModel):
    field_id: str
    element_id: str | None = None
    dataset: str
    section: str
    name: str
    label: str
    official_name: str | None = None
    definition: str | None = None
    data_type: str | None = None
    usage: str | None = None
    required_level: str | None = None
    national_element: str | None = None
    state_element: str | None = None
    recurrence: str | None = None
    min_occurs: str | None = None
    max_occurs: str | None = None
    nillable: str | None = None
    not_value_allowed: str | None = None
    pertinent_negative_allowed: str | None = None
    required_if: str | None = None
    defined_list_ref: str | None = None
    enumeration_ref: str | None = None
    version_2_element: str | None = None
    min_length: str | None = None
    max_length: str | None = None
    pattern: str | None = None
    constraints: dict[str, Any] = Field(default_factory=dict)
    code_system: str | None = None
    code_type_attribute: str | None = None
    allowed_values: list[Any] = Field(default_factory=list)
    element_comments: str | None = None
    deprecated: bool = False
    dictionary_version: str | None = None
    dictionary_source: str | None = None
    source_datasets: list[str] = Field(default_factory=list)
    attributes: list[Any] = Field(default_factory=list)
    source_artifact: str | None = None
    source_repo_path: str | None = None
    source_commit: str | None = None
    source_version: str | None = None


class RegistryCodeSetPayload(BaseModel):
    field_element_id: str
    code: str
    label: str
    description: str | None = None
    code_system: str | None = None
    code_type: str | None = None
    source: str | None = None
    source_version: str | None = None
    effective_date: str | None = None
    deprecated: bool = False


class RegistryVersionResponse(BaseModel):
    source_repo: str
    source_commit: str
    source_branch: str | None = None
    target_version: str | None = None
    dictionary_version: str | None = None
    retrieved_at: str | None = None
    baseline_total_expected: int | None = None
    baseline_total_actual: int | None = None
    baseline_counts_expected: dict[str, int] = Field(default_factory=dict)
    baseline_counts_actual: dict[str, int] = Field(default_factory=dict)
    baseline_counts_match: bool = False
    coverage_warnings: list[str] = Field(default_factory=list)


class RegistryEnumerationPayload(BaseModel):
    field_id: str | None = None
    attribute_name: str | None = None
    code: str
    display: str
    description: str | None = None
    active: bool | None = None
    dataset: str | None = None
    source_artifact: str | None = None
    source_repo_path: str | None = None
    source_commit: str | None = None
    source_version: str | None = None


class RegistryDefinedListPayload(BaseModel):
    list_id: str
    list_name: str | None = None
    field_id: str
    values: list[Any]
    value_count: int
    source_artifact: str
    source_repo_path: str
    source_url: str | None = None
    upstream_date: str | None = None
    retrieved_at: str | None = None
    source_commit: str | None = None
    source_version: str | None = None


class RegistryEvaluateRequest(BaseModel):
    chart_state: dict[str, Any]
    dataset: str | None = None


class RegistryEvaluateResponse(BaseModel):
    dataset: str | None = None
    field_count: int
    provided_field_count: int
    covered_field_ids: list[str]
    completeness: str
    source_mode: str | None = None
    source_repo: str


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


def _service() -> NemsisRegistryService:
    return get_default_registry_service()


@router.get("", response_model=RegistrySnapshotResponse)
async def get_registry_snapshot(
    current_user: CurrentUser = Depends(get_current_user),
) -> RegistrySnapshotResponse:
    _ = current_user
    snap = _service().get_snapshot()
    return RegistrySnapshotResponse(**snap)


@router.get("/version", response_model=RegistryVersionResponse)
async def get_registry_version(
    current_user: CurrentUser = Depends(get_current_user),
) -> RegistryVersionResponse:
    _ = current_user
    return RegistryVersionResponse(**_service().get_version())


@router.get("/manifest", response_model=RegistryManifestResponse)
async def get_registry_manifest(
    current_user: CurrentUser = Depends(get_current_user),
) -> RegistryManifestResponse:
    _ = current_user
    return RegistryManifestResponse(**_service().get_manifest())


@router.get("/datasets", response_model=list[str])
async def list_datasets(
    current_user: CurrentUser = Depends(get_current_user),
) -> list[str]:
    _ = current_user
    return _service().list_datasets()


@router.get("/sections", response_model=list[str])
async def list_sections(
    dataset: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
) -> list[str]:
    _ = current_user
    return _service().list_sections(dataset=dataset)


@router.get("/fields", response_model=list[RegistryFieldPayload])
async def list_fields(
    dataset: str | None = Query(default=None),
    section: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
) -> list[RegistryFieldPayload]:
    _ = current_user
    return [
        RegistryFieldPayload(**f)
        for f in _service().list_fields(dataset=dataset, section=section)
    ]


@router.get("/fields/{field_id}", response_model=RegistryFieldPayload)
async def get_field(
    field_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> RegistryFieldPayload:
    _ = current_user
    f = _service().get_field(field_id)
    if f is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"NEMSIS field '{field_id}' is not present in the official "
                "registry. The service does not invent fields."
            ),
        )
    return RegistryFieldPayload(**f)


@router.get("/element-enumerations", response_model=list[RegistryEnumerationPayload])
async def list_element_enumerations(
    field_id: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
) -> list[RegistryEnumerationPayload]:
    _ = current_user
    return [
        RegistryEnumerationPayload(**r)
        for r in _service().list_element_enumerations(field_id=field_id)
    ]


@router.get("/attribute-enumerations", response_model=list[RegistryEnumerationPayload])
async def list_attribute_enumerations(
    attribute_name: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
) -> list[RegistryEnumerationPayload]:
    _ = current_user
    return [
        RegistryEnumerationPayload(**r)
        for r in _service().list_attribute_enumerations(attribute_name=attribute_name)
    ]


@router.get("/defined-lists", response_model=list[RegistryDefinedListPayload])
async def list_defined_lists(
    current_user: CurrentUser = Depends(get_current_user),
) -> list[RegistryDefinedListPayload]:
    _ = current_user
    return [RegistryDefinedListPayload(**r) for r in _service().list_defined_lists()]


@router.get("/code-sets/{field_id}", response_model=list[RegistryCodeSetPayload])
async def list_code_sets(
    field_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> list[RegistryCodeSetPayload]:
    _ = current_user
    return [RegistryCodeSetPayload(**row) for row in _service().list_code_sets(field_id)]


@router.post("/evaluate", response_model=RegistryEvaluateResponse)
async def evaluate_registry_coverage(
    payload: RegistryEvaluateRequest = Body(...),
    current_user: CurrentUser = Depends(get_current_user),
) -> RegistryEvaluateResponse:
    """Read-only coverage analysis. NEVER persists chart_state or PHI."""

    _ = current_user
    result = _service().evaluate_registry_coverage(
        chart_state=payload.chart_state, dataset=payload.dataset
    )
    return RegistryEvaluateResponse(**result)
