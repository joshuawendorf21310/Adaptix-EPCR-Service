"""Desktop frontend API surface — review, QA, coding, admin, and export authority.

Desktop is the authoritative surface for:
- Chart review and supervisor QA
- Coding review and billing readiness
- NEMSIS readiness dashboard
- Export preview and blocker list
- Mapping trace explorer
- XML preview
- Submission history
- Custom field audit console
- Agency workflow builder
- Role management
- Protocol configuration
- CareGraph replay
- Timeline replay
- VAS replay
- Training mode
- Legal reconstruction view

Desktop rules:
- Desktop edit must go through audit
- Admin configuration cannot break NEMSIS constraints
- Export blockers are NEVER hidden
- False readiness is NEVER presented
- Generated narrative is NEVER treated as source truth
"""
from __future__ import annotations

import json
from datetime import datetime, UTC
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.dependencies import get_current_user, get_tenant_id
from epcr_app.models import (
    Chart, ChartStatus, NemsisCompliance, ComplianceStatus,
    NemsisMappingRecord, EpcrAuditLog,
)
from epcr_app.models_terminology import ImpressionBinding
from epcr_app.models_cpae import PhysicalFinding
from epcr_app.models_vision import VisionReviewQueue
from epcr_app.models_sync import SyncConflict
from epcr_app.clinical_validation_stack import run_full_validation_stack

router = APIRouter(prefix="/api/v1/epcr/desktop", tags=["desktop"])


# ===========================================================================
# Supervisor QA Queue
# ===========================================================================

@router.get("/qa/queue")
async def get_qa_queue(
    status_filter: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Get supervisor QA queue — charts requiring review.

    Returns charts in under_review or finalized state for QA.
    Export blockers are always surfaced — never hidden.
    """
    q = select(Chart).where(
        Chart.tenant_id == tenant_id,
        Chart.deleted_at.is_(None),
    )
    if status_filter:
        try:
            q = q.where(Chart.status == ChartStatus(status_filter))
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid status: {status_filter}")
    else:
        q = q.where(Chart.status.in_([ChartStatus.UNDER_REVIEW, ChartStatus.FINALIZED]))

    q = q.order_by(Chart.updated_at.desc()).limit(limit).offset(offset)
    result = await session.execute(q)
    charts = result.scalars().all()

    return {
        "charts": [
            {
                "id": c.id,
                "call_number": c.call_number,
                "incident_type": c.incident_type,
                "status": c.status,
                "created_by_user_id": c.created_by_user_id,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
                "finalized_at": c.finalized_at.isoformat() if c.finalized_at else None,
            }
            for c in charts
        ],
        "count": len(charts),
        "limit": limit,
        "offset": offset,
    }


# ===========================================================================
# NEMSIS Readiness Dashboard
# ===========================================================================

@router.get("/nemsis/readiness-dashboard")
async def get_nemsis_readiness_dashboard(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """NEMSIS readiness dashboard for the tenant.

    Shows compliance status distribution across all charts.
    Export blockers are NEVER hidden.
    False readiness is NEVER presented.
    """
    result = await session.execute(
        select(
            NemsisCompliance.compliance_status,
            func.count(NemsisCompliance.id).label("count"),
        ).where(
            NemsisCompliance.tenant_id == tenant_id,
            NemsisCompliance.deleted_at.is_(None),
        ).group_by(NemsisCompliance.compliance_status)
    )
    rows = result.all()

    status_counts = {row.compliance_status: row.count for row in rows}
    total = sum(status_counts.values())
    fully_compliant = status_counts.get(ComplianceStatus.FULLY_COMPLIANT, 0)

    return {
        "tenant_id": tenant_id,
        "total_charts_with_compliance": total,
        "fully_compliant": fully_compliant,
        "partially_compliant": status_counts.get(ComplianceStatus.PARTIALLY_COMPLIANT, 0),
        "non_compliant": status_counts.get(ComplianceStatus.NON_COMPLIANT, 0),
        "not_started": status_counts.get(ComplianceStatus.NOT_STARTED, 0),
        "in_progress": status_counts.get(ComplianceStatus.IN_PROGRESS, 0),
        "compliance_rate_pct": round((fully_compliant / total * 100) if total > 0 else 0, 1),
        "export_blocked_count": status_counts.get(ComplianceStatus.NON_COMPLIANT, 0),
    }


# ===========================================================================
# Chart Review — Full Detail
# ===========================================================================

@router.get("/charts/{chart_id}/review")
async def get_chart_review(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Full chart review surface for desktop QA.

    Returns complete chart state including:
    - Chart metadata
    - NEMSIS compliance state
    - Physical findings count
    - Impression bindings
    - Unreviewed Vision proposals
    - Sync conflicts
    - Audit trail summary
    - Export blockers (NEVER hidden)
    """
    # Chart
    chart_result = await session.execute(
        select(Chart).where(
            Chart.id == chart_id,
            Chart.tenant_id == tenant_id,
            Chart.deleted_at.is_(None),
        )
    )
    chart = chart_result.scalar_one_or_none()
    if not chart:
        raise HTTPException(status_code=404, detail="chart_not_found")

    # NEMSIS compliance
    compliance_result = await session.execute(
        select(NemsisCompliance).where(
            NemsisCompliance.chart_id == chart_id,
            NemsisCompliance.tenant_id == tenant_id,
        )
    )
    compliance = compliance_result.scalar_one_or_none()

    # Physical findings
    findings_result = await session.execute(
        select(func.count(PhysicalFinding.id)).where(
            PhysicalFinding.chart_id == chart_id,
            PhysicalFinding.tenant_id == tenant_id,
            PhysicalFinding.deleted_at.is_(None),
        )
    )
    findings_count = findings_result.scalar() or 0

    # Unreviewed Vision proposals
    vision_result = await session.execute(
        select(func.count(VisionReviewQueue.id)).where(
            VisionReviewQueue.chart_id == chart_id,
            VisionReviewQueue.tenant_id == tenant_id,
            VisionReviewQueue.queue_state.in_(["pending", "in_review"]),
        )
    )
    unreviewed_vision = vision_result.scalar() or 0

    # Sync conflicts
    conflicts_result = await session.execute(
        select(func.count(SyncConflict.id)).where(
            SyncConflict.chart_id == chart_id,
            SyncConflict.tenant_id == tenant_id,
            SyncConflict.resolved_at.is_(None),
        )
    )
    unresolved_conflicts = conflicts_result.scalar() or 0

    # Impression bindings
    impressions_result = await session.execute(
        select(ImpressionBinding).where(
            ImpressionBinding.chart_id == chart_id,
            ImpressionBinding.tenant_id == tenant_id,
            ImpressionBinding.deleted_at.is_(None),
        )
    )
    impressions = impressions_result.scalars().all()

    # Audit log count
    audit_result = await session.execute(
        select(func.count(EpcrAuditLog.id)).where(
            EpcrAuditLog.chart_id == chart_id,
            EpcrAuditLog.tenant_id == tenant_id,
        )
    )
    audit_count = audit_result.scalar() or 0

    # Export blockers — NEVER hidden
    export_blockers = []
    if compliance:
        if compliance.compliance_status == ComplianceStatus.NON_COMPLIANT:
            missing = json.loads(compliance.missing_mandatory_fields or "[]")
            export_blockers.extend([f"Missing mandatory: {f}" for f in missing])
    if unreviewed_vision > 0:
        export_blockers.append(f"{unreviewed_vision} unreviewed Vision proposals")
    if unresolved_conflicts > 0:
        export_blockers.append(f"{unresolved_conflicts} unresolved sync conflicts")

    return {
        "chart": {
            "id": chart.id,
            "call_number": chart.call_number,
            "incident_type": chart.incident_type,
            "status": chart.status,
            "version": chart.version,
            "created_at": chart.created_at.isoformat() if chart.created_at else None,
            "finalized_at": chart.finalized_at.isoformat() if chart.finalized_at else None,
        },
        "nemsis_compliance": {
            "status": compliance.compliance_status if compliance else "not_started",
            "mandatory_fields_filled": compliance.mandatory_fields_filled if compliance else 0,
            "mandatory_fields_required": compliance.mandatory_fields_required if compliance else 0,
            "missing_mandatory_fields": json.loads(compliance.missing_mandatory_fields or "[]") if compliance else [],
        },
        "clinical_summary": {
            "physical_findings_count": findings_count,
            "impressions_count": len(impressions),
            "primary_impressions": [
                {
                    "adaptix_label": imp.adaptix_label,
                    "snomed_code": imp.snomed_code,
                    "icd10_code": imp.icd10_code,
                    "nemsis_value": imp.nemsis_value,
                    "review_state": imp.review_state,
                }
                for imp in impressions if imp.impression_class == "primary"
            ],
        },
        "review_gates": {
            "unreviewed_vision_proposals": unreviewed_vision,
            "unresolved_sync_conflicts": unresolved_conflicts,
        },
        "export_blockers": export_blockers,
        "export_blocked": len(export_blockers) > 0,
        "audit_event_count": audit_count,
    }


# ===========================================================================
# 5-Layer Validation — Desktop Surface
# ===========================================================================

@router.post("/charts/{chart_id}/validate")
async def run_chart_validation(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Run the full 5-layer validation stack on a chart.

    Layers:
    1. Clinical validation (contradictions, physiologic impossibilities)
    2. NEMSIS structural validation (mandatory/required fields, regex)
    3. XSD schema validation (against official NEMSIS XSDs)
    4. Export validation (impression validity, AI review gates)
    5. Custom audit validation (duplicate fields, unreviewed proposals)

    Export blockers are NEVER hidden.
    False readiness is NEVER presented.
    """
    result = await run_full_validation_stack(
        chart_id=chart_id,
        tenant_id=tenant_id,
        session=session,
        xml_content=None,  # XSD validation requires XML — skipped without it
    )
    return result.to_dict()


# ===========================================================================
# Mapping Trace Explorer
# ===========================================================================

@router.get("/charts/{chart_id}/nemsis-mappings")
async def get_nemsis_mappings(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Get all NEMSIS field mappings for a chart with provenance.

    Used by the desktop mapping trace explorer to show exactly which
    fields are mapped, their values, and their sources.
    """
    result = await session.execute(
        select(NemsisMappingRecord).where(
            NemsisMappingRecord.chart_id == chart_id,
            NemsisMappingRecord.tenant_id == tenant_id,
            NemsisMappingRecord.deleted_at.is_(None),
        ).order_by(NemsisMappingRecord.nemsis_field)
    )
    mappings = result.scalars().all()

    return {
        "chart_id": chart_id,
        "mappings": [
            {
                "id": m.id,
                "nemsis_field": m.nemsis_field,
                "nemsis_value": m.nemsis_value,
                "source": m.source,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "updated_at": m.updated_at.isoformat() if m.updated_at else None,
                "version": m.version,
            }
            for m in mappings
        ],
        "count": len(mappings),
    }


# ===========================================================================
# Audit Trail — Desktop View
# ===========================================================================

@router.get("/charts/{chart_id}/audit-trail")
async def get_chart_audit_trail(
    chart_id: str,
    limit: int = 100,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Get the complete audit trail for a chart.

    Used for legal reconstruction, QA review, and compliance verification.
    Audit trail is immutable — never modified.
    """
    result = await session.execute(
        select(EpcrAuditLog).where(
            EpcrAuditLog.chart_id == chart_id,
            EpcrAuditLog.tenant_id == tenant_id,
        ).order_by(EpcrAuditLog.performed_at.desc()).limit(limit).offset(offset)
    )
    events = result.scalars().all()

    return {
        "chart_id": chart_id,
        "audit_events": [
            {
                "id": e.id,
                "action": e.action,
                "user_id": e.user_id,
                "detail_json": e.detail_json,
                "performed_at": e.performed_at.isoformat() if e.performed_at else None,
            }
            for e in events
        ],
        "count": len(events),
        "limit": limit,
        "offset": offset,
    }


# ===========================================================================
# Derived Output — Desktop View (narrative is derived, never truth)
# ===========================================================================

@router.get("/charts/{chart_id}/derived-outputs")
async def get_derived_outputs(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Get derived outputs for a chart.

    Derived outputs include: narrative, handoff summary, clinical summary,
    billing justification, QA summary, training replay.

    IMPORTANT: Derived outputs are NEVER the source of truth.
    They are generated FROM structured CareGraph state.
    """
    from epcr_app.models import DerivedChartOutput
    result = await session.execute(
        select(DerivedChartOutput).where(
            DerivedChartOutput.chart_id == chart_id,
            DerivedChartOutput.tenant_id == tenant_id,
            DerivedChartOutput.deleted_at.is_(None),
        ).order_by(DerivedChartOutput.generated_at.desc())
    )
    outputs = result.scalars().all()

    return {
        "chart_id": chart_id,
        "derived_outputs": [
            {
                "id": o.id,
                "output_type": o.output_type,
                "content_text": o.content_text,
                "source_revision": o.source_revision,
                "generated_at": o.generated_at.isoformat() if o.generated_at else None,
                "generated_by_user_id": o.generated_by_user_id,
                "is_authoritative_truth": False,  # ALWAYS False — narrative is derived output only
            }
            for o in outputs
        ],
        "count": len(outputs),
        "note": "Derived outputs are generated from structured CareGraph state. They are NEVER the source of truth.",
    }
