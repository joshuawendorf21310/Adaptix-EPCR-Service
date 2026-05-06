"""HTTP routes exposing the NEMSIS custom element catalog (Slice 4).

Read-only endpoints over ``NemsisCustomElementService``. No PHI is read
or written. No XML is generated. No CTA submission occurs. Auth uses the
same ``get_current_user`` dependency the rest of the ePCR service uses.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.nemsis_custom_elements import (
    ALLOWED_DATASETS,
    NemsisCustomElementService,
    UnknownDatasetError,
    get_default_custom_element_service,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/epcr/nemsis-custom-elements",
    tags=["nemsis-custom-elements"],
)


class CustomElementPayload(BaseModel):
    element_id: str
    dataset: str
    section: str
    label: str
    data_type: str
    required: bool
    allowed_values: list[str]
    source: str
    version: str
    description: str | None = None


class CustomElementCatalogResponse(BaseModel):
    source: str
    version: str
    field_count: int
    elements: list[CustomElementPayload]


def _service() -> NemsisCustomElementService:
    return get_default_custom_element_service()


@router.get("", response_model=CustomElementCatalogResponse)
async def list_nemsis_custom_elements(
    dataset: str | None = Query(
        default=None,
        description=(
            "Optional dataset filter. Must be one of: "
            f"{', '.join(ALLOWED_DATASETS)}."
        ),
    ),
    current_user: CurrentUser = Depends(get_current_user),
) -> CustomElementCatalogResponse:
    """Return locally-registered NEMSIS custom elements (read-only)."""

    _ = current_user  # auth required; metadata itself is tenant-agnostic
    try:
        catalog = _service().catalog(dataset)
    except UnknownDatasetError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    payload = catalog.to_payload()
    return CustomElementCatalogResponse(**payload)


@router.get("/{element_id}", response_model=CustomElementPayload)
async def get_nemsis_custom_element(
    element_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> CustomElementPayload:
    """Return a single locally-registered custom element.

    Returns 404 when ``element_id`` is not present in the local catalog.
    The service does NOT fabricate custom elements.
    """

    _ = current_user
    element = _service().get_custom_element(element_id)
    if element is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"NEMSIS custom element '{element_id}' is not present in the "
                "local custom element catalog. The catalog only exposes "
                "locally registered custom elements and does not fabricate "
                "coverage."
            ),
        )
    return CustomElementPayload(**element.to_payload())
