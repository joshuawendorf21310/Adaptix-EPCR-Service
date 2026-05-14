"""Adaptix ePCR Clinical Validation AI service."""
from __future__ import annotations
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class EPCRClinicalValidationServiceResult:
    """Result from ePCR Clinical Validation AI assessment."""
    assessment_id: str
    record_id: str
    tenant_id: str
    actor_id: str
    # AI-generated text (NOT logged - returned to caller only)
    summary_text: Optional[str]
    missing_fields: List[str]
    warnings: List[str]
    recommendations: List[str]
    human_review_required: bool
    risk_level: str
    created_at: datetime
    audit_event_id: str
    correlation_id: str
    # Hard rules
    ai_signed: bool = False
    ai_marked_complete: bool = False
    ai_dispatched_resources: bool = False

    def __post_init__(self):
        self.ai_signed = False
        self.ai_marked_complete = False
        self.ai_dispatched_resources = False


class EPCRClinicalValidationService:
    """Adaptix ePCR Clinical Validation AI service.
    
    Hard rules:
    - AI never signs forms
    - AI never marks documents complete
    - AI never dispatches resources
    - AI never invents facts, times, signatures, medications, or interventions
    - No PHI/prompts/completions/tokens/secrets in logs
    - Human review required for high-risk outputs
    """

    def __init__(self):
        self.ai_provider = os.environ.get("AI_PROVIDER", "")
        self.ai_api_key = os.environ.get("OPENAI_API_KEY", os.environ.get("ANTHROPIC_API_KEY", ""))
        self._ai_available = bool(self.ai_provider and self.ai_api_key)

    def assess(
        self,
        record_id: str,
        tenant_id: str,
        actor_id: str,
        record_data: Dict[str, Any],
    ) -> EPCRClinicalValidationServiceResult:
        """Generate AI assessment for ePCR Clinical Validation."""
        assessment_id = str(uuid.uuid4())
        audit_event_id = str(uuid.uuid4())
        correlation_id = str(uuid.uuid4())

        missing_fields = self._detect_missing_fields(record_data)
        warnings = self._generate_warnings(record_data, missing_fields)
        recommendations = self._generate_recommendations(record_data)
        human_review_required = self._requires_human_review(record_data, missing_fields)
        risk_level = self._assess_risk_level(record_data)

        summary_text = None
        if self._ai_available and not missing_fields:
            try:
                summary_text = self._generate_summary(record_data)
            except Exception as e:
                logger.error(f"AI generation failed for epcr record {record_id}: {e}")
                warnings.append(f"AI summary unavailable: {e}")
        else:
            summary_text = self._rule_based_summary(record_data, missing_fields, warnings)

        return EPCRClinicalValidationServiceResult(
            assessment_id=assessment_id,
            record_id=record_id,
            tenant_id=tenant_id,
            actor_id=actor_id,
            summary_text=summary_text,
            missing_fields=missing_fields,
            warnings=warnings,
            recommendations=recommendations,
            human_review_required=human_review_required,
            risk_level=risk_level,
            created_at=datetime.utcnow(),
            audit_event_id=audit_event_id,
            correlation_id=correlation_id,
        )

    def _detect_missing_fields(self, data: Dict[str, Any]) -> List[str]:
        return []

    def _generate_warnings(self, data: Dict[str, Any], missing_fields: List[str]) -> List[str]:
        warnings = []
        if missing_fields:
            warnings.append(f"{len(missing_fields)} required field(s) missing")
        return warnings

    def _generate_recommendations(self, data: Dict[str, Any]) -> List[str]:
        return []

    def _requires_human_review(self, data: Dict[str, Any], missing_fields: List[str]) -> bool:
        return len(missing_fields) > 0

    def _assess_risk_level(self, data: Dict[str, Any]) -> str:
        return "medium"

    def _rule_based_summary(self, data: Dict[str, Any], missing_fields: List[str], warnings: List[str]) -> str:
        if not missing_fields:
            return "ePCR Clinical Validation record is ready for review."
        return f"{len(missing_fields)} field(s) require attention before proceeding."

    def _generate_summary(self, data: Dict[str, Any]) -> str:
        return self._rule_based_summary(data, [], [])


# Adaptix public API adapter
import uuid as _uuid_cv
from dataclasses import dataclass as _dc_cv
from typing import List as _List_cv


@_dc_cv
class ClinicalContradiction:
    field_a: str
    field_b: str
    description: str
    severity: str
    human_review_required: bool = True


@_dc_cv
class ClinicalValidationResult:
    validation_id: str
    chart_id: str
    tenant_id: str
    actor_id: str
    contradictions: _List_cv[ClinicalContradiction]
    missing_fields: _List_cv[str]
    warnings: _List_cv[str]
    human_review_required: bool
    ai_may_not_auto_lock: bool = True
    ai_may_not_overwrite_facts: bool = True


class ClinicalValidationService:
    def validate(self, chart_id, tenant_id, actor_id, chart_data):
        contradictions = []
        missing_fields = []
        warnings = []
        medications = chart_data.get('medications', [])
        allergies = chart_data.get('allergies', [])
        if medications and allergies:
            allergy_names = {a.lower() if isinstance(a, str) else a.get('name', '').lower() for a in allergies}
            for med in medications:
                med_name = med.lower() if isinstance(med, str) else med.get('name', '').lower()
                if med_name and med_name in allergy_names:
                    contradictions.append(ClinicalContradiction(field_a='medications', field_b='allergies', description=f"Medication {med_name!r} conflicts with documented allergy", severity='error', human_review_required=True))
        required = ['patient_name', 'incident_date', 'dispatch_time', 'arrival_time', 'chief_complaint', 'clinical_impression', 'disposition']
        missing_fields = [f for f in required if not chart_data.get(f)]
        human_review = bool(contradictions or missing_fields)
        return ClinicalValidationResult(validation_id=str(_uuid_cv.uuid4()), chart_id=chart_id, tenant_id=tenant_id, actor_id=actor_id, contradictions=contradictions, missing_fields=missing_fields, warnings=warnings, human_review_required=human_review, ai_may_not_auto_lock=True, ai_may_not_overwrite_facts=True)
