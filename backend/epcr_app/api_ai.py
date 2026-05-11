"""AI clinical intelligence API routes.

Router prefix: /api/v1/epcr/ai
Tag: ai

Endpoints:
  POST /charts/{chart_id}/narrative              — generate + persist AiNarrativeGeneration
  GET  /charts/{chart_id}/narratives             — list narrative generations for chart
  POST /charts/{chart_id}/narratives/{id}/review — accept/edit/reject narrative
  POST /charts/{chart_id}/billing-readiness      — run + persist AiBillingReadiness
  GET  /charts/{chart_id}/billing-readiness      — latest billing readiness for chart
  POST /charts/{chart_id}/qa-flags               — run QA analysis + persist AiQaFlag records
  GET  /charts/{chart_id}/qa-flags               — list unresolved QA flags
  POST /charts/{chart_id}/qa-flags/{id}/resolve  — resolve a QA flag with note
  POST /charts/{chart_id}/clinical-prompts       — generate clinical prompts for trigger event
  GET  /charts/{chart_id}/clinical-prompts       — list active (undismissed) prompts
  POST /charts/{chart_id}/clinical-prompts/{id}/dismiss — dismiss a prompt
  GET  /protocol-packs                           — return PROTOCOL_PACKS registry as JSON
  GET  /protocol-packs/{pack_name}               — return single protocol pack

Safety invariants enforced on every write:
- ai_signed is always False
- ai_marked_complete is always False
- human_review_required is always True on narrative responses
"""
from __future__ import annotations

import logging
from datetime import datetime, UTC
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.ai_clinical_engine import AdaptixClinicalAiEngine, PROTOCOL_PACKS
from epcr_app.db import get_session
from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.models_ai import (
    AiBillingReadiness,
    AiClinicalPrompt,
    AiNarrativeGeneration,
    AiQaFlag,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/epcr/ai",
    tags=["ai"],
)

# ---------------------------------------------------------------------------
# Shared engine instance (stateless — safe to reuse)
# ---------------------------------------------------------------------------

_engine = AdaptixClinicalAiEngine()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class GenerateNarrativeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    narrative_type: str = "structured"
    chart_data: dict[str, Any] = {}


class ReviewNarrativeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str  # "accepted" | "edited" | "rejected" | "regenerated"
    final_text: str | None = None
    edit_note: str | None = None


class BillingReadinessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_type: str = "ems"
    chart_data: dict[str, Any] = {}


class RunQaFlagsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chart_data: dict[str, Any] = {}
    protocol_pack: str | None = None


class ResolveQaFlagRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution_note: str


class GenerateClinicalPromptsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chart_data: dict[str, Any] = {}
    trigger_event: str
    protocol_pack: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_REVIEW_ACTIONS = {"accepted", "edited", "rejected", "regenerated"}


def _row_to_narrative_dict(row: AiNarrativeGeneration) -> dict:
    return {
        "id": row.id,
        "chart_id": row.chart_id,
        "tenant_id": row.tenant_id,
        "narrative_type": row.narrative_type,
        "generated_text": row.generated_text,
        "source_fields": row.source_fields_json,
        "missing_fields": row.missing_fields_json,
        "warnings": row.warnings_json,
        "model_used": row.model_used,
        "human_review_required": row.human_review_required,
        "review_status": row.review_status,
        "reviewed_by": row.reviewed_by,
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "final_text": row.final_text,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "ai_signed": False,           # SAFETY INVARIANT
        "ai_marked_complete": False,  # SAFETY INVARIANT
    }


def _row_to_billing_dict(row: AiBillingReadiness) -> dict:
    return {
        "id": row.id,
        "chart_id": row.chart_id,
        "tenant_id": row.tenant_id,
        "assessed_at": row.assessed_at.isoformat() if row.assessed_at else None,
        "assessed_by": row.assessed_by,
        "score": row.score,
        "missing_fields": row.missing_fields_json,
        "warnings": row.warnings_json,
        "blockers": row.blockers_json,
        "cms_service_level_risk": row.cms_service_level_risk,
        "medical_necessity_complete": row.medical_necessity_complete,
        "pcs_required": row.pcs_required,
        "pcs_complete": row.pcs_complete,
        "mileage_documented": row.mileage_documented,
        "signature_complete": row.signature_complete,
        "origin_destination_complete": row.origin_destination_complete,
    }


def _row_to_qa_flag_dict(row: AiQaFlag) -> dict:
    return {
        "id": row.id,
        "chart_id": row.chart_id,
        "tenant_id": row.tenant_id,
        "flag_type": row.flag_type,
        "severity": row.severity,
        "field_path": row.field_path,
        "description": row.description,
        "suggested_action": row.suggested_action,
        "resolved": row.resolved,
        "resolved_by": row.resolved_by,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "resolution_note": row.resolution_note,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "created_by_system": row.created_by_system,
    }


def _row_to_prompt_dict(row: AiClinicalPrompt) -> dict:
    return {
        "id": row.id,
        "chart_id": row.chart_id,
        "tenant_id": row.tenant_id,
        "trigger_event": row.trigger_event,
        "prompt_type": row.prompt_type,
        "protocol_pack": row.protocol_pack,
        "prompt_text": row.prompt_text,
        "field_references": row.field_references_json,
        "dismissed": row.dismissed,
        "dismissed_by": row.dismissed_by,
        "dismissed_at": row.dismissed_at.isoformat() if row.dismissed_at else None,
        "acted_upon": row.acted_upon,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


# ---------------------------------------------------------------------------
# Narrative endpoints
# ---------------------------------------------------------------------------


@router.post("/charts/{chart_id}/narrative", status_code=status.HTTP_201_CREATED)
async def generate_narrative(
    chart_id: str,
    body: GenerateNarrativeRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Generate and persist an AI narrative for the chart.

    The result always requires human review. ai_signed and ai_marked_complete
    are always False and cannot be changed by the AI.
    """
    try:
        result = await _engine.generate_narrative(
            narrative_type=body.narrative_type,
            chart_data=body.chart_data,
            tenant_id=str(user.tenant_id),
            actor_id=str(user.user_id),
        )
    except Exception as exc:
        logger.error("generate_narrative: engine error: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI engine unavailable — try again later",
        ) from exc

    row = AiNarrativeGeneration(
        id=str(uuid4()),
        chart_id=chart_id,
        tenant_id=str(user.tenant_id),
        narrative_type=body.narrative_type,
        generated_text=result["narrative_text"],
        source_fields_json={"references": result["source_references"]},
        missing_fields_json=result.get("unsupported_statements", []),
        warnings_json=result.get("warnings", []),
        model_used=result.get("model"),
        human_review_required=True,
        review_status="pending",
        created_by=str(user.user_id),
        created_at=datetime.now(UTC),
        ai_signed=False,
        ai_marked_complete=False,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _row_to_narrative_dict(row)


@router.get("/charts/{chart_id}/narratives")
async def list_narratives(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """List all narrative generations for a chart."""
    result = await session.execute(
        select(AiNarrativeGeneration)
        .where(
            AiNarrativeGeneration.chart_id == chart_id,
            AiNarrativeGeneration.tenant_id == str(user.tenant_id),
        )
        .order_by(AiNarrativeGeneration.created_at.desc())
    )
    rows = result.scalars().all()
    return {
        "chart_id": chart_id,
        "count": len(rows),
        "items": [_row_to_narrative_dict(r) for r in rows],
    }


@router.post("/charts/{chart_id}/narratives/{narrative_id}/review")
async def review_narrative(
    chart_id: str,
    narrative_id: str,
    body: ReviewNarrativeRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Accept, edit, reject, or mark a narrative for regeneration.

    Only a human provider may set the review_status. The AI cannot call
    this endpoint on its own behalf.
    """
    if body.action not in _VALID_REVIEW_ACTIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"action must be one of {sorted(_VALID_REVIEW_ACTIONS)}",
        )

    result = await session.execute(
        select(AiNarrativeGeneration).where(
            AiNarrativeGeneration.id == narrative_id,
            AiNarrativeGeneration.chart_id == chart_id,
            AiNarrativeGeneration.tenant_id == str(user.tenant_id),
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="narrative not found")

    row.review_status = body.action
    row.reviewed_by = str(user.user_id)
    row.reviewed_at = datetime.now(UTC)

    if body.action in ("accepted", "edited"):
        row.final_text = body.final_text or row.generated_text

    # Safety invariants — cannot be changed through this endpoint
    row.ai_signed = False
    row.ai_marked_complete = False

    await session.commit()
    await session.refresh(row)
    return _row_to_narrative_dict(row)


# ---------------------------------------------------------------------------
# Billing readiness endpoints
# ---------------------------------------------------------------------------


@router.post("/charts/{chart_id}/billing-readiness", status_code=status.HTTP_201_CREATED)
async def run_billing_readiness(
    chart_id: str,
    body: BillingReadinessRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Run billing readiness assessment and persist results."""
    try:
        result = await _engine.assess_billing_readiness(
            chart_data=body.chart_data,
            service_type=body.service_type,
        )
    except Exception as exc:
        logger.error("billing_readiness: engine error: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI engine unavailable — try again later",
        ) from exc

    now = datetime.now(UTC)
    row = AiBillingReadiness(
        id=str(uuid4()),
        chart_id=chart_id,
        tenant_id=str(user.tenant_id),
        assessed_at=now,
        assessed_by=str(user.user_id),
        score=result["score"],
        missing_fields_json=result["missing_fields"],
        warnings_json=result["warnings"],
        blockers_json=result["blockers"],
        cms_service_level_risk=result["cms_service_level_risk"],
        medical_necessity_complete=result["medical_necessity_complete"],
        pcs_required=result["pcs_required"],
        pcs_complete=result["pcs_complete"],
        mileage_documented=result["mileage_documented"],
        signature_complete=result["signature_complete"],
        origin_destination_complete=result["origin_destination_complete"],
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _row_to_billing_dict(row)


@router.get("/charts/{chart_id}/billing-readiness")
async def get_billing_readiness(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Return the most recent billing readiness assessment for a chart."""
    result = await session.execute(
        select(AiBillingReadiness)
        .where(
            AiBillingReadiness.chart_id == chart_id,
            AiBillingReadiness.tenant_id == str(user.tenant_id),
        )
        .order_by(AiBillingReadiness.assessed_at.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no billing readiness assessment found for this chart",
        )
    return _row_to_billing_dict(row)


# ---------------------------------------------------------------------------
# QA flag endpoints
# ---------------------------------------------------------------------------


@router.post("/charts/{chart_id}/qa-flags", status_code=status.HTTP_201_CREATED)
async def run_qa_flags(
    chart_id: str,
    body: RunQaFlagsRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Run QA analysis and persist detected flags."""
    try:
        flags = await _engine.detect_qa_flags(
            chart_data=body.chart_data,
            protocol_pack=body.protocol_pack,
        )
    except Exception as exc:
        logger.error("qa_flags: engine error: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI engine unavailable — try again later",
        ) from exc

    rows = []
    for f in flags:
        row = AiQaFlag(
            id=str(uuid4()),
            chart_id=chart_id,
            tenant_id=str(user.tenant_id),
            flag_type=f["flag_type"],
            severity=f["severity"],
            field_path=f.get("field_path"),
            description=f["description"],
            suggested_action=f.get("suggested_action"),
            resolved=False,
            created_at=datetime.now(UTC),
            created_by_system=True,
        )
        session.add(row)
        rows.append(row)

    await session.commit()
    for r in rows:
        await session.refresh(r)

    return {
        "chart_id": chart_id,
        "flags_created": len(rows),
        "items": [_row_to_qa_flag_dict(r) for r in rows],
    }


@router.get("/charts/{chart_id}/qa-flags")
async def list_qa_flags(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """List unresolved QA flags for a chart."""
    result = await session.execute(
        select(AiQaFlag)
        .where(
            AiQaFlag.chart_id == chart_id,
            AiQaFlag.tenant_id == str(user.tenant_id),
            AiQaFlag.resolved == False,  # noqa: E712
        )
        .order_by(AiQaFlag.created_at.desc())
    )
    rows = result.scalars().all()
    return {
        "chart_id": chart_id,
        "count": len(rows),
        "items": [_row_to_qa_flag_dict(r) for r in rows],
    }


@router.post("/charts/{chart_id}/qa-flags/{flag_id}/resolve")
async def resolve_qa_flag(
    chart_id: str,
    flag_id: str,
    body: ResolveQaFlagRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Resolve a QA flag with a provider note."""
    result = await session.execute(
        select(AiQaFlag).where(
            AiQaFlag.id == flag_id,
            AiQaFlag.chart_id == chart_id,
            AiQaFlag.tenant_id == str(user.tenant_id),
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="qa flag not found")

    row.resolved = True
    row.resolved_by = str(user.user_id)
    row.resolved_at = datetime.now(UTC)
    row.resolution_note = body.resolution_note

    await session.commit()
    await session.refresh(row)
    return _row_to_qa_flag_dict(row)


# ---------------------------------------------------------------------------
# Clinical prompts endpoints
# ---------------------------------------------------------------------------


@router.post("/charts/{chart_id}/clinical-prompts", status_code=status.HTTP_201_CREATED)
async def generate_clinical_prompts(
    chart_id: str,
    body: GenerateClinicalPromptsRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Generate and persist clinical documentation prompts for a trigger event."""
    try:
        prompts = await _engine.generate_clinical_prompts(
            chart_data=body.chart_data,
            trigger_event=body.trigger_event,
            protocol_pack=body.protocol_pack,
        )
    except Exception as exc:
        logger.error("clinical_prompts: engine error: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI engine unavailable — try again later",
        ) from exc

    rows = []
    for p in prompts:
        row = AiClinicalPrompt(
            id=str(uuid4()),
            chart_id=chart_id,
            tenant_id=str(user.tenant_id),
            trigger_event=body.trigger_event,
            prompt_type=p["prompt_type"],
            protocol_pack=p.get("protocol_pack"),
            prompt_text=p["prompt_text"],
            field_references_json=p.get("field_references", []),
            dismissed=False,
            acted_upon=False,
            created_at=datetime.now(UTC),
        )
        session.add(row)
        rows.append(row)

    await session.commit()
    for r in rows:
        await session.refresh(r)

    return {
        "chart_id": chart_id,
        "prompts_created": len(rows),
        "items": [_row_to_prompt_dict(r) for r in rows],
    }


@router.get("/charts/{chart_id}/clinical-prompts")
async def list_clinical_prompts(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """List active (undismissed) clinical prompts for a chart."""
    result = await session.execute(
        select(AiClinicalPrompt)
        .where(
            AiClinicalPrompt.chart_id == chart_id,
            AiClinicalPrompt.tenant_id == str(user.tenant_id),
            AiClinicalPrompt.dismissed == False,  # noqa: E712
        )
        .order_by(AiClinicalPrompt.created_at.desc())
    )
    rows = result.scalars().all()
    return {
        "chart_id": chart_id,
        "count": len(rows),
        "items": [_row_to_prompt_dict(r) for r in rows],
    }


@router.post("/charts/{chart_id}/clinical-prompts/{prompt_id}/dismiss")
async def dismiss_clinical_prompt(
    chart_id: str,
    prompt_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Dismiss a clinical documentation prompt."""
    result = await session.execute(
        select(AiClinicalPrompt).where(
            AiClinicalPrompt.id == prompt_id,
            AiClinicalPrompt.chart_id == chart_id,
            AiClinicalPrompt.tenant_id == str(user.tenant_id),
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="prompt not found")

    row.dismissed = True
    row.dismissed_by = str(user.user_id)
    row.dismissed_at = datetime.now(UTC)

    await session.commit()
    await session.refresh(row)
    return _row_to_prompt_dict(row)


# ---------------------------------------------------------------------------
# Protocol packs registry endpoints
# ---------------------------------------------------------------------------


@router.get("/protocol-packs")
async def list_protocol_packs(
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Return the full protocol packs registry."""
    return {
        "count": len(PROTOCOL_PACKS),
        "packs": {name: pack for name, pack in PROTOCOL_PACKS.items()},
    }


@router.get("/protocol-packs/{pack_name}")
async def get_protocol_pack(
    pack_name: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Return a single protocol pack by name."""
    pack = PROTOCOL_PACKS.get(pack_name.upper())
    if pack is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"protocol pack '{pack_name}' not found",
        )
    return {"name": pack_name.upper(), **pack}


__all__ = ["router"]
