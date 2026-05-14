"""Quality module API router: Medical Director, QA, and QI endpoints.

RBAC is enforced on every endpoint. tenant_id always comes from JWT claims.
Every mutation creates a QualityAuditEvent.

Role definitions:
  medical_director, assistant_medical_director — clinical governance access
  qa_reviewer — QA case access
  qi_lead — QI initiative access
  peer_reviewer — assigned peer review access only
  clinical_supervisor — supervisor access
  provider — own feedback and education only
  agency_admin — agency-level configuration and summaries
  educator — education management
  system_admin — platform-level operations
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.models_quality import (
    AccreditationEvidencePackage,
    ClinicalVariance,
    EducationFollowUp,
    MedicalDirectorNote,
    MedicalDirectorReview,
    PeerReview,
    ProtocolAcknowledgment,
    ProtocolDocument,
    ProtocolVersion,
    ProviderFeedback,
    QACaseRecord,
    QAReviewFinding,
    QAScore,
    QATriggerConfiguration,
    QIActionItem,
    QICommitteeReview,
    QIInitiative,
    QIInitiativeMetric,
    QualityAuditEvent,
    StandingOrder,
    StandingOrderVersion,
)
from epcr_app.quality_service import (
    ConflictOfInterestError,
    QAWorkflowError,
    QualityService,
    _new_id,
    _now,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/quality", tags=["quality"])

_MD_ROLES = {"medical_director", "assistant_medical_director"}
_QA_ROLES = {"qa_reviewer", "medical_director", "assistant_medical_director", "clinical_supervisor", "agency_admin", "system_admin"}
_QI_ROLES = {"qi_lead", "medical_director", "assistant_medical_director", "agency_admin", "system_admin"}
_ADMIN_ROLES = {"agency_admin", "system_admin"}
_SENIOR_ROLES = {"medical_director", "assistant_medical_director", "qa_reviewer", "qi_lead", "clinical_supervisor", "agency_admin", "system_admin"}


def _require_any_role(user: CurrentUser, *roles: str) -> None:
    if not any(r in roles for r in user.roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied. Required role: one of {list(roles)}. You have: {user.roles}",
        )


def _user_primary_role(user: CurrentUser) -> str:
    priority = [
        "system_admin", "agency_admin", "medical_director", "assistant_medical_director",
        "qi_lead", "qa_reviewer", "clinical_supervisor", "peer_reviewer",
        "educator", "billing_reviewer", "provider",
    ]
    for r in priority:
        if r in user.roles:
            return r
    return user.roles[0] if user.roles else "unknown"


# ---------------------------------------------------------------------------
# QA TRIGGER CONFIGURATION
# ---------------------------------------------------------------------------

class CreateTriggerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trigger_key: str = Field(..., min_length=1, max_length=128)
    trigger_type: str = Field(..., pattern="^(mandatory|optional)$")
    trigger_label: str = Field(..., min_length=1, max_length=255)
    priority: str = Field(default="standard", pattern="^(critical|high|standard|low)$")
    condition_json: dict = Field(default_factory=dict)


@router.get("/triggers")
async def list_triggers(
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List active QA trigger configurations for the tenant."""
    _require_any_role(current_user, *_ADMIN_ROLES, "qa_reviewer", "medical_director")
    result = await session.execute(
        select(QATriggerConfiguration).where(
            QATriggerConfiguration.tenant_id == str(current_user.tenant_id),
            QATriggerConfiguration.deleted_at == None,  # noqa: E711
        )
    )
    return [_model_to_dict(t) for t in result.scalars().all()]


@router.post("/triggers", status_code=201)
async def create_trigger(
    payload: CreateTriggerRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Create a QA trigger configuration (agency_admin only)."""
    _require_any_role(current_user, *_ADMIN_ROLES)
    import json as _json
    now = _now()
    trigger = QATriggerConfiguration(
        id=_new_id(),
        tenant_id=str(current_user.tenant_id),
        trigger_key=payload.trigger_key,
        trigger_type=payload.trigger_type,
        trigger_label=payload.trigger_label,
        priority=payload.priority,
        is_active=True,
        condition_json=_json.dumps(payload.condition_json),
        created_by=str(current_user.user_id),
        created_at=now,
        updated_by=str(current_user.user_id),
        updated_at=now,
    )
    session.add(trigger)
    await QualityService.emit_audit_event(
        session,
        tenant_id=str(current_user.tenant_id),
        actor_id=str(current_user.user_id),
        actor_role=_user_primary_role(current_user),
        event_type="trigger_configuration_changed",
        reference_type="qa_trigger",
        reference_id=trigger.id,
        metadata={"action": "created", "trigger_key": payload.trigger_key},
    )
    await session.commit()
    await session.refresh(trigger)
    return _model_to_dict(trigger)


@router.patch("/triggers/{trigger_id}")
async def update_trigger(
    trigger_id: str,
    payload: dict,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Update a QA trigger (agency_admin only). Mandatory triggers cannot be deactivated."""
    _require_any_role(current_user, *_ADMIN_ROLES)
    result = await session.execute(
        select(QATriggerConfiguration).where(
            QATriggerConfiguration.id == trigger_id,
            QATriggerConfiguration.tenant_id == str(current_user.tenant_id),
        )
    )
    trigger = result.scalar_one_or_none()
    if not trigger:
        raise HTTPException(status_code=404, detail="Trigger not found")

    if trigger.trigger_type == "mandatory" and payload.get("is_active") is False:
        raise HTTPException(
            status_code=400,
            detail="Mandatory triggers cannot be deactivated.",
        )

    now = _now()
    for field in ("trigger_label", "priority", "is_active"):
        if field in payload:
            setattr(trigger, field, payload[field])
    trigger.updated_by = str(current_user.user_id)
    trigger.updated_at = now

    await QualityService.emit_audit_event(
        session,
        tenant_id=str(current_user.tenant_id),
        actor_id=str(current_user.user_id),
        actor_role=_user_primary_role(current_user),
        event_type="trigger_configuration_changed",
        reference_type="qa_trigger",
        reference_id=trigger_id,
        metadata={"action": "updated"},
    )
    await session.commit()
    await session.refresh(trigger)
    return _model_to_dict(trigger)


# ---------------------------------------------------------------------------
# QA CASES
# ---------------------------------------------------------------------------

class CreateQACaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_chart_id: str
    trigger_key: str
    trigger_type: str = "supervisor"
    priority: str = "standard"
    agency_id: str | None = None
    due_date: datetime | None = None


class AssignQACaseRequest(BaseModel):
    reviewer_id: str
    due_date: datetime | None = None


class SubmitQAScoreRequest(BaseModel):
    documentation_quality_score: float = Field(..., ge=0, le=100)
    protocol_adherence_score: float = Field(..., ge=0, le=100)
    timeliness_score: float = Field(..., ge=0, le=100)
    clinical_quality_score: float = Field(..., ge=0, le=100)
    operational_quality_score: float = Field(..., ge=0, le=100)
    reviewer_notes: str | None = None
    context_flags: dict = Field(default_factory=dict)
    call_complexity_adjustment: float = Field(default=0.0, ge=-10, le=10)
    documentation_weight: float = Field(default=0.25, ge=0, le=1)
    protocol_weight: float = Field(default=0.25, ge=0, le=1)
    timeliness_weight: float = Field(default=0.15, ge=0, le=1)
    clinical_weight: float = Field(default=0.25, ge=0, le=1)
    operational_weight: float = Field(default=0.10, ge=0, le=1)


class AddFindingRequest(BaseModel):
    finding_type: str
    severity: str = "minor"
    domain: str = "documentation"
    description: str
    recommendation: str | None = None
    chart_reference: dict = Field(default_factory=dict)
    education_recommended: bool = False
    process_improvement_recommended: bool = False
    medical_director_review_recommended: bool = False


class EscalateRequest(BaseModel):
    escalation_reason: str
    medical_director_id: str
    review_type: str = "qa_escalation"


class CloseQACaseRequest(BaseModel):
    closure_notes: str


@router.get("/qa-cases")
async def list_qa_cases(
    status_filter: str | None = Query(None, alias="status"),
    priority: str | None = None,
    assigned_to: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List QA cases for the tenant (RBAC: QA roles)."""
    _require_any_role(current_user, *_QA_ROLES)
    query = select(QACaseRecord).where(
        QACaseRecord.tenant_id == str(current_user.tenant_id),
        QACaseRecord.deleted_at == None,  # noqa: E711
    )
    if status_filter:
        query = query.where(QACaseRecord.status == status_filter)
    if priority:
        query = query.where(QACaseRecord.priority == priority)
    if assigned_to:
        query = query.where(QACaseRecord.assigned_to == assigned_to)
    query = query.order_by(QACaseRecord.created_at.desc()).offset(offset).limit(limit)
    result = await session.execute(query)
    return [_model_to_dict(c) for c in result.scalars().all()]


@router.post("/qa-cases", status_code=201)
async def create_qa_case(
    payload: CreateQACaseRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Create a QA case manually."""
    _require_any_role(current_user, *_QA_ROLES)
    case = await QualityService.create_qa_case(
        session,
        tenant_id=str(current_user.tenant_id),
        source_chart_id=payload.source_chart_id,
        trigger_key=payload.trigger_key,
        trigger_type=payload.trigger_type,
        priority=payload.priority,
        created_by=str(current_user.user_id),
        created_by_role=_user_primary_role(current_user),
        agency_id=payload.agency_id,
        due_date=payload.due_date,
    )
    await session.commit()
    return _model_to_dict(case)


@router.get("/qa-cases/{case_id}")
async def get_qa_case(
    case_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Get full QA case detail."""
    _require_any_role(current_user, *_QA_ROLES)
    result = await session.execute(
        select(QACaseRecord).where(
            QACaseRecord.id == case_id,
            QACaseRecord.tenant_id == str(current_user.tenant_id),
        )
    )
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="QA case not found")

    # Load related scores and findings
    scores_result = await session.execute(
        select(QAScore).where(QAScore.qa_case_id == case_id, QAScore.tenant_id == str(current_user.tenant_id))
    )
    findings_result = await session.execute(
        select(QAReviewFinding).where(
            QAReviewFinding.qa_case_id == case_id,
            QAReviewFinding.tenant_id == str(current_user.tenant_id),
        )
    )
    return {
        **_model_to_dict(case),
        "scores": [_model_to_dict(s) for s in scores_result.scalars().all()],
        "findings": [_model_to_dict(f) for f in findings_result.scalars().all()],
    }


@router.patch("/qa-cases/{case_id}/assign")
async def assign_qa_case(
    case_id: str,
    payload: AssignQACaseRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Assign a QA case to a reviewer."""
    _require_any_role(current_user, *_QA_ROLES - {"qa_reviewer"}, "qa_reviewer")
    case = await QualityService.assign_qa_case(
        session,
        tenant_id=str(current_user.tenant_id),
        qa_case_id=case_id,
        reviewer_id=payload.reviewer_id,
        assigned_by=str(current_user.user_id),
        assigned_by_role=_user_primary_role(current_user),
        due_date=payload.due_date,
    )
    return _model_to_dict(case)


@router.post("/qa-cases/{case_id}/scores", status_code=201)
async def submit_qa_score(
    case_id: str,
    payload: SubmitQAScoreRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Submit a QA score for a case."""
    _require_any_role(current_user, *_QA_ROLES)
    score = await QualityService.submit_qa_score(
        session,
        tenant_id=str(current_user.tenant_id),
        qa_case_id=case_id,
        reviewer_id=str(current_user.user_id),
        reviewer_role=_user_primary_role(current_user),
        **payload.model_dump(),
    )
    return _model_to_dict(score)


@router.post("/qa-cases/{case_id}/findings", status_code=201)
async def add_qa_finding(
    case_id: str,
    payload: AddFindingRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Add a finding to a QA case."""
    _require_any_role(current_user, *_QA_ROLES)
    finding = await QualityService.add_qa_finding(
        session,
        tenant_id=str(current_user.tenant_id),
        qa_case_id=case_id,
        reviewer_id=str(current_user.user_id),
        reviewer_role=_user_primary_role(current_user),
        **payload.model_dump(),
    )
    return _model_to_dict(finding)


@router.post("/qa-cases/{case_id}/escalate", status_code=201)
async def escalate_qa_case(
    case_id: str,
    payload: EscalateRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Escalate a QA case to the medical director."""
    _require_any_role(current_user, *_QA_ROLES)
    review = await QualityService.escalate_to_medical_director(
        session,
        tenant_id=str(current_user.tenant_id),
        qa_case_id=case_id,
        escalated_by=str(current_user.user_id),
        escalated_by_role=_user_primary_role(current_user),
        escalation_reason=payload.escalation_reason,
        medical_director_id=payload.medical_director_id,
        review_type=payload.review_type,
    )
    return _model_to_dict(review)


@router.post("/qa-cases/{case_id}/close")
async def close_qa_case(
    case_id: str,
    payload: CloseQACaseRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Close a QA case."""
    _require_any_role(current_user, *_QA_ROLES)
    try:
        case = await QualityService.close_qa_case(
            session,
            tenant_id=str(current_user.tenant_id),
            qa_case_id=case_id,
            closed_by=str(current_user.user_id),
            closed_by_role=_user_primary_role(current_user),
            closure_notes=payload.closure_notes,
        )
    except QAWorkflowError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _model_to_dict(case)


@router.get("/qa-cases/{case_id}/audit")
async def get_qa_case_audit(
    case_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Get audit trail for a QA case."""
    _require_any_role(current_user, *_QA_ROLES)
    result = await session.execute(
        select(QualityAuditEvent).where(
            QualityAuditEvent.tenant_id == str(current_user.tenant_id),
            QualityAuditEvent.reference_id == case_id,
        ).order_by(QualityAuditEvent.occurred_at.desc())
    )
    return [_model_to_dict(e) for e in result.scalars().all()]


# ---------------------------------------------------------------------------
# PEER REVIEW
# ---------------------------------------------------------------------------

class AssignPeerReviewRequest(BaseModel):
    qa_case_id: str
    reviewer_id: str
    chart_provider_id: str
    crew_member_ids: list[str] = Field(default_factory=list)
    is_blind: bool = False
    due_date: datetime | None = None


class CompletePeerReviewRequest(BaseModel):
    strengths_notes: str | None = None
    improvement_notes: str | None = None
    education_recommendation: str | None = None
    process_improvement_suggestion: str | None = None
    exemplary_care_flag: bool = False
    reviewer_signature: str | None = None


@router.get("/peer-reviews")
async def list_peer_reviews(
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List peer reviews. Peer reviewers only see their own assigned reviews."""
    _require_any_role(current_user, "peer_reviewer", *_QA_ROLES)
    query = select(PeerReview).where(
        PeerReview.tenant_id == str(current_user.tenant_id),
    )
    # Peer reviewers can only see their own assigned reviews
    if "peer_reviewer" in current_user.roles and not any(r in _QA_ROLES for r in current_user.roles):
        query = query.where(PeerReview.reviewer_id == str(current_user.user_id))
    result = await session.execute(query.order_by(PeerReview.created_at.desc()))
    return [_model_to_dict(r) for r in result.scalars().all()]


@router.post("/peer-reviews", status_code=201)
async def assign_peer_review(
    payload: AssignPeerReviewRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Assign a peer review."""
    _require_any_role(current_user, *_QA_ROLES)
    try:
        review = await QualityService.assign_peer_review(
            session,
            tenant_id=str(current_user.tenant_id),
            qa_case_id=payload.qa_case_id,
            reviewer_id=payload.reviewer_id,
            assignor_id=str(current_user.user_id),
            assignor_role=_user_primary_role(current_user),
            chart_provider_id=payload.chart_provider_id,
            crew_member_ids=payload.crew_member_ids,
            is_blind=payload.is_blind,
            due_date=payload.due_date,
        )
    except ConflictOfInterestError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _model_to_dict(review)


@router.get("/peer-reviews/{review_id}")
async def get_peer_review(
    review_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Get peer review. Reviewers can only access their own assigned review."""
    _require_any_role(current_user, "peer_reviewer", *_QA_ROLES)
    result = await session.execute(
        select(PeerReview).where(
            PeerReview.id == review_id,
            PeerReview.tenant_id == str(current_user.tenant_id),
        )
    )
    review = result.scalar_one_or_none()
    if not review:
        raise HTTPException(status_code=404, detail="Peer review not found")

    # Peer reviewers can only see their own
    if "peer_reviewer" in current_user.roles and not any(r in _QA_ROLES for r in current_user.roles):
        if review.reviewer_id != str(current_user.user_id):
            raise HTTPException(status_code=403, detail="Access denied. Not your assigned review.")

    return _model_to_dict(review)


@router.patch("/peer-reviews/{review_id}/complete")
async def complete_peer_review(
    review_id: str,
    payload: CompletePeerReviewRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Complete a peer review."""
    _require_any_role(current_user, "peer_reviewer", *_QA_ROLES)
    try:
        review = await QualityService.complete_peer_review(
            session,
            tenant_id=str(current_user.tenant_id),
            peer_review_id=review_id,
            reviewer_id=str(current_user.user_id),
            reviewer_role=_user_primary_role(current_user),
            **payload.model_dump(),
        )
    except QAWorkflowError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _model_to_dict(review)


# ---------------------------------------------------------------------------
# MEDICAL DIRECTOR REVIEWS
# ---------------------------------------------------------------------------

class AddMDNoteRequest(BaseModel):
    note_type: str = "finding"
    note_text: str
    recommendation: str | None = None
    finding_type: str | None = None


class CompleteMDReviewRequest(BaseModel):
    finding_classification: str | None = None
    protocol_deviation_identified: bool = False
    exemplary_care_identified: bool = False
    education_recommended: bool = False
    protocol_revision_recommended: bool = False
    agency_leadership_flag: bool = False


class RequestClarificationRequest(BaseModel):
    clarification_from: str
    clarification_notes: str


@router.get("/md-reviews")
async def list_md_reviews(
    status_filter: str | None = Query(None, alias="status"),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List medical director reviews."""
    _require_any_role(current_user, *_MD_ROLES, *_ADMIN_ROLES)
    query = select(MedicalDirectorReview).where(
        MedicalDirectorReview.tenant_id == str(current_user.tenant_id),
    )
    if status_filter:
        query = query.where(MedicalDirectorReview.status == status_filter)
    # MD only sees their assigned reviews
    if _MD_ROLES.intersection(current_user.roles) and not _ADMIN_ROLES.intersection(current_user.roles):
        query = query.where(MedicalDirectorReview.medical_director_id == str(current_user.user_id))
    result = await session.execute(query.order_by(MedicalDirectorReview.created_at.desc()))
    return [_model_to_dict(r) for r in result.scalars().all()]


@router.get("/md-reviews/{review_id}")
async def get_md_review(
    review_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Get a medical director review with its notes."""
    _require_any_role(current_user, *_MD_ROLES, *_ADMIN_ROLES)
    result = await session.execute(
        select(MedicalDirectorReview).where(
            MedicalDirectorReview.id == review_id,
            MedicalDirectorReview.tenant_id == str(current_user.tenant_id),
        )
    )
    review = result.scalar_one_or_none()
    if not review:
        raise HTTPException(status_code=404, detail="MD review not found")

    notes_result = await session.execute(
        select(MedicalDirectorNote).where(
            MedicalDirectorNote.medical_director_review_id == review_id,
            MedicalDirectorNote.tenant_id == str(current_user.tenant_id),
        ).order_by(MedicalDirectorNote.created_at.asc())
    )
    return {
        **_model_to_dict(review),
        "notes": [_model_to_dict(n) for n in notes_result.scalars().all()],
    }


@router.post("/md-reviews/{review_id}/notes", status_code=201)
async def add_md_note(
    review_id: str,
    payload: AddMDNoteRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Add a protected medical director note. MD roles only."""
    _require_any_role(current_user, *_MD_ROLES)
    try:
        note = await QualityService.add_medical_director_note(
            session,
            tenant_id=str(current_user.tenant_id),
            medical_director_review_id=review_id,
            author_id=str(current_user.user_id),
            author_role=_user_primary_role(current_user),
            **payload.model_dump(),
        )
    except QAWorkflowError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _model_to_dict(note)


@router.patch("/md-reviews/{review_id}/complete")
async def complete_md_review(
    review_id: str,
    payload: CompleteMDReviewRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Complete a medical director review."""
    _require_any_role(current_user, *_MD_ROLES)
    try:
        review = await QualityService.complete_medical_director_review(
            session,
            tenant_id=str(current_user.tenant_id),
            review_id=review_id,
            md_id=str(current_user.user_id),
            md_role=_user_primary_role(current_user),
            **payload.model_dump(),
        )
    except QAWorkflowError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _model_to_dict(review)


@router.post("/md-reviews/{review_id}/request-clarification")
async def request_clarification(
    review_id: str,
    payload: RequestClarificationRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Request clarification from a provider."""
    _require_any_role(current_user, *_MD_ROLES)
    try:
        review = await QualityService.request_md_clarification(
            session,
            tenant_id=str(current_user.tenant_id),
            review_id=review_id,
            md_id=str(current_user.user_id),
            md_role=_user_primary_role(current_user),
            clarification_from=payload.clarification_from,
            clarification_notes=payload.clarification_notes,
        )
    except QAWorkflowError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _model_to_dict(review)


# ---------------------------------------------------------------------------
# PROTOCOLS
# ---------------------------------------------------------------------------

class CreateProtocolRequest(BaseModel):
    protocol_code: str
    protocol_name: str
    protocol_category: str
    acknowledgment_required: bool = False
    linked_qa_trigger_keys: list[str] = Field(default_factory=list)


class CreateProtocolVersionRequest(BaseModel):
    version_number: str
    effective_date: datetime
    expiration_date: datetime | None = None
    content_text: str | None = None
    content_url: str | None = None
    scope_applicability: dict = Field(default_factory=dict)


@router.get("/protocols")
async def list_protocols(
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List protocols for the tenant."""
    _require_any_role(current_user, *_SENIOR_ROLES)
    result = await session.execute(
        select(ProtocolDocument).where(
            ProtocolDocument.tenant_id == str(current_user.tenant_id),
            ProtocolDocument.deleted_at == None,  # noqa: E711
        ).order_by(ProtocolDocument.created_at.desc())
    )
    return [_model_to_dict(p) for p in result.scalars().all()]


@router.post("/protocols", status_code=201)
async def create_protocol(
    payload: CreateProtocolRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Create a new protocol document."""
    _require_any_role(current_user, *_MD_ROLES, *_ADMIN_ROLES)
    import json as _json
    now = _now()
    proto = ProtocolDocument(
        id=_new_id(),
        tenant_id=str(current_user.tenant_id),
        protocol_code=payload.protocol_code,
        protocol_name=payload.protocol_name,
        protocol_category=payload.protocol_category,
        status="draft",
        acknowledgment_required=payload.acknowledgment_required,
        linked_qa_trigger_keys_json=_json.dumps(payload.linked_qa_trigger_keys),
        created_by=str(current_user.user_id),
        created_at=now,
        updated_by=str(current_user.user_id),
        updated_at=now,
    )
    session.add(proto)
    await QualityService.emit_audit_event(
        session,
        tenant_id=str(current_user.tenant_id),
        actor_id=str(current_user.user_id),
        actor_role=_user_primary_role(current_user),
        event_type="protocol_created",
        reference_type="protocol",
        reference_id=proto.id,
        metadata={"protocol_code": payload.protocol_code},
    )
    await session.commit()
    await session.refresh(proto)
    return _model_to_dict(proto)


@router.get("/protocols/{protocol_id}")
async def get_protocol(
    protocol_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Get protocol with its versions."""
    _require_any_role(current_user, *_SENIOR_ROLES)
    result = await session.execute(
        select(ProtocolDocument).where(
            ProtocolDocument.id == protocol_id,
            ProtocolDocument.tenant_id == str(current_user.tenant_id),
        )
    )
    proto = result.scalar_one_or_none()
    if not proto:
        raise HTTPException(status_code=404, detail="Protocol not found")

    versions_result = await session.execute(
        select(ProtocolVersion).where(
            ProtocolVersion.protocol_id == protocol_id,
            ProtocolVersion.tenant_id == str(current_user.tenant_id),
        ).order_by(ProtocolVersion.created_at.desc())
    )
    return {
        **_model_to_dict(proto),
        "versions": [_model_to_dict(v) for v in versions_result.scalars().all()],
    }


@router.post("/protocols/{protocol_id}/versions", status_code=201)
async def create_protocol_version(
    protocol_id: str,
    payload: CreateProtocolVersionRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Create a new protocol version."""
    _require_any_role(current_user, *_MD_ROLES, *_ADMIN_ROLES)
    import json as _json
    now = _now()
    version = ProtocolVersion(
        id=_new_id(),
        tenant_id=str(current_user.tenant_id),
        protocol_id=protocol_id,
        version_number=payload.version_number,
        effective_date=payload.effective_date,
        expiration_date=payload.expiration_date,
        content_text=payload.content_text,
        content_url=payload.content_url,
        status="draft",
        scope_applicability_json=_json.dumps(payload.scope_applicability),
        created_by=str(current_user.user_id),
        created_at=now,
        updated_by=str(current_user.user_id),
        updated_at=now,
    )
    session.add(version)
    await session.commit()
    await session.refresh(version)
    return _model_to_dict(version)


@router.post("/protocols/{protocol_id}/versions/{version_id}/publish")
async def publish_protocol_version(
    protocol_id: str,
    version_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Publish a protocol version. MD approval required."""
    _require_any_role(current_user, *_MD_ROLES, *_ADMIN_ROLES)
    try:
        version = await QualityService.publish_protocol_version(
            session,
            tenant_id=str(current_user.tenant_id),
            protocol_id=protocol_id,
            version_id=version_id,
            approved_by=str(current_user.user_id),
            approved_by_role=_user_primary_role(current_user),
        )
    except QAWorkflowError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _model_to_dict(version)


@router.post("/protocols/{protocol_id}/versions/{version_id}/acknowledge")
async def acknowledge_protocol_version(
    protocol_id: str,
    version_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Provider acknowledges a protocol version."""
    try:
        ack = await QualityService.record_protocol_acknowledgment(
            session,
            tenant_id=str(current_user.tenant_id),
            protocol_version_id=version_id,
            provider_id=str(current_user.user_id),
        )
    except QAWorkflowError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _model_to_dict(ack)


@router.get("/protocols/{protocol_id}/acknowledgments")
async def list_protocol_acknowledgments(
    protocol_id: str,
    version_id: str | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List acknowledgments for a protocol version."""
    _require_any_role(current_user, *_MD_ROLES, *_ADMIN_ROLES)
    query = select(ProtocolAcknowledgment).where(
        ProtocolAcknowledgment.tenant_id == str(current_user.tenant_id),
    )
    if version_id:
        query = query.where(ProtocolAcknowledgment.protocol_version_id == version_id)
    result = await session.execute(query)
    return [_model_to_dict(a) for a in result.scalars().all()]


# ---------------------------------------------------------------------------
# STANDING ORDERS
# ---------------------------------------------------------------------------

@router.get("/standing-orders")
async def list_standing_orders(
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List standing orders for the tenant."""
    _require_any_role(current_user, *_SENIOR_ROLES)
    result = await session.execute(
        select(StandingOrder).where(
            StandingOrder.tenant_id == str(current_user.tenant_id),
            StandingOrder.deleted_at == None,  # noqa: E711
        ).order_by(StandingOrder.created_at.desc())
    )
    return [_model_to_dict(s) for s in result.scalars().all()]


@router.post("/standing-orders", status_code=201)
async def create_standing_order(
    payload: dict,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Create a standing order."""
    _require_any_role(current_user, *_MD_ROLES, *_ADMIN_ROLES)
    now = _now()
    order = StandingOrder(
        id=_new_id(),
        tenant_id=str(current_user.tenant_id),
        order_code=payload.get("order_code", ""),
        order_name=payload.get("order_name", ""),
        order_type=payload.get("order_type", ""),
        status="draft",
        acknowledgment_required=payload.get("acknowledgment_required", False),
        created_by=str(current_user.user_id),
        created_at=now,
        updated_by=str(current_user.user_id),
        updated_at=now,
    )
    session.add(order)
    await QualityService.emit_audit_event(
        session,
        tenant_id=str(current_user.tenant_id),
        actor_id=str(current_user.user_id),
        actor_role=_user_primary_role(current_user),
        event_type="standing_order_created",
        reference_type="standing_order",
        reference_id=order.id,
        metadata={"order_code": order.order_code},
    )
    await session.commit()
    await session.refresh(order)
    return _model_to_dict(order)


@router.get("/standing-orders/{order_id}")
async def get_standing_order(
    order_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Get standing order with versions."""
    _require_any_role(current_user, *_SENIOR_ROLES)
    result = await session.execute(
        select(StandingOrder).where(
            StandingOrder.id == order_id,
            StandingOrder.tenant_id == str(current_user.tenant_id),
        )
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Standing order not found")
    versions_result = await session.execute(
        select(StandingOrderVersion).where(
            StandingOrderVersion.standing_order_id == order_id,
            StandingOrderVersion.tenant_id == str(current_user.tenant_id),
        ).order_by(StandingOrderVersion.created_at.desc())
    )
    return {
        **_model_to_dict(order),
        "versions": [_model_to_dict(v) for v in versions_result.scalars().all()],
    }


# ---------------------------------------------------------------------------
# QI INITIATIVES
# ---------------------------------------------------------------------------

class CreateQIInitiativeRequest(BaseModel):
    initiative_title: str
    category: str
    source_trend_description: str
    intervention_plan: str
    owner_id: str
    start_date: datetime | None = None
    baseline_metric_value: float | None = None
    baseline_metric_label: str | None = None
    target_metric_value: float | None = None
    target_metric_label: str | None = None
    target_completion_date: datetime | None = None
    stakeholder_ids: list[str] = Field(default_factory=list)


class AdvanceQIStatusRequest(BaseModel):
    new_status: str
    notes: str | None = None
    outcome_summary: str | None = None
    current_metric_value: float | None = None


class RecordQIMetricRequest(BaseModel):
    metric_key: str
    metric_value: float
    metric_label: str
    measurement_period: str
    notes: str | None = None


class AddQIActionRequest(BaseModel):
    action_title: str
    action_description: str
    assigned_to: str
    due_date: datetime | None = None


@router.get("/qi/initiatives")
async def list_qi_initiatives(
    status_filter: str | None = Query(None, alias="status"),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List QI initiatives."""
    _require_any_role(current_user, *_QI_ROLES)
    query = select(QIInitiative).where(QIInitiative.tenant_id == str(current_user.tenant_id))
    if status_filter:
        query = query.where(QIInitiative.status == status_filter)
    result = await session.execute(query.order_by(QIInitiative.created_at.desc()))
    return [_model_to_dict(i) for i in result.scalars().all()]


@router.post("/qi/initiatives", status_code=201)
async def create_qi_initiative(
    payload: CreateQIInitiativeRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Create a QI initiative."""
    _require_any_role(current_user, *_QI_ROLES)
    initiative = await QualityService.create_qi_initiative(
        session,
        tenant_id=str(current_user.tenant_id),
        created_by=str(current_user.user_id),
        created_by_role=_user_primary_role(current_user),
        **payload.model_dump(),
    )
    return _model_to_dict(initiative)


@router.get("/qi/initiatives/{initiative_id}")
async def get_qi_initiative(
    initiative_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Get QI initiative with metrics and action items."""
    _require_any_role(current_user, *_QI_ROLES)
    result = await session.execute(
        select(QIInitiative).where(
            QIInitiative.id == initiative_id,
            QIInitiative.tenant_id == str(current_user.tenant_id),
        )
    )
    initiative = result.scalar_one_or_none()
    if not initiative:
        raise HTTPException(status_code=404, detail="QI initiative not found")

    metrics_result = await session.execute(
        select(QIInitiativeMetric).where(
            QIInitiativeMetric.initiative_id == initiative_id,
            QIInitiativeMetric.tenant_id == str(current_user.tenant_id),
        ).order_by(QIInitiativeMetric.recorded_at.asc())
    )
    actions_result = await session.execute(
        select(QIActionItem).where(
            QIActionItem.initiative_id == initiative_id,
            QIActionItem.tenant_id == str(current_user.tenant_id),
        ).order_by(QIActionItem.created_at.asc())
    )
    return {
        **_model_to_dict(initiative),
        "metrics": [_model_to_dict(m) for m in metrics_result.scalars().all()],
        "action_items": [_model_to_dict(a) for a in actions_result.scalars().all()],
    }


@router.patch("/qi/initiatives/{initiative_id}/status")
async def advance_qi_initiative_status(
    initiative_id: str,
    payload: AdvanceQIStatusRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Advance QI initiative status."""
    _require_any_role(current_user, *_QI_ROLES)
    try:
        initiative = await QualityService.advance_qi_initiative_status(
            session,
            tenant_id=str(current_user.tenant_id),
            initiative_id=initiative_id,
            actor_id=str(current_user.user_id),
            actor_role=_user_primary_role(current_user),
            **payload.model_dump(),
        )
    except QAWorkflowError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _model_to_dict(initiative)


@router.post("/qi/initiatives/{initiative_id}/metrics", status_code=201)
async def record_qi_metric(
    initiative_id: str,
    payload: RecordQIMetricRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Record a QI metric measurement."""
    _require_any_role(current_user, *_QI_ROLES)
    metric = await QualityService.record_qi_metric(
        session,
        tenant_id=str(current_user.tenant_id),
        initiative_id=initiative_id,
        recorded_by=str(current_user.user_id),
        **payload.model_dump(),
    )
    return _model_to_dict(metric)


@router.post("/qi/initiatives/{initiative_id}/actions", status_code=201)
async def add_qi_action_item(
    initiative_id: str,
    payload: AddQIActionRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Add an action item to a QI initiative."""
    _require_any_role(current_user, *_QI_ROLES)
    now = _now()
    action = QIActionItem(
        id=_new_id(),
        tenant_id=str(current_user.tenant_id),
        initiative_id=initiative_id,
        action_title=payload.action_title,
        action_description=payload.action_description,
        assigned_to=payload.assigned_to,
        due_date=payload.due_date,
        status="open",
        created_by=str(current_user.user_id),
        created_at=now,
        updated_by=str(current_user.user_id),
        updated_at=now,
    )
    session.add(action)
    await session.commit()
    await session.refresh(action)
    return _model_to_dict(action)


@router.patch("/qi/actions/{action_id}")
async def update_qi_action_item(
    action_id: str,
    payload: dict,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Update a QI action item status."""
    _require_any_role(current_user, *_QI_ROLES)
    result = await session.execute(
        select(QIActionItem).where(
            QIActionItem.id == action_id,
            QIActionItem.tenant_id == str(current_user.tenant_id),
        )
    )
    action = result.scalar_one_or_none()
    if not action:
        raise HTTPException(status_code=404, detail="Action item not found")
    now = _now()
    for field in ("status", "completion_notes"):
        if field in payload:
            setattr(action, field, payload[field])
    if payload.get("status") == "completed":
        action.completed_at = now
    action.updated_by = str(current_user.user_id)
    action.updated_at = now
    await session.commit()
    await session.refresh(action)
    return _model_to_dict(action)


# ---------------------------------------------------------------------------
# QI COMMITTEE
# ---------------------------------------------------------------------------

@router.get("/qi/committee-reviews")
async def list_committee_reviews(
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List QI committee reviews."""
    _require_any_role(current_user, *_QI_ROLES, *_MD_ROLES, *_ADMIN_ROLES)
    result = await session.execute(
        select(QICommitteeReview).where(
            QICommitteeReview.tenant_id == str(current_user.tenant_id),
        ).order_by(QICommitteeReview.meeting_date.desc())
    )
    return [_model_to_dict(r) for r in result.scalars().all()]


@router.post("/qi/committee-reviews", status_code=201)
async def create_committee_review(
    payload: dict,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Create a QI committee review."""
    _require_any_role(current_user, *_QI_ROLES, *_ADMIN_ROLES)
    import json as _json
    now = _now()
    review = QICommitteeReview(
        id=_new_id(),
        tenant_id=str(current_user.tenant_id),
        meeting_date=payload.get("meeting_date", now.isoformat()),
        chair_id=payload.get("chair_id", str(current_user.user_id)),
        attendee_ids_json=_json.dumps(payload.get("attendee_ids", [])),
        agenda_json=_json.dumps(payload.get("agenda", [])),
        status="scheduled",
        created_by=str(current_user.user_id),
        created_at=now,
        updated_by=str(current_user.user_id),
        updated_at=now,
    )
    session.add(review)
    await session.commit()
    await session.refresh(review)
    return _model_to_dict(review)


# ---------------------------------------------------------------------------
# EDUCATION FOLLOW-UP
# ---------------------------------------------------------------------------

class AssignEducationRequest(BaseModel):
    provider_id: str
    education_type: str = "remedial"
    education_title: str
    education_description: str | None = None
    education_resource_url: str | None = None
    due_date: datetime | None = None
    qa_case_id: str | None = None
    medical_director_review_id: str | None = None
    qi_initiative_id: str | None = None


@router.get("/education")
async def list_education(
    provider_id: str | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List education assignments. Providers only see their own."""
    query = select(EducationFollowUp).where(
        EducationFollowUp.tenant_id == str(current_user.tenant_id),
    )
    if "provider" in current_user.roles and not any(r in _SENIOR_ROLES for r in current_user.roles):
        query = query.where(EducationFollowUp.provider_id == str(current_user.user_id))
    elif provider_id:
        query = query.where(EducationFollowUp.provider_id == provider_id)
    result = await session.execute(query.order_by(EducationFollowUp.created_at.desc()))
    return [_model_to_dict(e) for e in result.scalars().all()]


@router.post("/education", status_code=201)
async def assign_education(
    payload: AssignEducationRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Assign education to a provider."""
    _require_any_role(current_user, *_SENIOR_ROLES)
    edu = await QualityService.assign_education(
        session,
        tenant_id=str(current_user.tenant_id),
        assigned_by=str(current_user.user_id),
        assigned_by_role=_user_primary_role(current_user),
        **payload.model_dump(),
    )
    return _model_to_dict(edu)


@router.get("/education/{education_id}")
async def get_education(
    education_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Get education detail. Providers can only access their own."""
    result = await session.execute(
        select(EducationFollowUp).where(
            EducationFollowUp.id == education_id,
            EducationFollowUp.tenant_id == str(current_user.tenant_id),
        )
    )
    edu = result.scalar_one_or_none()
    if not edu:
        raise HTTPException(status_code=404, detail="Education not found")

    if "provider" in current_user.roles and not any(r in _SENIOR_ROLES for r in current_user.roles):
        if edu.provider_id != str(current_user.user_id):
            raise HTTPException(status_code=403, detail="Access denied.")

    return _model_to_dict(edu)


@router.patch("/education/{education_id}/complete")
async def complete_education(
    education_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Provider marks education as completed."""
    try:
        edu = await QualityService.complete_education(
            session,
            tenant_id=str(current_user.tenant_id),
            education_id=education_id,
            provider_id=str(current_user.user_id),
        )
    except QAWorkflowError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _model_to_dict(edu)


# ---------------------------------------------------------------------------
# PROVIDER FEEDBACK
# ---------------------------------------------------------------------------

class SendFeedbackRequest(BaseModel):
    provider_id: str
    feedback_type: str = "informational"
    subject: str
    message_text: str
    qa_case_id: str | None = None
    medical_director_review_id: str | None = None


class AcknowledgeFeedbackRequest(BaseModel):
    provider_response: str | None = None


@router.get("/feedback")
async def list_provider_feedback(
    provider_id: str | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List provider feedback. Providers only see their own."""
    query = select(ProviderFeedback).where(
        ProviderFeedback.tenant_id == str(current_user.tenant_id),
    )
    if "provider" in current_user.roles and not any(r in _SENIOR_ROLES for r in current_user.roles):
        query = query.where(ProviderFeedback.provider_id == str(current_user.user_id))
    elif provider_id:
        query = query.where(ProviderFeedback.provider_id == provider_id)
    result = await session.execute(query.order_by(ProviderFeedback.created_at.desc()))
    return [_model_to_dict(f) for f in result.scalars().all()]


@router.post("/feedback", status_code=201)
async def send_provider_feedback(
    payload: SendFeedbackRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Send feedback to a provider."""
    _require_any_role(current_user, *_SENIOR_ROLES)
    feedback = await QualityService.send_provider_feedback(
        session,
        tenant_id=str(current_user.tenant_id),
        sent_by=str(current_user.user_id),
        sent_by_role=_user_primary_role(current_user),
        **payload.model_dump(),
    )
    return _model_to_dict(feedback)


@router.get("/feedback/{feedback_id}")
async def get_feedback(
    feedback_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Get feedback detail. Providers can only access their own."""
    result = await session.execute(
        select(ProviderFeedback).where(
            ProviderFeedback.id == feedback_id,
            ProviderFeedback.tenant_id == str(current_user.tenant_id),
        )
    )
    feedback = result.scalar_one_or_none()
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found")
    if "provider" in current_user.roles and not any(r in _SENIOR_ROLES for r in current_user.roles):
        if feedback.provider_id != str(current_user.user_id):
            raise HTTPException(status_code=403, detail="Access denied.")
    return _model_to_dict(feedback)


@router.patch("/feedback/{feedback_id}/acknowledge")
async def acknowledge_feedback(
    feedback_id: str,
    payload: AcknowledgeFeedbackRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Provider acknowledges feedback."""
    try:
        feedback = await QualityService.acknowledge_provider_feedback(
            session,
            tenant_id=str(current_user.tenant_id),
            feedback_id=feedback_id,
            provider_id=str(current_user.user_id),
            provider_response=payload.provider_response,
        )
    except QAWorkflowError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _model_to_dict(feedback)


# ---------------------------------------------------------------------------
# CLINICAL VARIANCES
# ---------------------------------------------------------------------------

@router.get("/variances")
async def list_variances(
    variance_type: str | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List clinical variances."""
    _require_any_role(current_user, *_QA_ROLES, *_MD_ROLES)
    query = select(ClinicalVariance).where(
        ClinicalVariance.tenant_id == str(current_user.tenant_id),
    )
    if variance_type:
        query = query.where(ClinicalVariance.variance_type == variance_type)
    result = await session.execute(query.order_by(ClinicalVariance.created_at.desc()))
    return [_model_to_dict(v) for v in result.scalars().all()]


@router.post("/variances", status_code=201)
async def create_variance(
    payload: dict,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Create a clinical variance."""
    _require_any_role(current_user, *_QA_ROLES, *_MD_ROLES)
    now = _now()
    variance = ClinicalVariance(
        id=_new_id(),
        tenant_id=str(current_user.tenant_id),
        source_chart_id=payload.get("source_chart_id", ""),
        provider_id=payload.get("provider_id", str(current_user.user_id)),
        unit_id=payload.get("unit_id"),
        qa_case_id=payload.get("qa_case_id"),
        incident_datetime=payload.get("incident_datetime", now),
        variance_type=payload.get("variance_type", "protocol"),
        severity=payload.get("severity", "minor"),
        clinical_context=payload.get("clinical_context", ""),
        closure_status="open",
        created_by=str(current_user.user_id),
        created_at=now,
        updated_by=str(current_user.user_id),
        updated_at=now,
    )
    session.add(variance)
    await QualityService.emit_audit_event(
        session,
        tenant_id=str(current_user.tenant_id),
        actor_id=str(current_user.user_id),
        actor_role=_user_primary_role(current_user),
        event_type="clinical_variance_created",
        reference_type="clinical_variance",
        reference_id=variance.id,
        source_chart_id=variance.source_chart_id,
        metadata={"variance_type": variance.variance_type},
    )
    await session.commit()
    await session.refresh(variance)
    return _model_to_dict(variance)


@router.get("/variances/{variance_id}")
async def get_variance(
    variance_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Get clinical variance detail."""
    _require_any_role(current_user, *_QA_ROLES, *_MD_ROLES)
    result = await session.execute(
        select(ClinicalVariance).where(
            ClinicalVariance.id == variance_id,
            ClinicalVariance.tenant_id == str(current_user.tenant_id),
        )
    )
    variance = result.scalar_one_or_none()
    if not variance:
        raise HTTPException(status_code=404, detail="Variance not found")
    return _model_to_dict(variance)


# ---------------------------------------------------------------------------
# DASHBOARDS
# ---------------------------------------------------------------------------

@router.get("/dashboards/medical-director")
async def get_md_dashboard(
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Medical Director dashboard — real DB data only."""
    _require_any_role(current_user, *_MD_ROLES, *_ADMIN_ROLES)
    return await QualityService.get_md_dashboard_data(session, tenant_id=str(current_user.tenant_id))


@router.get("/dashboards/qa")
async def get_qa_dashboard(
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """QA dashboard — real DB data only."""
    _require_any_role(current_user, *_QA_ROLES)
    return await QualityService.get_qa_dashboard_data(session, tenant_id=str(current_user.tenant_id))


@router.get("/dashboards/qi")
async def get_qi_dashboard(
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """QI dashboard — real DB data only."""
    _require_any_role(current_user, *_QI_ROLES, *_MD_ROLES, *_ADMIN_ROLES)
    return await QualityService.get_qi_dashboard_data(session, tenant_id=str(current_user.tenant_id))


@router.get("/dashboards/agency-leadership")
async def get_agency_leadership_dashboard(
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Agency leadership dashboard — aggregated quality health."""
    _require_any_role(current_user, *_ADMIN_ROLES, *_MD_ROLES)
    qa_data = await QualityService.get_qa_dashboard_data(session, tenant_id=str(current_user.tenant_id))
    qi_data = await QualityService.get_qi_dashboard_data(session, tenant_id=str(current_user.tenant_id))
    md_data = await QualityService.get_md_dashboard_data(session, tenant_id=str(current_user.tenant_id))
    return {
        "qa_summary": qa_data,
        "qi_summary": qi_data,
        "md_summary": md_data,
    }


@router.get("/dashboards/provider-feedback")
async def get_provider_feedback_dashboard(
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Provider personal feedback dashboard."""
    provider_id = str(current_user.user_id)
    feedback_result = await session.execute(
        select(ProviderFeedback).where(
            ProviderFeedback.tenant_id == str(current_user.tenant_id),
            ProviderFeedback.provider_id == provider_id,
        ).order_by(ProviderFeedback.created_at.desc()).limit(20)
    )
    education_result = await session.execute(
        select(EducationFollowUp).where(
            EducationFollowUp.tenant_id == str(current_user.tenant_id),
            EducationFollowUp.provider_id == provider_id,
            EducationFollowUp.status.in_(["assigned", "acknowledged", "in_progress"]),
        )
    )
    return {
        "recent_feedback": [_model_to_dict(f) for f in feedback_result.scalars().all()],
        "pending_education": [_model_to_dict(e) for e in education_result.scalars().all()],
    }


# ---------------------------------------------------------------------------
# REPORTS
# ---------------------------------------------------------------------------

@router.get("/reports/qa-summary")
async def qa_summary_report(
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """QA summary report generated from real data."""
    _require_any_role(current_user, *_QA_ROLES, *_MD_ROLES, *_ADMIN_ROLES)
    return await QualityService.get_qa_dashboard_data(session, tenant_id=str(current_user.tenant_id))


@router.get("/reports/qi-summary")
async def qi_summary_report(
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """QI summary report."""
    _require_any_role(current_user, *_QI_ROLES, *_MD_ROLES, *_ADMIN_ROLES)
    return await QualityService.get_qi_dashboard_data(session, tenant_id=str(current_user.tenant_id))


@router.get("/reports/md-summary")
async def md_summary_report(
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Medical Director summary report."""
    _require_any_role(current_user, *_MD_ROLES, *_ADMIN_ROLES)
    return await QualityService.get_md_dashboard_data(session, tenant_id=str(current_user.tenant_id))


@router.get("/reports/provider-scorecard/{provider_id}")
async def provider_scorecard_report(
    provider_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Provider scorecard report."""
    _require_any_role(current_user, *_SENIOR_ROLES)
    # Providers can only see their own scorecard
    if "provider" in current_user.roles and not any(r in _SENIOR_ROLES - {"provider"} for r in current_user.roles):
        if provider_id != str(current_user.user_id):
            raise HTTPException(status_code=403, detail="Access denied.")

    cases_result = await session.execute(
        select(QACaseRecord).where(
            QACaseRecord.tenant_id == str(current_user.tenant_id),
        )
    )
    # This would normally filter by provider but chart provider link is not stored on case directly
    # In a full implementation, link through chart data
    feedback_result = await session.execute(
        select(ProviderFeedback).where(
            ProviderFeedback.tenant_id == str(current_user.tenant_id),
            ProviderFeedback.provider_id == provider_id,
        )
    )
    edu_result = await session.execute(
        select(EducationFollowUp).where(
            EducationFollowUp.tenant_id == str(current_user.tenant_id),
            EducationFollowUp.provider_id == provider_id,
        )
    )
    feedbacks = list(feedback_result.scalars().all())
    edus = list(edu_result.scalars().all())
    completed_edu = [e for e in edus if e.status == "completed"]

    return {
        "provider_id": provider_id,
        "feedback_count": len(feedbacks),
        "commendations": len([f for f in feedbacks if f.feedback_type == "commendation"]),
        "education_assigned": len(edus),
        "education_completed": len(completed_edu),
        "education_completion_rate": round((len(completed_edu) / len(edus) * 100) if edus else 0, 1),
    }


# ---------------------------------------------------------------------------
# ACCREDITATION EVIDENCE
# ---------------------------------------------------------------------------

class GenerateAccreditationPackageRequest(BaseModel):
    package_name: str
    accreditation_type: str = "internal_audit"
    period_start: datetime
    period_end: datetime


@router.get("/accreditation")
async def list_accreditation_packages(
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List accreditation evidence packages."""
    _require_any_role(current_user, *_QI_ROLES, *_MD_ROLES, *_ADMIN_ROLES)
    result = await session.execute(
        select(AccreditationEvidencePackage).where(
            AccreditationEvidencePackage.tenant_id == str(current_user.tenant_id),
        ).order_by(AccreditationEvidencePackage.created_at.desc())
    )
    return [_model_to_dict(p) for p in result.scalars().all()]


@router.post("/accreditation", status_code=201)
async def generate_accreditation_package(
    payload: GenerateAccreditationPackageRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Generate an accreditation evidence package from real data."""
    _require_any_role(current_user, *_QI_ROLES, *_MD_ROLES, *_ADMIN_ROLES)
    package = await QualityService.generate_accreditation_package(
        session,
        tenant_id=str(current_user.tenant_id),
        generated_by=str(current_user.user_id),
        generated_by_role=_user_primary_role(current_user),
        **payload.model_dump(),
    )
    return _model_to_dict(package)


@router.get("/accreditation/{package_id}")
async def get_accreditation_package(
    package_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Get accreditation evidence package detail."""
    _require_any_role(current_user, *_QI_ROLES, *_MD_ROLES, *_ADMIN_ROLES)
    result = await session.execute(
        select(AccreditationEvidencePackage).where(
            AccreditationEvidencePackage.id == package_id,
            AccreditationEvidencePackage.tenant_id == str(current_user.tenant_id),
        )
    )
    package = result.scalar_one_or_none()
    if not package:
        raise HTTPException(status_code=404, detail="Accreditation package not found")
    return _model_to_dict(package)


# ---------------------------------------------------------------------------
# AUDIT TRAIL
# ---------------------------------------------------------------------------

@router.get("/audit")
async def list_audit_events(
    reference_type: str | None = None,
    reference_id: str | None = None,
    actor_id: str | None = None,
    event_type: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List quality audit events (tenant-scoped)."""
    _require_any_role(current_user, *_SENIOR_ROLES)
    query = select(QualityAuditEvent).where(
        QualityAuditEvent.tenant_id == str(current_user.tenant_id),
    )
    if reference_type:
        query = query.where(QualityAuditEvent.reference_type == reference_type)
    if reference_id:
        query = query.where(QualityAuditEvent.reference_id == reference_id)
    if actor_id:
        query = query.where(QualityAuditEvent.actor_id == actor_id)
    if event_type:
        query = query.where(QualityAuditEvent.event_type == event_type)
    query = query.order_by(QualityAuditEvent.occurred_at.desc()).offset(offset).limit(limit)
    result = await session.execute(query)
    return [_model_to_dict(e) for e in result.scalars().all()]


# ---------------------------------------------------------------------------
# TREND AGGREGATIONS
# ---------------------------------------------------------------------------

@router.get("/trends")
async def list_trend_aggregations(
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List QA trend aggregations."""
    _require_any_role(current_user, *_QI_ROLES, *_MD_ROLES, *_ADMIN_ROLES)
    from epcr_app.models_quality import QATrendAggregation
    result = await session.execute(
        select(QATrendAggregation).where(
            QATrendAggregation.tenant_id == str(current_user.tenant_id),
        ).order_by(QATrendAggregation.period.desc())
    )
    return [_model_to_dict(t) for t in result.scalars().all()]


@router.post("/trends/compute")
async def compute_trend_aggregation(
    payload: dict,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Trigger trend computation for a period."""
    _require_any_role(current_user, *_QI_ROLES, *_ADMIN_ROLES)
    trend = await QualityService.compute_qa_trend_aggregation(
        session,
        tenant_id=str(current_user.tenant_id),
        period=payload.get("period", _now().strftime("%Y-%m")),
        period_type=payload.get("period_type", "month"),
        computed_by=str(current_user.user_id),
    )
    return _model_to_dict(trend)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _model_to_dict(obj: Any) -> dict:
    """Convert a SQLAlchemy ORM model to a dict for JSON serialization."""
    if obj is None:
        return {}
    result = {}
    for col in obj.__table__.columns:
        val = getattr(obj, col.name)
        if hasattr(val, "isoformat"):
            val = val.isoformat()
        result[col.name] = val
    return result
