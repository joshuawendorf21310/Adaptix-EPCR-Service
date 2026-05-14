from __future__ import annotations
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List
import uuid

logger = logging.getLogger(__name__)


@dataclass
class BillingReadinessResult:
    assessment_id: str
    chart_id: str
    tenant_id: str
    ready_for_billing: bool
    missing_billing_fields: List[str]
    medical_necessity_complete: bool
    payer_info_complete: bool
    nemsis_export_required: bool
    blocking_reasons: List[str]
    recommendations: List[str]
    human_review_required: bool = True
    assessed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class BillingReadinessService:
    REQUIRED_BILLING_FIELDS = [
        'patient_name', 'date_of_birth', 'incident_date',
        'chief_complaint', 'clinical_impression', 'disposition',
        'origin', 'destination', 'level_of_care',
        'payer', 'medical_necessity_reason',
    ]

    def assess(self, chart_id, tenant_id, chart_data):
        assessment_id = str(uuid.uuid4())
        missing = [f for f in self.REQUIRED_BILLING_FIELDS if not chart_data.get(f)]
        blocking = []
        recommendations = []
        if missing:
            blocking.append('Missing required billing fields: ' + ', '.join(missing))
        payer_complete = bool(chart_data.get('payer') and chart_data.get('member_id'))
        if not payer_complete:
            blocking.append('Payer information incomplete')
            recommendations.append('Verify payer and member ID before billing submission')
        med_necessity = bool(chart_data.get('medical_necessity_reason'))
        if not med_necessity:
            blocking.append('Medical necessity documentation missing')
            recommendations.append('Document medical necessity reason for transport/service')
        nemsis_required = chart_data.get('service_type', '').lower() in ('ems', 'transport', 'air_medical')
        return BillingReadinessResult(
            assessment_id=assessment_id, chart_id=chart_id, tenant_id=tenant_id,
            ready_for_billing=len(blocking) == 0, missing_billing_fields=missing,
            medical_necessity_complete=med_necessity, payer_info_complete=payer_complete,
            nemsis_export_required=nemsis_required, blocking_reasons=blocking,
            recommendations=recommendations, human_review_required=True,
        )
