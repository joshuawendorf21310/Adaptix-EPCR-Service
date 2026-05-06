"""HTTP routes exposing the NEMSIS field graph (Slice A).

Read-only endpoints over ``NemsisFieldGraphService``. No PHI is read or
written. Auth uses the same ``get_current_user`` dependency the rest of the
ePCR service relies on so tenant context is preserved even though the graph
itself is tenant-agnostic.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.nemsis_field_graph import (
    DEFAULT_GRAPH_SOURCE,
    NemsisFieldGraphService,
    get_default_service,
)

logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/epcr/nemsis-field-graph",
    tags=["nemsis-field-graph"],
)


class FieldRequiredIfPayload(BaseModel):
    field_id: str
    operator: str
    expected: object | None = None


class FieldDefinitionPayload(BaseModel):
    field_id: str
    section: str
    label: str
    data_type: str
    required_level: str
    allowed_values: list[str]
    required_if: list[FieldRequiredIfPayload]
    source: str


class SectionSummaryPayload(BaseModel):
    section: str
    total_fields: int
    required_fields: int
    required_if_fields: int
    recommended_fields: int
    optional_fields: int


class FieldGraphResponse(BaseModel):
    source: str
    field_count: int
    section_count: int
    sections: list[SectionSummaryPayload]
    fields: list[FieldDefinitionPayload]


class FieldGraphSectionResponse(BaseModel):
    source: str
    section: str
    summary: SectionSummaryPayload
    fields: list[FieldDefinitionPayload]


def _service() -> NemsisFieldGraphService:
    return get_default_service()


@router.get("", response_model=FieldGraphResponse)
async def get_nemsis_field_graph(
    current_user: CurrentUser = Depends(get_current_user),
) -> FieldGraphResponse:
    """Return the full NEMSIS field graph metadata catalog."""

    _ = current_user  # auth required; graph itself is tenant-agnostic metadata
    service = _service()
    fields = service.list_fields()
    sections = service.list_sections()
    return FieldGraphResponse(
        source=DEFAULT_GRAPH_SOURCE,
        field_count=len(fields),
        section_count=len(sections),
        sections=[SectionSummaryPayload(**s.to_payload()) for s in sections],
        fields=[FieldDefinitionPayload(**f.to_payload()) for f in fields],
    )


@router.get("/sections/{section}", response_model=FieldGraphSectionResponse)
async def get_nemsis_field_graph_section(
    section: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> FieldGraphSectionResponse:
    """Return the metadata for a single NEMSIS section."""

    _ = current_user
    service = _service()
    fields = service.list_section(section)
    if not fields:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown NEMSIS section: {section}",
        )

    summary = next(s for s in service.list_sections() if s.section == section)
    return FieldGraphSectionResponse(
        source=DEFAULT_GRAPH_SOURCE,
        section=section,
        summary=SectionSummaryPayload(**summary.to_payload()),
        fields=[FieldDefinitionPayload(**f.to_payload()) for f in fields],
    )
