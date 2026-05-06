"""HTTP routes exposing the NEMSIS defined-list picker catalog (Slice 3 + 3B).

Read-only endpoints over ``NemsisDefinedListService``. No PHI is read or
written. Auth uses the same ``get_current_user`` dependency the rest of the
ePCR service relies on so tenant context is preserved even though the
defined-list catalog itself is tenant-agnostic metadata.

Slice 3B additions (additive, backwards compatible):
* The catalog response includes ``official_source_url``, ``official_list_count``,
  ``local_seed_fallback_count``, and ``coverage_mode``.
* Each field payload now includes ``list_name``, ``source_url``,
  ``upstream_date``, ``retrieved_at``, and ``value_count`` (all optional /
  honest-empty when the field came from the local seed fallback).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.nemsis_defined_lists import (
    NemsisDefinedListService,
    OFFICIAL_DEFINED_LIST_SOURCE_URL,
    get_default_defined_list_service,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/epcr/nemsis-defined-lists",
    tags=["nemsis-defined-lists"],
)


class DefinedListValuePayload(BaseModel):
    code: str
    display: str
    description: str | None = None
    active: bool | None = None
    category: str | None = None


class DefinedListFieldPayload(BaseModel):
    field_id: str
    section: str
    label: str
    source: str
    version: str | None = None
    list_name: str | None = None
    source_url: str | None = None
    upstream_date: str | None = None
    retrieved_at: str | None = None
    value_count: int = 0
    values: list[DefinedListValuePayload]


class DefinedListCatalogResponse(BaseModel):
    source: str
    version: str | None = None
    field_count: int
    official_source_url: str = OFFICIAL_DEFINED_LIST_SOURCE_URL
    official_list_count: int = 0
    local_seed_fallback_count: int = 0
    coverage_mode: str
    source_repo: str | None = None
    source_commit: str | None = None
    target_version: str | None = None
    official_artifact_count: int = 0
    source_mode: str | None = None
    fields: list[DefinedListFieldPayload]


def _service() -> NemsisDefinedListService:
    return get_default_defined_list_service()


@router.get("", response_model=DefinedListCatalogResponse)
async def list_nemsis_defined_lists(
    current_user: CurrentUser = Depends(get_current_user),
) -> DefinedListCatalogResponse:
    """Return every NEMSIS field that is backed by a defined-list picker."""

    _ = current_user  # auth required; metadata itself is tenant-agnostic
    service = _service()
    catalog = service.catalog()
    return DefinedListCatalogResponse(
        source=catalog.source,
        version=catalog.version,
        field_count=catalog.field_count,
        official_source_url=catalog.official_source_url,
        official_list_count=catalog.official_list_count,
        local_seed_fallback_count=catalog.local_seed_fallback_count,
        coverage_mode=catalog.coverage_mode,
        source_repo=catalog.source_repo,
        source_commit=catalog.source_commit,
        target_version=catalog.target_version,
        official_artifact_count=catalog.official_artifact_count,
        source_mode=catalog.source_mode,
        fields=[DefinedListFieldPayload(**f.to_payload()) for f in catalog.fields],
    )


@router.get("/{field_id}", response_model=DefinedListFieldPayload)
async def get_nemsis_defined_list(
    field_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> DefinedListFieldPayload:
    """Return the defined-list values for ``field_id``.

    Returns 404 when ``field_id`` is not a defined-list-backed field in the
    local catalog. The service does NOT fabricate values for unknown fields.
    """

    _ = current_user
    service = _service()
    picker = service.get_defined_list(field_id)
    if picker is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"NEMSIS field '{field_id}' is not present in the local "
                "defined-list catalog. The catalog only exposes locally "
                "proven defined-list fields and does not fabricate coverage."
            ),
        )
    return DefinedListFieldPayload(**picker.to_payload())
