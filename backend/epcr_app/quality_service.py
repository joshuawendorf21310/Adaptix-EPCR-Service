"""Quality module service: Medical Director, QA, and QI business logic.

Architecture rules enforced here:
- Medical Director notes NEVER modify original ePCR chart data.
- QA findings NEVER modify original chart data.
- Peer review notes NEVER modify original chart data.
- Every state-changing operation creates a QualityAuditEvent.
- Peer reviewer must not be the chart provider or crew member.
- Dashboard data is always computed from real DB queries.
- AI suggestions include source references, confidence, and human review status.
- QA cases are never auto-closed by the system — only by authorized reviewers.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models_quality import (
    AccreditationEvidencePackage,
    ClinicalVariance,
    EducationFollowUp,
    MedicalDirectorNote,
    MedicalDirectorReview,
    PeerReview,
    PeerReviewAssignment,
    ProtocolAcknowledgment,
    ProtocolDocument,
    ProtocolVersion,
    ProviderAcknowledgment,
    ProviderFeedback,
    QACaseRecord,
    QAReviewFinding,
    QAScore,
    QATrendAggregation,
    QATriggerConfiguration,
    QIActionItem,
    QICommitteeReview,
    QIInitiative,
    QIInitiativeMetric,
    QualityAuditEvent,
    StandingOrder,
    StandingOrderVersion,
)

logger = logging.getLogger(__name__)


class ConflictOfInterestError(Exception):
    """Raised when a peer review assignment violates conflict-of-interest rules."""


class QAWorkflowError(Exception):
    """Raised when a QA workflow transition is invalid."""


def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


def _json_dumps(obj) -> str:
    return json.dumps(obj)


def _json_loads(s: str | None):
    if not s:
        return {}
    try:
        return json.loads(s)
    except Exception:
        return {}


class QualityService:
    """Service layer for the Medical Director, QA, and QI modules."""

    # =========================================================================
    # AUDIT EVENT EMISSION
    # =========================================================================

    @staticmethod
    async def emit_audit_event(
        db: AsyncSession,
        *,
        tenant_id: str,
        actor_id: str,
        actor_role: str,
        event_type: str,
        reference_type: str,
        reference_id: str,
        source_chart_id: str | None = None,
        metadata: dict | None = None,
        correlation_id: str | None = None,
    ) -> QualityAuditEvent:
        """Create an immutable audit event.  Called by every state-changing operation."""
        evt = QualityAuditEvent(
            id=_new_id(),
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            event_type=event_type,
            reference_type=reference_type,
            reference_id=reference_id,
            source_chart_id=source_chart_id,
            event_metadata_json=_json_dumps(metadata or {}),
            correlation_id=correlation_id,
            occurred_at=_now(),
        )
        db.add(evt)
        return evt

    # =========================================================================
    # QA TRIGGER ENGINE
    # =========================================================================

    @staticmethod
    async def get_active_triggers(db: AsyncSession, *, tenant_id: str) -> list[QATriggerConfiguration]:
        result = await db.execute(
            select(QATriggerConfiguration).where(
                QATriggerConfiguration.tenant_id == tenant_id,
                QATriggerConfiguration.is_active == True,  # noqa: E712
                QATriggerConfiguration.deleted_at == None,  # noqa: E711
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def evaluate_qa_triggers(
        db: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        chart_data: dict,
        created_by: str,
        created_by_role: str = "system",
    ) -> list[QACaseRecord]:
        """Evaluate all active triggers against chart data and create QA cases.

        Matches trigger conditions against chart_data keys/values.
        A condition_json of {"field": "value"} matches when chart_data[field] == value.
        A condition_json of {} (empty) matches all charts for that trigger_key.
        Never auto-closes a QA case.
        """
        triggers = await QualityService.get_active_triggers(db, tenant_id=tenant_id)
        created_cases: list[QACaseRecord] = []

        for trigger in triggers:
            condition = _json_loads(trigger.condition_json)
            matched = True
            for field, expected in condition.items():
                if str(chart_data.get(field, "")).lower() != str(expected).lower():
                    matched = False
                    break

            if matched:
                case = await QualityService.create_qa_case(
                    db,
                    tenant_id=tenant_id,
                    source_chart_id=chart_id,
                    trigger_key=trigger.trigger_key,
                    trigger_type="automatic",
                    priority=trigger.priority,
                    created_by=created_by,
                    created_by_role=created_by_role,
                )
                created_cases.append(case)

        if created_cases:
            await db.commit()
        return created_cases

    @staticmethod
    async def create_qa_case(
        db: AsyncSession,
        *,
        tenant_id: str,
        source_chart_id: str,
        trigger_key: str,
        trigger_type: str,
        priority: str,
        created_by: str,
        created_by_role: str = "qa_reviewer",
        agency_id: str | None = None,
        due_date: datetime | None = None,
    ) -> QACaseRecord:
        """Create a new QA case with a deterministic case number."""
        now = _now()
        period = now.strftime("%Y%m")

        # Count existing cases for this tenant+period to build sequence number
        count_result = await db.execute(
            select(func.count()).where(
                QACaseRecord.tenant_id == tenant_id,
                QACaseRecord.case_number.like(f"QA-%{period}%"),
            )
        )
        seq = (count_result.scalar() or 0) + 1

        # Derive a short tenant prefix from the first 4 chars of tenant_id
        prefix = tenant_id.replace("-", "")[:4].upper()
        case_number = f"QA-{prefix}-{period}-{seq:04d}"

        case = QACaseRecord(
            id=_new_id(),
            tenant_id=tenant_id,
            agency_id=agency_id,
            source_chart_id=source_chart_id,
            case_number=case_number,
            trigger_key=trigger_key,
            trigger_type=trigger_type,
            priority=priority,
            status="new",
            due_date=due_date,
            created_by=created_by,
            created_at=now,
            updated_by=created_by,
            updated_at=now,
        )
        db.add(case)
        await db.flush()

        await QualityService.emit_audit_event(
            db,
            tenant_id=tenant_id,
            actor_id=created_by,
            actor_role=created_by_role,
            event_type="qa_case_created",
            reference_type="qa_case",
            reference_id=case.id,
            source_chart_id=source_chart_id,
            metadata={
                "trigger_key": trigger_key,
                "trigger_type": trigger_type,
                "priority": priority,
                "case_number": case_number,
            },
        )
        return case

    @staticmethod
    async def assign_qa_case(
        db: AsyncSession,
        *,
        tenant_id: str,
        qa_case_id: str,
        reviewer_id: str,
        assigned_by: str,
        assigned_by_role: str,
        due_date: datetime | None = None,
    ) -> QACaseRecord:
        """Assign a QA case to a reviewer."""
        result = await db.execute(
            select(QACaseRecord).where(
                QACaseRecord.id == qa_case_id,
                QACaseRecord.tenant_id == tenant_id,
            )
        )
        case = result.scalar_one_or_none()
        if case is None:
            raise QAWorkflowError(f"QA case {qa_case_id} not found for tenant {tenant_id}")

        now = _now()
        case.assigned_to = reviewer_id
        case.assigned_at = now
        case.status = "assigned"
        case.updated_by = assigned_by
        case.updated_at = now
        if due_date:
            case.due_date = due_date

        await QualityService.emit_audit_event(
            db,
            tenant_id=tenant_id,
            actor_id=assigned_by,
            actor_role=assigned_by_role,
            event_type="qa_case_assigned",
            reference_type="qa_case",
            reference_id=qa_case_id,
            source_chart_id=case.source_chart_id,
            metadata={"reviewer_id": reviewer_id},
        )
        await db.commit()
        await db.refresh(case)
        return case

    @staticmethod
    async def submit_qa_score(
        db: AsyncSession,
        *,
        tenant_id: str,
        qa_case_id: str,
        reviewer_id: str,
        reviewer_role: str,
        documentation_quality_score: float,
        protocol_adherence_score: float,
        timeliness_score: float,
        clinical_quality_score: float,
        operational_quality_score: float,
        reviewer_notes: str | None = None,
        context_flags: dict | None = None,
        call_complexity_adjustment: float = 0.0,
        documentation_weight: float = 0.25,
        protocol_weight: float = 0.25,
        timeliness_weight: float = 0.15,
        clinical_weight: float = 0.25,
        operational_weight: float = 0.10,
    ) -> QAScore:
        """Submit a QA score. Does not auto-close the case."""
        composite = (
            documentation_quality_score * documentation_weight
            + protocol_adherence_score * protocol_weight
            + timeliness_score * timeliness_weight
            + clinical_quality_score * clinical_weight
            + operational_quality_score * operational_weight
            + call_complexity_adjustment
        )
        composite = min(100.0, max(0.0, composite))

        now = _now()
        score = QAScore(
            id=_new_id(),
            tenant_id=tenant_id,
            qa_case_id=qa_case_id,
            reviewer_id=reviewer_id,
            score_version="v1",
            documentation_quality_score=documentation_quality_score,
            protocol_adherence_score=protocol_adherence_score,
            timeliness_score=timeliness_score,
            clinical_quality_score=clinical_quality_score,
            operational_quality_score=operational_quality_score,
            composite_score=composite,
            documentation_weight=documentation_weight,
            protocol_weight=protocol_weight,
            timeliness_weight=timeliness_weight,
            clinical_weight=clinical_weight,
            operational_weight=operational_weight,
            reviewer_notes=reviewer_notes,
            context_flags_json=_json_dumps(context_flags or {}),
            call_complexity_adjustment=call_complexity_adjustment,
            created_by=reviewer_id,
            created_at=now,
            updated_by=reviewer_id,
            updated_at=now,
        )
        db.add(score)

        # Update case with latest score
        result = await db.execute(
            select(QACaseRecord).where(
                QACaseRecord.id == qa_case_id,
                QACaseRecord.tenant_id == tenant_id,
            )
        )
        case = result.scalar_one_or_none()
        if case:
            case.qa_score = composite
            case.score_version = "v1"
            if case.status == "assigned":
                case.status = "in_review"
            case.updated_by = reviewer_id
            case.updated_at = now

        await QualityService.emit_audit_event(
            db,
            tenant_id=tenant_id,
            actor_id=reviewer_id,
            actor_role=reviewer_role,
            event_type="qa_score_submitted",
            reference_type="qa_case",
            reference_id=qa_case_id,
            source_chart_id=case.source_chart_id if case else None,
            metadata={"composite_score": composite, "score_id": score.id},
        )
        await db.commit()
        await db.refresh(score)
        return score

    @staticmethod
    async def add_qa_finding(
        db: AsyncSession,
        *,
        tenant_id: str,
        qa_case_id: str,
        reviewer_id: str,
        reviewer_role: str,
        finding_type: str,
        severity: str,
        domain: str,
        description: str,
        recommendation: str | None = None,
        chart_reference: dict | None = None,
        education_recommended: bool = False,
        process_improvement_recommended: bool = False,
        medical_director_review_recommended: bool = False,
    ) -> QAReviewFinding:
        """Add a finding to a QA case. Never modifies original chart data."""
        now = _now()
        finding = QAReviewFinding(
            id=_new_id(),
            tenant_id=tenant_id,
            qa_case_id=qa_case_id,
            reviewer_id=reviewer_id,
            finding_type=finding_type,
            severity=severity,
            domain=domain,
            description=description,
            recommendation=recommendation,
            chart_reference_json=_json_dumps(chart_reference or {}),
            education_recommended=education_recommended,
            process_improvement_recommended=process_improvement_recommended,
            medical_director_review_recommended=medical_director_review_recommended,
            status="open",
            created_by=reviewer_id,
            created_at=now,
            updated_by=reviewer_id,
            updated_at=now,
        )
        db.add(finding)

        await QualityService.emit_audit_event(
            db,
            tenant_id=tenant_id,
            actor_id=reviewer_id,
            actor_role=reviewer_role,
            event_type="qa_finding_added",
            reference_type="qa_case",
            reference_id=qa_case_id,
            metadata={
                "finding_id": finding.id,
                "finding_type": finding_type,
                "severity": severity,
            },
        )
        await db.commit()
        await db.refresh(finding)
        return finding

    @staticmethod
    async def escalate_to_medical_director(
        db: AsyncSession,
        *,
        tenant_id: str,
        qa_case_id: str,
        escalated_by: str,
        escalated_by_role: str,
        escalation_reason: str,
        medical_director_id: str,
        review_type: str = "qa_escalation",
    ) -> MedicalDirectorReview:
        """Escalate a QA case to the medical director."""
        result = await db.execute(
            select(QACaseRecord).where(
                QACaseRecord.id == qa_case_id,
                QACaseRecord.tenant_id == tenant_id,
            )
        )
        case = result.scalar_one_or_none()
        if case is None:
            raise QAWorkflowError(f"QA case {qa_case_id} not found")

        now = _now()
        review = MedicalDirectorReview(
            id=_new_id(),
            tenant_id=tenant_id,
            qa_case_id=qa_case_id,
            source_chart_id=case.source_chart_id,
            medical_director_id=medical_director_id,
            escalated_by=escalated_by,
            escalation_reason=escalation_reason,
            status="pending",
            review_type=review_type,
            created_by=escalated_by,
            created_at=now,
            updated_by=escalated_by,
            updated_at=now,
        )
        db.add(review)
        await db.flush()

        case.medical_director_escalated = True
        case.medical_director_escalation_id = review.id
        case.status = "medical_director_escalated"
        case.updated_by = escalated_by
        case.updated_at = now

        await QualityService.emit_audit_event(
            db,
            tenant_id=tenant_id,
            actor_id=escalated_by,
            actor_role=escalated_by_role,
            event_type="qa_case_escalated",
            reference_type="qa_case",
            reference_id=qa_case_id,
            source_chart_id=case.source_chart_id,
            metadata={
                "md_review_id": review.id,
                "medical_director_id": medical_director_id,
                "escalation_reason": escalation_reason,
            },
        )
        await db.commit()
        await db.refresh(review)
        return review

    @staticmethod
    async def close_qa_case(
        db: AsyncSession,
        *,
        tenant_id: str,
        qa_case_id: str,
        closed_by: str,
        closed_by_role: str,
        closure_notes: str,
    ) -> QACaseRecord:
        """Close a QA case.

        Cannot close if a medical director escalation is still pending.
        """
        result = await db.execute(
            select(QACaseRecord).where(
                QACaseRecord.id == qa_case_id,
                QACaseRecord.tenant_id == tenant_id,
            )
        )
        case = result.scalar_one_or_none()
        if case is None:
            raise QAWorkflowError(f"QA case {qa_case_id} not found")

        if case.medical_director_escalated:
            # Check if the MD review is complete
            md_result = await db.execute(
                select(MedicalDirectorReview).where(
                    MedicalDirectorReview.id == case.medical_director_escalation_id,
                    MedicalDirectorReview.tenant_id == tenant_id,
                )
            )
            md_review = md_result.scalar_one_or_none()
            if md_review and md_review.status not in ("completed", "closed"):
                raise QAWorkflowError(
                    "Cannot close QA case while medical director review is still pending. "
                    f"MD review {md_review.id} has status '{md_review.status}'."
                )

        now = _now()
        case.status = "closed"
        case.closure_notes = closure_notes
        case.closed_at = now
        case.closed_by = closed_by
        case.updated_by = closed_by
        case.updated_at = now

        await QualityService.emit_audit_event(
            db,
            tenant_id=tenant_id,
            actor_id=closed_by,
            actor_role=closed_by_role,
            event_type="qa_case_closed",
            reference_type="qa_case",
            reference_id=qa_case_id,
            source_chart_id=case.source_chart_id,
            metadata={"closure_notes": closure_notes},
        )
        await db.commit()
        await db.refresh(case)
        return case

    # =========================================================================
    # PEER REVIEW
    # =========================================================================

    @staticmethod
    async def assign_peer_review(
        db: AsyncSession,
        *,
        tenant_id: str,
        qa_case_id: str,
        reviewer_id: str,
        assignor_id: str,
        assignor_role: str,
        chart_provider_id: str,
        crew_member_ids: list[str],
        is_blind: bool = False,
        due_date: datetime | None = None,
    ) -> PeerReview:
        """Assign a peer review.

        Validates conflict of interest:
        - reviewer_id must not equal chart_provider_id
        - reviewer_id must not be in crew_member_ids
        """
        # Get source chart ID from QA case
        result = await db.execute(
            select(QACaseRecord).where(
                QACaseRecord.id == qa_case_id,
                QACaseRecord.tenant_id == tenant_id,
            )
        )
        case = result.scalar_one_or_none()
        if case is None:
            raise QAWorkflowError(f"QA case {qa_case_id} not found")

        if reviewer_id == chart_provider_id:
            raise ConflictOfInterestError(
                "Peer reviewer cannot review their own case. "
                f"Reviewer {reviewer_id} is the chart provider."
            )
        if reviewer_id in crew_member_ids:
            raise ConflictOfInterestError(
                "Peer reviewer cannot review a case where they were part of the crew. "
                f"Reviewer {reviewer_id} is in crew: {crew_member_ids}"
            )

        now = _now()
        review = PeerReview(
            id=_new_id(),
            tenant_id=tenant_id,
            qa_case_id=qa_case_id,
            source_chart_id=case.source_chart_id,
            reviewer_id=reviewer_id,
            assignor_id=assignor_id,
            is_blind=is_blind,
            conflict_of_interest_checked=True,
            status="assigned",
            is_protected=True,
            created_by=assignor_id,
            created_at=now,
            updated_by=assignor_id,
            updated_at=now,
        )
        db.add(review)
        await db.flush()

        assignment = PeerReviewAssignment(
            id=_new_id(),
            tenant_id=tenant_id,
            peer_review_id=review.id,
            reviewer_id=reviewer_id,
            chart_provider_id=chart_provider_id,
            crew_member_ids_json=_json_dumps(crew_member_ids),
            is_conflict=False,
            assigned_at=now,
            due_date=due_date,
            created_by=assignor_id,
            created_at=now,
        )
        db.add(assignment)

        await QualityService.emit_audit_event(
            db,
            tenant_id=tenant_id,
            actor_id=assignor_id,
            actor_role=assignor_role,
            event_type="peer_review_assigned",
            reference_type="peer_review",
            reference_id=review.id,
            source_chart_id=case.source_chart_id,
            metadata={
                "reviewer_id": reviewer_id,
                "qa_case_id": qa_case_id,
                "is_blind": is_blind,
            },
        )
        await db.commit()
        await db.refresh(review)
        return review

    @staticmethod
    async def complete_peer_review(
        db: AsyncSession,
        *,
        tenant_id: str,
        peer_review_id: str,
        reviewer_id: str,
        reviewer_role: str,
        strengths_notes: str | None = None,
        improvement_notes: str | None = None,
        education_recommendation: str | None = None,
        process_improvement_suggestion: str | None = None,
        exemplary_care_flag: bool = False,
        reviewer_signature: str | None = None,
    ) -> PeerReview:
        """Complete a peer review with findings."""
        result = await db.execute(
            select(PeerReview).where(
                PeerReview.id == peer_review_id,
                PeerReview.tenant_id == tenant_id,
                PeerReview.reviewer_id == reviewer_id,
            )
        )
        review = result.scalar_one_or_none()
        if review is None:
            raise QAWorkflowError(
                f"Peer review {peer_review_id} not found or you are not the assigned reviewer."
            )

        now = _now()
        review.status = "completed"
        review.strengths_notes = strengths_notes
        review.improvement_notes = improvement_notes
        review.education_recommendation = education_recommendation
        review.process_improvement_suggestion = process_improvement_suggestion
        review.exemplary_care_flag = exemplary_care_flag
        review.reviewer_signature = reviewer_signature
        review.signed_at = now if reviewer_signature else None
        review.completed_at = now
        review.updated_by = reviewer_id
        review.updated_at = now

        await QualityService.emit_audit_event(
            db,
            tenant_id=tenant_id,
            actor_id=reviewer_id,
            actor_role=reviewer_role,
            event_type="peer_review_completed",
            reference_type="peer_review",
            reference_id=peer_review_id,
            source_chart_id=review.source_chart_id,
            metadata={"exemplary_care_flag": exemplary_care_flag},
        )
        await db.commit()
        await db.refresh(review)
        return review

    # =========================================================================
    # MEDICAL DIRECTOR
    # =========================================================================

    @staticmethod
    async def add_medical_director_note(
        db: AsyncSession,
        *,
        tenant_id: str,
        medical_director_review_id: str,
        author_id: str,
        author_role: str,
        note_type: str,
        note_text: str,
        recommendation: str | None = None,
        finding_type: str | None = None,
    ) -> MedicalDirectorNote:
        """Add a protected medical director note.

        This note is stored as a separate review artifact.
        It NEVER modifies original clinical documentation.
        """
        result = await db.execute(
            select(MedicalDirectorReview).where(
                MedicalDirectorReview.id == medical_director_review_id,
                MedicalDirectorReview.tenant_id == tenant_id,
            )
        )
        review = result.scalar_one_or_none()
        if review is None:
            raise QAWorkflowError(f"MD review {medical_director_review_id} not found")

        now = _now()
        note = MedicalDirectorNote(
            id=_new_id(),
            tenant_id=tenant_id,
            medical_director_review_id=medical_director_review_id,
            source_chart_id=review.source_chart_id,
            author_id=author_id,
            author_role=author_role,
            note_type=note_type,
            note_text=note_text,
            recommendation=recommendation,
            finding_type=finding_type,
            is_protected=True,
            created_by=author_id,
            created_at=now,
            updated_by=author_id,
            updated_at=now,
        )
        db.add(note)

        if review.status == "pending":
            review.status = "in_review"
            review.updated_by = author_id
            review.updated_at = now

        await QualityService.emit_audit_event(
            db,
            tenant_id=tenant_id,
            actor_id=author_id,
            actor_role=author_role,
            event_type="md_note_added",
            reference_type="md_review",
            reference_id=medical_director_review_id,
            source_chart_id=review.source_chart_id,
            metadata={"note_id": note.id, "note_type": note_type},
        )
        await db.commit()
        await db.refresh(note)
        return note

    @staticmethod
    async def complete_medical_director_review(
        db: AsyncSession,
        *,
        tenant_id: str,
        review_id: str,
        md_id: str,
        md_role: str,
        finding_classification: str | None = None,
        protocol_deviation_identified: bool = False,
        exemplary_care_identified: bool = False,
        education_recommended: bool = False,
        protocol_revision_recommended: bool = False,
        agency_leadership_flag: bool = False,
    ) -> MedicalDirectorReview:
        """Complete a medical director review with findings classification."""
        result = await db.execute(
            select(MedicalDirectorReview).where(
                MedicalDirectorReview.id == review_id,
                MedicalDirectorReview.tenant_id == tenant_id,
                MedicalDirectorReview.medical_director_id == md_id,
            )
        )
        review = result.scalar_one_or_none()
        if review is None:
            raise QAWorkflowError(f"MD review {review_id} not found or you are not the assigned medical director.")

        now = _now()
        review.status = "completed"
        review.finding_classification = finding_classification
        review.protocol_deviation_identified = protocol_deviation_identified
        review.exemplary_care_identified = exemplary_care_identified
        review.education_recommended = education_recommended
        review.protocol_revision_recommended = protocol_revision_recommended
        review.agency_leadership_flag = agency_leadership_flag
        review.completed_at = now
        review.updated_by = md_id
        review.updated_at = now

        await QualityService.emit_audit_event(
            db,
            tenant_id=tenant_id,
            actor_id=md_id,
            actor_role=md_role,
            event_type="md_review_completed",
            reference_type="md_review",
            reference_id=review_id,
            source_chart_id=review.source_chart_id,
            metadata={
                "finding_classification": finding_classification,
                "protocol_deviation_identified": protocol_deviation_identified,
                "education_recommended": education_recommended,
            },
        )
        await db.commit()
        await db.refresh(review)
        return review

    @staticmethod
    async def request_md_clarification(
        db: AsyncSession,
        *,
        tenant_id: str,
        review_id: str,
        md_id: str,
        md_role: str,
        clarification_from: str,
        clarification_notes: str,
    ) -> MedicalDirectorReview:
        """Request clarification from a provider."""
        result = await db.execute(
            select(MedicalDirectorReview).where(
                MedicalDirectorReview.id == review_id,
                MedicalDirectorReview.tenant_id == tenant_id,
            )
        )
        review = result.scalar_one_or_none()
        if review is None:
            raise QAWorkflowError(f"MD review {review_id} not found")

        now = _now()
        review.status = "clarification_requested"
        review.clarification_requested_from = clarification_from
        review.clarification_request_notes = clarification_notes
        review.updated_by = md_id
        review.updated_at = now

        await QualityService.emit_audit_event(
            db,
            tenant_id=tenant_id,
            actor_id=md_id,
            actor_role=md_role,
            event_type="md_clarification_requested",
            reference_type="md_review",
            reference_id=review_id,
            source_chart_id=review.source_chart_id,
            metadata={"clarification_from": clarification_from},
        )
        await db.commit()
        await db.refresh(review)
        return review

    # =========================================================================
    # PROTOCOLS
    # =========================================================================

    @staticmethod
    async def publish_protocol_version(
        db: AsyncSession,
        *,
        tenant_id: str,
        protocol_id: str,
        version_id: str,
        approved_by: str,
        approved_by_role: str,
    ) -> ProtocolVersion:
        """Publish a protocol version."""
        result = await db.execute(
            select(ProtocolVersion).where(
                ProtocolVersion.id == version_id,
                ProtocolVersion.tenant_id == tenant_id,
                ProtocolVersion.protocol_id == protocol_id,
            )
        )
        version = result.scalar_one_or_none()
        if version is None:
            raise QAWorkflowError(f"Protocol version {version_id} not found")

        now = _now()
        version.status = "published"
        version.published_at = now
        version.medical_director_approval_id = approved_by
        version.approved_at = now
        version.updated_by = approved_by
        version.updated_at = now

        # Update protocol's current_version_id
        proto_result = await db.execute(
            select(ProtocolDocument).where(
                ProtocolDocument.id == protocol_id,
                ProtocolDocument.tenant_id == tenant_id,
            )
        )
        proto = proto_result.scalar_one_or_none()
        if proto:
            proto.current_version_id = version_id
            proto.status = "published"
            proto.updated_by = approved_by
            proto.updated_at = now

        await QualityService.emit_audit_event(
            db,
            tenant_id=tenant_id,
            actor_id=approved_by,
            actor_role=approved_by_role,
            event_type="protocol_published",
            reference_type="protocol_version",
            reference_id=version_id,
            metadata={"protocol_id": protocol_id},
        )
        await db.commit()
        await db.refresh(version)
        return version

    @staticmethod
    async def record_protocol_acknowledgment(
        db: AsyncSession,
        *,
        tenant_id: str,
        protocol_version_id: str,
        provider_id: str,
        provider_signature: str | None = None,
    ) -> ProtocolAcknowledgment:
        """Record provider acknowledgment of a protocol version."""
        # Check if already acknowledged
        existing = await db.execute(
            select(ProtocolAcknowledgment).where(
                ProtocolAcknowledgment.tenant_id == tenant_id,
                ProtocolAcknowledgment.protocol_version_id == protocol_version_id,
                ProtocolAcknowledgment.provider_id == provider_id,
            )
        )
        if existing.scalar_one_or_none():
            raise QAWorkflowError("Provider has already acknowledged this protocol version.")

        now = _now()
        ack = ProtocolAcknowledgment(
            id=_new_id(),
            tenant_id=tenant_id,
            protocol_version_id=protocol_version_id,
            provider_id=provider_id,
            acknowledged_at=now,
            provider_signature=provider_signature,
            created_by=provider_id,
            created_at=now,
        )
        db.add(ack)

        await QualityService.emit_audit_event(
            db,
            tenant_id=tenant_id,
            actor_id=provider_id,
            actor_role="provider",
            event_type="protocol_acknowledgment_recorded",
            reference_type="protocol_acknowledgment",
            reference_id=ack.id,
            metadata={"protocol_version_id": protocol_version_id},
        )
        await db.commit()
        await db.refresh(ack)
        return ack

    # =========================================================================
    # EDUCATION FOLLOW-UP
    # =========================================================================

    @staticmethod
    async def assign_education(
        db: AsyncSession,
        *,
        tenant_id: str,
        provider_id: str,
        assigned_by: str,
        assigned_by_role: str,
        education_type: str,
        education_title: str,
        education_description: str | None = None,
        education_resource_url: str | None = None,
        due_date: datetime | None = None,
        qa_case_id: str | None = None,
        medical_director_review_id: str | None = None,
        qi_initiative_id: str | None = None,
    ) -> EducationFollowUp:
        """Assign education to a provider."""
        now = _now()
        edu = EducationFollowUp(
            id=_new_id(),
            tenant_id=tenant_id,
            provider_id=provider_id,
            assigned_by=assigned_by,
            assigned_by_role=assigned_by_role,
            qa_case_id=qa_case_id,
            medical_director_review_id=medical_director_review_id,
            qi_initiative_id=qi_initiative_id,
            education_type=education_type,
            education_title=education_title,
            education_description=education_description,
            education_resource_url=education_resource_url,
            due_date=due_date,
            status="assigned",
            created_by=assigned_by,
            created_at=now,
            updated_by=assigned_by,
            updated_at=now,
        )
        db.add(edu)
        await db.flush()

        # Update QA case if linked
        if qa_case_id:
            qa_result = await db.execute(
                select(QACaseRecord).where(
                    QACaseRecord.id == qa_case_id,
                    QACaseRecord.tenant_id == tenant_id,
                )
            )
            qa_case = qa_result.scalar_one_or_none()
            if qa_case:
                qa_case.education_assigned = True
                qa_case.education_assignment_id = edu.id
                qa_case.updated_by = assigned_by
                qa_case.updated_at = now

        await QualityService.emit_audit_event(
            db,
            tenant_id=tenant_id,
            actor_id=assigned_by,
            actor_role=assigned_by_role,
            event_type="education_assigned",
            reference_type="education_followup",
            reference_id=edu.id,
            metadata={
                "provider_id": provider_id,
                "education_type": education_type,
                "education_title": education_title,
            },
        )
        await db.commit()
        await db.refresh(edu)
        return edu

    @staticmethod
    async def complete_education(
        db: AsyncSession,
        *,
        tenant_id: str,
        education_id: str,
        provider_id: str,
    ) -> EducationFollowUp:
        """Provider marks their education as completed."""
        result = await db.execute(
            select(EducationFollowUp).where(
                EducationFollowUp.id == education_id,
                EducationFollowUp.tenant_id == tenant_id,
                EducationFollowUp.provider_id == provider_id,
            )
        )
        edu = result.scalar_one_or_none()
        if edu is None:
            raise QAWorkflowError(f"Education {education_id} not found or not assigned to provider {provider_id}.")

        now = _now()
        edu.status = "completed"
        edu.completed_at = now
        edu.updated_by = provider_id
        edu.updated_at = now

        await QualityService.emit_audit_event(
            db,
            tenant_id=tenant_id,
            actor_id=provider_id,
            actor_role="provider",
            event_type="education_completed",
            reference_type="education_followup",
            reference_id=education_id,
            metadata={},
        )
        await db.commit()
        await db.refresh(edu)
        return edu

    # =========================================================================
    # PROVIDER FEEDBACK
    # =========================================================================

    @staticmethod
    async def send_provider_feedback(
        db: AsyncSession,
        *,
        tenant_id: str,
        provider_id: str,
        sent_by: str,
        sent_by_role: str,
        feedback_type: str,
        subject: str,
        message_text: str,
        qa_case_id: str | None = None,
        medical_director_review_id: str | None = None,
    ) -> ProviderFeedback:
        """Send protected, auditable feedback to a provider."""
        now = _now()
        feedback = ProviderFeedback(
            id=_new_id(),
            tenant_id=tenant_id,
            provider_id=provider_id,
            sent_by=sent_by,
            sent_by_role=sent_by_role,
            qa_case_id=qa_case_id,
            medical_director_review_id=medical_director_review_id,
            feedback_type=feedback_type,
            subject=subject,
            message_text=message_text,
            is_protected=True,
            status="sent",
            created_by=sent_by,
            created_at=now,
            updated_by=sent_by,
            updated_at=now,
        )
        db.add(feedback)

        await QualityService.emit_audit_event(
            db,
            tenant_id=tenant_id,
            actor_id=sent_by,
            actor_role=sent_by_role,
            event_type="provider_feedback_sent",
            reference_type="provider_feedback",
            reference_id=feedback.id,
            metadata={
                "provider_id": provider_id,
                "feedback_type": feedback_type,
            },
        )
        await db.commit()
        await db.refresh(feedback)
        return feedback

    @staticmethod
    async def acknowledge_provider_feedback(
        db: AsyncSession,
        *,
        tenant_id: str,
        feedback_id: str,
        provider_id: str,
        provider_response: str | None = None,
    ) -> ProviderFeedback:
        """Provider acknowledges and optionally responds to feedback."""
        result = await db.execute(
            select(ProviderFeedback).where(
                ProviderFeedback.id == feedback_id,
                ProviderFeedback.tenant_id == tenant_id,
                ProviderFeedback.provider_id == provider_id,
            )
        )
        feedback = result.scalar_one_or_none()
        if feedback is None:
            raise QAWorkflowError(f"Feedback {feedback_id} not found for provider {provider_id}.")

        now = _now()
        feedback.acknowledged_at = now
        feedback.status = "responded" if provider_response else "acknowledged"
        if provider_response:
            feedback.provider_response = provider_response
            feedback.provider_responded_at = now
        feedback.updated_by = provider_id
        feedback.updated_at = now

        await QualityService.emit_audit_event(
            db,
            tenant_id=tenant_id,
            actor_id=provider_id,
            actor_role="provider",
            event_type="provider_feedback_acknowledged",
            reference_type="provider_feedback",
            reference_id=feedback_id,
            metadata={},
        )
        await db.commit()
        await db.refresh(feedback)
        return feedback

    # =========================================================================
    # QI INITIATIVES
    # =========================================================================

    @staticmethod
    async def create_qi_initiative(
        db: AsyncSession,
        *,
        tenant_id: str,
        initiative_title: str,
        category: str,
        source_trend_description: str,
        intervention_plan: str,
        owner_id: str,
        created_by: str,
        created_by_role: str,
        start_date: datetime | None = None,
        baseline_metric_value: float | None = None,
        baseline_metric_label: str | None = None,
        target_metric_value: float | None = None,
        target_metric_label: str | None = None,
        target_completion_date: datetime | None = None,
        stakeholder_ids: list[str] | None = None,
    ) -> QIInitiative:
        """Create a new QI initiative."""
        now = _now()
        initiative = QIInitiative(
            id=_new_id(),
            tenant_id=tenant_id,
            initiative_title=initiative_title,
            category=category,
            source_trend_description=source_trend_description,
            baseline_metric_value=baseline_metric_value,
            baseline_metric_label=baseline_metric_label,
            target_metric_value=target_metric_value,
            target_metric_label=target_metric_label,
            start_date=start_date or now,
            target_completion_date=target_completion_date,
            owner_id=owner_id,
            stakeholder_ids_json=_json_dumps(stakeholder_ids or []),
            intervention_plan=intervention_plan,
            status="identified",
            created_by=created_by,
            created_at=now,
            updated_by=created_by,
            updated_at=now,
        )
        db.add(initiative)

        await QualityService.emit_audit_event(
            db,
            tenant_id=tenant_id,
            actor_id=created_by,
            actor_role=created_by_role,
            event_type="qi_initiative_created",
            reference_type="qi_initiative",
            reference_id=initiative.id,
            metadata={"category": category, "title": initiative_title},
        )
        await db.commit()
        await db.refresh(initiative)
        return initiative

    @staticmethod
    async def advance_qi_initiative_status(
        db: AsyncSession,
        *,
        tenant_id: str,
        initiative_id: str,
        new_status: str,
        actor_id: str,
        actor_role: str,
        notes: str | None = None,
        outcome_summary: str | None = None,
        current_metric_value: float | None = None,
    ) -> QIInitiative:
        """Advance a QI initiative through its lifecycle."""
        result = await db.execute(
            select(QIInitiative).where(
                QIInitiative.id == initiative_id,
                QIInitiative.tenant_id == tenant_id,
            )
        )
        initiative = result.scalar_one_or_none()
        if initiative is None:
            raise QAWorkflowError(f"QI initiative {initiative_id} not found")

        now = _now()
        old_status = initiative.status
        initiative.status = new_status
        if notes:
            initiative.closure_notes = notes
        if outcome_summary:
            initiative.outcome_summary = outcome_summary
        if current_metric_value is not None:
            initiative.current_metric_value = current_metric_value
        if new_status == "closed":
            initiative.closed_at = now
        initiative.updated_by = actor_id
        initiative.updated_at = now

        await QualityService.emit_audit_event(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            event_type="qi_initiative_status_changed",
            reference_type="qi_initiative",
            reference_id=initiative_id,
            metadata={"from_status": old_status, "to_status": new_status},
        )
        await db.commit()
        await db.refresh(initiative)
        return initiative

    @staticmethod
    async def record_qi_metric(
        db: AsyncSession,
        *,
        tenant_id: str,
        initiative_id: str,
        metric_key: str,
        metric_value: float,
        metric_label: str,
        measurement_period: str,
        recorded_by: str,
        notes: str | None = None,
    ) -> QIInitiativeMetric:
        """Record a metric measurement for a QI initiative."""
        now = _now()
        metric = QIInitiativeMetric(
            id=_new_id(),
            tenant_id=tenant_id,
            initiative_id=initiative_id,
            metric_key=metric_key,
            metric_value=metric_value,
            metric_label=metric_label,
            measurement_period=measurement_period,
            recorded_at=now,
            recorded_by=recorded_by,
            notes=notes,
            created_by=recorded_by,
            created_at=now,
        )
        db.add(metric)

        # Update current_metric_value on initiative
        result = await db.execute(
            select(QIInitiative).where(
                QIInitiative.id == initiative_id,
                QIInitiative.tenant_id == tenant_id,
            )
        )
        initiative = result.scalar_one_or_none()
        if initiative:
            initiative.current_metric_value = metric_value
            initiative.updated_by = recorded_by
            initiative.updated_at = now

        await db.commit()
        await db.refresh(metric)
        return metric

    # =========================================================================
    # DASHBOARDS (always computed from real DB data)
    # =========================================================================

    @staticmethod
    async def get_qa_dashboard_data(db: AsyncSession, *, tenant_id: str) -> dict:
        """Compute QA dashboard data from real DB queries."""
        # Total cases by status
        status_result = await db.execute(
            select(QACaseRecord.status, func.count().label("count"))
            .where(QACaseRecord.tenant_id == tenant_id, QACaseRecord.deleted_at == None)  # noqa: E711
            .group_by(QACaseRecord.status)
        )
        status_counts = {row.status: row.count for row in status_result}

        # Overdue cases
        now = _now()
        overdue_result = await db.execute(
            select(func.count()).where(
                QACaseRecord.tenant_id == tenant_id,
                QACaseRecord.status.notin_(["closed", "appealed"]),
                QACaseRecord.due_date < now,
                QACaseRecord.deleted_at == None,  # noqa: E711
            )
        )
        overdue_count = overdue_result.scalar() or 0

        # Average QA score
        score_result = await db.execute(
            select(func.avg(QACaseRecord.qa_score)).where(
                QACaseRecord.tenant_id == tenant_id,
                QACaseRecord.qa_score != None,  # noqa: E711
            )
        )
        avg_score = score_result.scalar() or 0.0

        # Trigger breakdown
        trigger_result = await db.execute(
            select(QACaseRecord.trigger_key, func.count().label("count"))
            .where(QACaseRecord.tenant_id == tenant_id)
            .group_by(QACaseRecord.trigger_key)
        )
        trigger_breakdown = {row.trigger_key: row.count for row in trigger_result}

        # Education pending
        edu_result = await db.execute(
            select(func.count()).where(
                EducationFollowUp.tenant_id == tenant_id,
                EducationFollowUp.status.in_(["assigned", "acknowledged", "in_progress"]),
            )
        )
        education_pending = edu_result.scalar() or 0

        # MD escalations
        md_result = await db.execute(
            select(func.count()).where(
                MedicalDirectorReview.tenant_id == tenant_id,
                MedicalDirectorReview.status.in_(["pending", "in_review", "clarification_requested"]),
            )
        )
        md_pending = md_result.scalar() or 0

        return {
            "open_cases": status_counts.get("new", 0) + status_counts.get("assigned", 0) + status_counts.get("in_review", 0),
            "pending_reviews": status_counts.get("assigned", 0),
            "overdue_reviews": overdue_count,
            "high_priority_cases": 0,  # extended query needed
            "avg_qa_score": round(avg_score, 1),
            "trigger_breakdown": trigger_breakdown,
            "education_assignments_pending": education_pending,
            "medical_director_escalations_pending": md_pending,
            "status_breakdown": status_counts,
            "total_cases": sum(status_counts.values()),
        }

    @staticmethod
    async def get_md_dashboard_data(db: AsyncSession, *, tenant_id: str) -> dict:
        """Compute Medical Director dashboard data from real DB queries."""
        # MD reviews by status
        md_result = await db.execute(
            select(MedicalDirectorReview.status, func.count().label("count"))
            .where(MedicalDirectorReview.tenant_id == tenant_id)
            .group_by(MedicalDirectorReview.status)
        )
        md_status = {row.status: row.count for row in md_result}

        # Protocol deviations
        pd_result = await db.execute(
            select(func.count()).where(
                MedicalDirectorReview.tenant_id == tenant_id,
                MedicalDirectorReview.protocol_deviation_identified == True,  # noqa: E712
            )
        )
        protocol_deviations = pd_result.scalar() or 0

        # Standing orders expiring soon (within 30 days)
        thirty_days = _now()
        so_result = await db.execute(
            select(func.count()).where(
                StandingOrderVersion.tenant_id == tenant_id,
                StandingOrderVersion.expiration_date != None,  # noqa: E711
                StandingOrderVersion.status == "active",
            )
        )
        standing_orders_expiring = so_result.scalar() or 0

        return {
            "pending_reviews": md_status.get("pending", 0),
            "in_review": md_status.get("in_review", 0),
            "completed_reviews": md_status.get("completed", 0),
            "protocol_deviations_identified": protocol_deviations,
            "standing_orders_requiring_attention": standing_orders_expiring,
            "status_breakdown": md_status,
        }

    @staticmethod
    async def get_qi_dashboard_data(db: AsyncSession, *, tenant_id: str) -> dict:
        """Compute QI dashboard data from real DB queries."""
        # Initiatives by status
        qi_result = await db.execute(
            select(QIInitiative.status, func.count().label("count"))
            .where(QIInitiative.tenant_id == tenant_id)
            .group_by(QIInitiative.status)
        )
        initiative_status = {row.status: row.count for row in qi_result}

        # Education effectiveness: completion rate
        edu_total = await db.execute(
            select(func.count()).where(EducationFollowUp.tenant_id == tenant_id)
        )
        edu_completed = await db.execute(
            select(func.count()).where(
                EducationFollowUp.tenant_id == tenant_id,
                EducationFollowUp.status == "completed",
            )
        )
        total_edu = edu_total.scalar() or 0
        completed_edu = edu_completed.scalar() or 0
        edu_completion_rate = round((completed_edu / total_edu * 100) if total_edu > 0 else 0.0, 1)

        return {
            "active_initiatives": initiative_status.get("active", 0) + initiative_status.get("follow_up", 0),
            "completed_initiatives": initiative_status.get("closed", 0),
            "identified_issues": initiative_status.get("identified", 0),
            "initiative_status_breakdown": initiative_status,
            "education_completion_rate": edu_completion_rate,
            "total_education_assigned": total_edu,
            "total_education_completed": completed_edu,
        }

    # =========================================================================
    # TREND AGGREGATION
    # =========================================================================

    @staticmethod
    async def compute_qa_trend_aggregation(
        db: AsyncSession,
        *,
        tenant_id: str,
        period: str,
        period_type: str = "month",
        computed_by: str = "system",
    ) -> QATrendAggregation:
        """Compute trend aggregation for a period. Idempotent upsert."""
        # Check existing
        existing = await db.execute(
            select(QATrendAggregation).where(
                QATrendAggregation.tenant_id == tenant_id,
                QATrendAggregation.period == period,
            )
        )
        trend = existing.scalar_one_or_none()

        # Compute real aggregates
        total_cases_result = await db.execute(
            select(func.count()).where(QACaseRecord.tenant_id == tenant_id)
        )
        total_cases = total_cases_result.scalar() or 0

        open_cases_result = await db.execute(
            select(func.count()).where(
                QACaseRecord.tenant_id == tenant_id,
                QACaseRecord.status.notin_(["closed", "appealed"]),
            )
        )
        open_cases = open_cases_result.scalar() or 0

        avg_score_result = await db.execute(
            select(func.avg(QACaseRecord.qa_score)).where(
                QACaseRecord.tenant_id == tenant_id,
                QACaseRecord.qa_score != None,  # noqa: E711
            )
        )
        avg_score = avg_score_result.scalar() or 0.0

        edu_assigned_result = await db.execute(
            select(func.count()).where(EducationFollowUp.tenant_id == tenant_id)
        )
        edu_assigned = edu_assigned_result.scalar() or 0

        edu_completed_result = await db.execute(
            select(func.count()).where(
                EducationFollowUp.tenant_id == tenant_id,
                EducationFollowUp.status == "completed",
            )
        )
        edu_completed = edu_completed_result.scalar() or 0

        md_escalations_result = await db.execute(
            select(func.count()).where(MedicalDirectorReview.tenant_id == tenant_id)
        )
        md_escalations = md_escalations_result.scalar() or 0

        peer_reviews_result = await db.execute(
            select(func.count()).where(
                PeerReview.tenant_id == tenant_id,
                PeerReview.status == "completed",
            )
        )
        peer_reviews = peer_reviews_result.scalar() or 0

        now = _now()
        if trend:
            trend.total_qa_cases = total_cases
            trend.total_open_cases = open_cases
            trend.avg_qa_score = round(avg_score, 2)
            trend.education_assignments = edu_assigned
            trend.education_completions = edu_completed
            trend.medical_director_escalations = md_escalations
            trend.peer_reviews_completed = peer_reviews
            trend.computed_at = now
        else:
            trend = QATrendAggregation(
                id=_new_id(),
                tenant_id=tenant_id,
                period=period,
                period_type=period_type,
                total_qa_cases=total_cases,
                total_open_cases=open_cases,
                avg_qa_score=round(avg_score, 2),
                education_assignments=edu_assigned,
                education_completions=edu_completed,
                medical_director_escalations=md_escalations,
                peer_reviews_completed=peer_reviews,
                computed_at=now,
                created_by=computed_by,
                created_at=now,
            )
            db.add(trend)

        await db.commit()
        await db.refresh(trend)
        return trend

    # =========================================================================
    # ACCREDITATION EVIDENCE
    # =========================================================================

    @staticmethod
    async def generate_accreditation_package(
        db: AsyncSession,
        *,
        tenant_id: str,
        package_name: str,
        accreditation_type: str,
        period_start: datetime,
        period_end: datetime,
        generated_by: str,
        generated_by_role: str,
    ) -> AccreditationEvidencePackage:
        """Compile accreditation evidence from real quality module data."""
        # QA evidence
        qa_cases_result = await db.execute(
            select(func.count()).where(
                QACaseRecord.tenant_id == tenant_id,
                QACaseRecord.created_at >= period_start,
                QACaseRecord.created_at <= period_end,
            )
        )
        qa_cases_total = qa_cases_result.scalar() or 0

        closed_cases_result = await db.execute(
            select(func.count()).where(
                QACaseRecord.tenant_id == tenant_id,
                QACaseRecord.status == "closed",
                QACaseRecord.created_at >= period_start,
                QACaseRecord.created_at <= period_end,
            )
        )
        qa_cases_closed = closed_cases_result.scalar() or 0

        avg_score_result = await db.execute(
            select(func.avg(QACaseRecord.qa_score)).where(
                QACaseRecord.tenant_id == tenant_id,
                QACaseRecord.qa_score != None,  # noqa: E711
                QACaseRecord.created_at >= period_start,
                QACaseRecord.created_at <= period_end,
            )
        )
        avg_score = avg_score_result.scalar() or 0.0

        # QI evidence
        qi_result = await db.execute(
            select(func.count()).where(
                QIInitiative.tenant_id == tenant_id,
                QIInitiative.start_date >= period_start,
                QIInitiative.start_date <= period_end,
            )
        )
        qi_total = qi_result.scalar() or 0

        # Peer review evidence
        pr_result = await db.execute(
            select(func.count()).where(
                PeerReview.tenant_id == tenant_id,
                PeerReview.status == "completed",
                PeerReview.created_at >= period_start,
                PeerReview.created_at <= period_end,
            )
        )
        pr_completed = pr_result.scalar() or 0

        # Education evidence
        edu_total_result = await db.execute(
            select(func.count()).where(
                EducationFollowUp.tenant_id == tenant_id,
                EducationFollowUp.created_at >= period_start,
                EducationFollowUp.created_at <= period_end,
            )
        )
        edu_total = edu_total_result.scalar() or 0

        edu_completed_result = await db.execute(
            select(func.count()).where(
                EducationFollowUp.tenant_id == tenant_id,
                EducationFollowUp.status == "completed",
                EducationFollowUp.created_at >= period_start,
                EducationFollowUp.created_at <= period_end,
            )
        )
        edu_completed = edu_completed_result.scalar() or 0

        now = _now()
        package = AccreditationEvidencePackage(
            id=_new_id(),
            tenant_id=tenant_id,
            package_name=package_name,
            accreditation_type=accreditation_type,
            period_start=period_start,
            period_end=period_end,
            status="compiled",
            generated_by=generated_by,
            qa_evidence_json=_json_dumps({
                "total_cases": qa_cases_total,
                "closed_cases": qa_cases_closed,
                "avg_composite_score": round(avg_score, 2),
                "closure_rate": round((qa_cases_closed / qa_cases_total * 100) if qa_cases_total > 0 else 0, 1),
            }),
            qi_evidence_json=_json_dumps({
                "total_initiatives": qi_total,
            }),
            peer_review_summary_json=_json_dumps({
                "completed_peer_reviews": pr_completed,
            }),
            education_completion_json=_json_dumps({
                "total_assigned": edu_total,
                "total_completed": edu_completed,
                "completion_rate": round((edu_completed / edu_total * 100) if edu_total > 0 else 0, 1),
            }),
            protocol_compliance_json=_json_dumps({}),
            compiled_at=now,
            created_by=generated_by,
            created_at=now,
            updated_by=generated_by,
            updated_at=now,
        )
        db.add(package)

        await QualityService.emit_audit_event(
            db,
            tenant_id=tenant_id,
            actor_id=generated_by,
            actor_role=generated_by_role,
            event_type="accreditation_package_generated",
            reference_type="accreditation_package",
            reference_id=package.id,
            metadata={
                "accreditation_type": accreditation_type,
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
            },
        )
        await db.commit()
        await db.refresh(package)
        return package
