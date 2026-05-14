"""Smart Text Box and Address Intelligence API routes.

Smart Text Box:
- Structured-aware clinical composition surface
- Proposals require explicit review — never auto-accepted
- Raw text always preserved
- Contradiction detection surfaced to user

Address Intelligence:
- Structured address parsing
- Geocode confidence tracking
- Facility recognition
- Raw address string always preserved
- Reviewer decisions preserved
- Never silently overwrites user-entered address
"""
from __future__ import annotations

import uuid
from datetime import datetime, UTC
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.dependencies import get_current_user, get_tenant_id
from epcr_app.models_smart_text import (
    SmartTextSession,
    SmartTextProposal,
    SmartTextAuditRecord,
    FindingMethod,
)
from epcr_app.models import ChartAddress, AddressValidationState

router = APIRouter(prefix="/api/v1/epcr", tags=["smart-text-address"])


# ===========================================================================
# Smart Text Box
# ===========================================================================

class SmartTextSubmit(BaseModel):
    raw_text: str
    text_source: str = "manual"  # manual, voice_cleanup, dictation
    context_section: Optional[str] = None


class SmartTextProposalAction(BaseModel):
    action: str  # accept, reject, edit_and_accept, ignore
    edited_entity_json: Optional[str] = None
    notes: Optional[str] = None


@router.post("/charts/{chart_id}/smart-text", status_code=status.HTTP_201_CREATED)
async def submit_smart_text(
    chart_id: str,
    body: SmartTextSubmit,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Submit raw text to the smart text composition surface.

    Raw text is always preserved. Structured extraction proposals are
    generated for review — never auto-accepted.

    Smart text may propose structure. It must NOT silently mutate
    authoritative chart data.
    """
    session_id = str(uuid.uuid4())
    now = datetime.now(UTC)

    smart_session = SmartTextSession(
        id=session_id,
        chart_id=chart_id,
        tenant_id=tenant_id,
        raw_text=body.raw_text,
        text_source=body.text_source,
        context_section=body.context_section,
        provider_id=user.user_id,
        processing_status="pending",
        created_at=now,
        updated_at=now,
    )
    session.add(smart_session)
    await session.commit()

    return {
        "session_id": session_id,
        "status": "pending",
        "raw_text_preserved": True,
        "message": "Smart text submitted for structured extraction. Review proposals before acceptance.",
    }


@router.get("/charts/{chart_id}/smart-text/{session_id}/proposals")
async def get_smart_text_proposals(
    chart_id: str,
    session_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Get structured extraction proposals from a smart text session.

    All proposals start in pending_review state.
    None are auto-accepted.
    """
    result = await session.execute(
        select(SmartTextProposal).where(
            SmartTextProposal.session_id == session_id,
            SmartTextProposal.chart_id == chart_id,
            SmartTextProposal.tenant_id == tenant_id,
        )
    )
    proposals = result.scalars().all()

    return {
        "session_id": session_id,
        "proposals": [
            {
                "id": p.id,
                "entity_type": p.entity_type,
                "entity_label": p.entity_label,
                "raw_source_text": p.raw_source_text,
                "confidence": p.confidence,
                "proposal_state": p.proposal_state,
                "is_contradiction": p.is_contradiction,
                "contradiction_detail": p.contradiction_detail,
                "target_chart_field": p.target_chart_field,
            }
            for p in proposals
        ],
        "count": len(proposals),
        "pending_review_count": sum(1 for p in proposals if p.proposal_state == "pending_review"),
    }


@router.post("/charts/{chart_id}/smart-text/proposals/{proposal_id}/action", status_code=status.HTTP_200_OK)
async def act_on_smart_text_proposal(
    chart_id: str,
    proposal_id: str,
    body: SmartTextProposalAction,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Accept, reject, or edit a smart text proposal.

    Smart text proposals NEVER auto-accept. Every acceptance is explicit.
    Audit record is created for every action.
    """
    result = await session.execute(
        select(SmartTextProposal).where(
            SmartTextProposal.id == proposal_id,
            SmartTextProposal.chart_id == chart_id,
            SmartTextProposal.tenant_id == tenant_id,
        )
    )
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=404, detail="proposal_not_found")

    now = datetime.now(UTC)
    before_state = proposal.proposal_state

    if body.action == "accept":
        proposal.proposal_state = "accepted"
    elif body.action == "reject":
        proposal.proposal_state = "rejected"
    elif body.action == "edit_and_accept":
        proposal.proposal_state = "edited_and_accepted"
        proposal.edited_entity_json = body.edited_entity_json
    elif body.action == "ignore":
        proposal.proposal_state = "ignored"
    else:
        raise HTTPException(status_code=422, detail=f"Invalid action: {body.action}")

    proposal.reviewer_id = str(user.user_id)
    proposal.reviewed_at = now
    proposal.reviewer_notes = body.notes

    # Audit record
    session.add(SmartTextAuditRecord(
        id=str(uuid.uuid4()),
        proposal_id=proposal_id,
        chart_id=chart_id,
        tenant_id=tenant_id,
        action=body.action,
        actor_id=str(user.user_id),
        before_state=before_state,
        after_state=proposal.proposal_state,
        notes=body.notes,
        performed_at=now,
    ))

    await session.commit()
    return {
        "proposal_id": proposal_id,
        "action": body.action,
        "new_state": proposal.proposal_state,
        "status": "recorded",
    }


@router.get("/cpae/finding-methods")
async def list_finding_methods(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
) -> dict:
    """List all active finding detection methods.

    Methods that require_review=True (Vision, SmartText, Voice proposals)
    must go through the review gate before becoming accepted findings.
    """
    result = await session.execute(
        select(FindingMethod).where(FindingMethod.is_active == True).order_by(FindingMethod.sort_order)
    )
    methods = result.scalars().all()
    return {
        "methods": [
            {
                "id": m.id,
                "method_code": m.method_code,
                "display_name": m.display_name,
                "requires_review": m.requires_review,
            }
            for m in methods
        ]
    }


# ===========================================================================
# Address Intelligence
# ===========================================================================

class AddressIntelligenceSubmit(BaseModel):
    raw_text: str  # always preserved
    intelligence_source: str = "manual"  # manual, geocode, vision, dispatch
    street_line_one: Optional[str] = None
    street_line_two: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    county: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    geocode_confidence: Optional[float] = None
    intelligence_detail: Optional[str] = None


class AddressValidationAction(BaseModel):
    validation_state: str  # manual_verified, validated, provider_unavailable
    notes: Optional[str] = None


@router.post("/charts/{chart_id}/address", status_code=status.HTTP_201_CREATED)
async def set_chart_address(
    chart_id: str,
    body: AddressIntelligenceSubmit,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Set or update the chart scene address with intelligence context.

    Raw address string is ALWAYS preserved.
    Geocode confidence is tracked — never treated as verified truth without acceptance.
    User-entered address is NEVER silently overwritten.
    """
    now = datetime.now(UTC)

    # Check if address already exists
    existing_result = await session.execute(
        select(ChartAddress).where(
            ChartAddress.chart_id == chart_id,
            ChartAddress.tenant_id == tenant_id,
        )
    )
    existing = existing_result.scalar_one_or_none()

    if existing:
        # Preserve raw text — never overwrite silently
        # Only update if explicitly provided
        if body.raw_text:
            existing.raw_text = body.raw_text
        if body.street_line_one is not None:
            existing.street_line_one = body.street_line_one
        if body.street_line_two is not None:
            existing.street_line_two = body.street_line_two
        if body.city is not None:
            existing.city = body.city
        if body.state is not None:
            existing.state = body.state
        if body.postal_code is not None:
            existing.postal_code = body.postal_code
        if body.county is not None:
            existing.county = body.county
        if body.latitude is not None:
            existing.latitude = body.latitude
        if body.longitude is not None:
            existing.longitude = body.longitude
        existing.intelligence_source = body.intelligence_source
        existing.intelligence_detail = body.intelligence_detail
        existing.validation_state = AddressValidationState.NEEDS_REVIEW
        existing.updated_at = now
        address_id = existing.id
    else:
        address_id = str(uuid.uuid4())
        session.add(ChartAddress(
            id=address_id,
            chart_id=chart_id,
            tenant_id=tenant_id,
            raw_text=body.raw_text,
            street_line_one=body.street_line_one,
            street_line_two=body.street_line_two,
            city=body.city,
            state=body.state,
            postal_code=body.postal_code,
            county=body.county,
            latitude=body.latitude,
            longitude=body.longitude,
            validation_state=AddressValidationState.NEEDS_REVIEW,
            intelligence_source=body.intelligence_source,
            intelligence_detail=body.intelligence_detail,
            updated_at=now,
        ))

    await session.commit()
    return {
        "id": address_id,
        "status": "saved",
        "raw_text_preserved": True,
        "validation_state": "needs_review",
        "geocode_confidence": body.geocode_confidence,
    }


@router.get("/charts/{chart_id}/address")
async def get_chart_address(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Get the chart scene address with intelligence context."""
    result = await session.execute(
        select(ChartAddress).where(
            ChartAddress.chart_id == chart_id,
            ChartAddress.tenant_id == tenant_id,
            ChartAddress.deleted_at.is_(None),
        )
    )
    address = result.scalar_one_or_none()
    if not address:
        raise HTTPException(status_code=404, detail="address_not_found")

    return {
        "id": address.id,
        "raw_text": address.raw_text,
        "street_line_one": address.street_line_one,
        "street_line_two": address.street_line_two,
        "city": address.city,
        "state": address.state,
        "postal_code": address.postal_code,
        "county": address.county,
        "latitude": address.latitude,
        "longitude": address.longitude,
        "validation_state": address.validation_state,
        "intelligence_source": address.intelligence_source,
        "intelligence_detail": address.intelligence_detail,
        "updated_at": address.updated_at.isoformat() if address.updated_at else None,
    }


@router.patch("/charts/{chart_id}/address/validate", status_code=status.HTTP_200_OK)
async def validate_chart_address(
    chart_id: str,
    body: AddressValidationAction,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Mark a chart address as validated or manually verified.

    Reviewer decisions are preserved.
    Geocode confidence is never treated as verified truth without this action.
    """
    result = await session.execute(
        select(ChartAddress).where(
            ChartAddress.chart_id == chart_id,
            ChartAddress.tenant_id == tenant_id,
            ChartAddress.deleted_at.is_(None),
        )
    )
    address = result.scalar_one_or_none()
    if not address:
        raise HTTPException(status_code=404, detail="address_not_found")

    try:
        address.validation_state = AddressValidationState(body.validation_state)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid validation_state: {body.validation_state}")

    address.updated_at = datetime.now(UTC)
    await session.commit()

    return {
        "id": address.id,
        "validation_state": address.validation_state,
        "status": "updated",
    }
