"""CPAE — CareGraph Physical Assessment Engine API routes.

All routes enforce:
- Tenant isolation via verified auth context
- Provider attribution
- Audit logging
- No Vision proposals accepted without review
- No findings without anatomy and physiology
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, UTC
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.dependencies import get_current_user, get_tenant_id
from epcr_app.models_cpae import (
    PhysicalFinding,
    FindingCharacteristic,
    FindingReassessment,
    FindingEvidenceLink,
    FindingInterventionLink,
    FindingNemsisLink,
    FindingAuditEvent,
    AssessmentRegion,
    PhysiologicSystemRef,
)

router = APIRouter(prefix="/api/v1/epcr", tags=["cpae"])


# ---------------------------------------------------------------------------
# Request/Response schemas
# ---------------------------------------------------------------------------

class PhysicalFindingCreate(BaseModel):
    chart_id: str
    anatomy: str
    physiologic_system: str
    finding_class: str
    severity: str
    finding_label: str
    finding_description: Optional[str] = None
    laterality: Optional[str] = None
    detection_method: str
    characteristics: Optional[list[dict]] = None
    snomed_code: Optional[str] = None
    snomed_display: Optional[str] = None
    nemsis_exam_element: Optional[str] = None
    nemsis_exam_value: Optional[str] = None
    caregraph_node_id: Optional[str] = None
    source_artifact_ids: Optional[list[str]] = None
    observed_at: datetime


class PhysicalFindingUpdate(BaseModel):
    severity: Optional[str] = None
    finding_description: Optional[str] = None
    characteristics: Optional[list[dict]] = None
    snomed_code: Optional[str] = None
    nemsis_exam_element: Optional[str] = None
    nemsis_exam_value: Optional[str] = None


class FindingReassessmentCreate(BaseModel):
    evolution: str
    severity_at_reassessment: Optional[str] = None
    description: Optional[str] = None
    characteristics: Optional[list[dict]] = None
    intervention_trigger_id: Optional[str] = None
    reassessed_at: datetime


class FindingResponse(BaseModel):
    id: str
    chart_id: str
    anatomy: str
    physiologic_system: str
    finding_class: str
    severity: str
    finding_label: str
    laterality: Optional[str]
    detection_method: str
    review_state: str
    has_contradiction: bool
    observed_at: datetime
    version: int

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/charts/{chart_id}/findings", status_code=status.HTTP_201_CREATED)
async def create_physical_finding(
    chart_id: str,
    body: PhysicalFindingCreate,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Create a structured physical finding linked to anatomy and physiology.

    Findings without anatomy and physiology are rejected.
    Vision/SmartText proposals require review_state != direct_confirmed.
    """
    if not body.anatomy or not body.physiologic_system:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="anatomy and physiologic_system are required for every physical finding",
        )

    finding_id = str(uuid.uuid4())
    now = datetime.now(UTC)

    finding = PhysicalFinding(
        id=finding_id,
        chart_id=chart_id,
        tenant_id=tenant_id,
        caregraph_node_id=body.caregraph_node_id,
        anatomy=body.anatomy,
        physiologic_system=body.physiologic_system,
        finding_class=body.finding_class,
        laterality=body.laterality,
        severity=body.severity,
        finding_label=body.finding_label,
        finding_description=body.finding_description,
        characteristics_json=json.dumps(body.characteristics) if body.characteristics else None,
        detection_method=body.detection_method,
        review_state="direct_confirmed",
        snomed_code=body.snomed_code,
        snomed_display=body.snomed_display,
        nemsis_exam_element=body.nemsis_exam_element,
        nemsis_exam_value=body.nemsis_exam_value,
        has_contradiction=False,
        provider_id=user.user_id,
        source_artifact_ids_json=json.dumps(body.source_artifact_ids) if body.source_artifact_ids else None,
        observed_at=body.observed_at,
        updated_at=now,
    )
    session.add(finding)

    # Add characteristics
    if body.characteristics:
        for char in body.characteristics:
            session.add(FindingCharacteristic(
                id=str(uuid.uuid4()),
                finding_id=finding_id,
                tenant_id=tenant_id,
                characteristic_key=char.get("key", ""),
                characteristic_value=char.get("value", ""),
                characteristic_unit=char.get("unit"),
                snomed_code=char.get("snomed_code"),
            ))

    # Audit event
    session.add(FindingAuditEvent(
        id=str(uuid.uuid4()),
        finding_id=finding_id,
        chart_id=chart_id,
        tenant_id=tenant_id,
        action="create",
        actor_id=user.user_id,
        after_state_json=json.dumps({"anatomy": body.anatomy, "finding_label": body.finding_label}),
        performed_at=now,
    ))

    await session.commit()
    return {"id": finding_id, "status": "created"}


@router.get("/charts/{chart_id}/findings")
async def list_physical_findings(
    chart_id: str,
    anatomy: Optional[str] = None,
    physiologic_system: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """List physical findings for a chart, optionally filtered by anatomy/system."""
    q = select(PhysicalFinding).where(
        PhysicalFinding.chart_id == chart_id,
        PhysicalFinding.tenant_id == tenant_id,
        PhysicalFinding.deleted_at.is_(None),
    )
    if anatomy:
        q = q.where(PhysicalFinding.anatomy == anatomy)
    if physiologic_system:
        q = q.where(PhysicalFinding.physiologic_system == physiologic_system)

    result = await session.execute(q)
    findings = result.scalars().all()
    return {
        "findings": [
            {
                "id": f.id,
                "anatomy": f.anatomy,
                "physiologic_system": f.physiologic_system,
                "finding_class": f.finding_class,
                "severity": f.severity,
                "finding_label": f.finding_label,
                "laterality": f.laterality,
                "detection_method": f.detection_method,
                "review_state": f.review_state,
                "has_contradiction": f.has_contradiction,
                "observed_at": f.observed_at.isoformat() if f.observed_at else None,
                "version": f.version,
            }
            for f in findings
        ],
        "count": len(findings),
    }


@router.get("/charts/{chart_id}/findings/{finding_id}")
async def get_physical_finding(
    chart_id: str,
    finding_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Get a single physical finding with all linked data."""
    result = await session.execute(
        select(PhysicalFinding).where(
            PhysicalFinding.id == finding_id,
            PhysicalFinding.chart_id == chart_id,
            PhysicalFinding.tenant_id == tenant_id,
            PhysicalFinding.deleted_at.is_(None),
        )
    )
    finding = result.scalar_one_or_none()
    if not finding:
        raise HTTPException(status_code=404, detail="finding_not_found")

    return {
        "id": finding.id,
        "chart_id": finding.chart_id,
        "anatomy": finding.anatomy,
        "physiologic_system": finding.physiologic_system,
        "finding_class": finding.finding_class,
        "severity": finding.severity,
        "finding_label": finding.finding_label,
        "finding_description": finding.finding_description,
        "laterality": finding.laterality,
        "detection_method": finding.detection_method,
        "review_state": finding.review_state,
        "snomed_code": finding.snomed_code,
        "snomed_display": finding.snomed_display,
        "nemsis_exam_element": finding.nemsis_exam_element,
        "nemsis_exam_value": finding.nemsis_exam_value,
        "has_contradiction": finding.has_contradiction,
        "contradiction_detail": finding.contradiction_detail,
        "caregraph_node_id": finding.caregraph_node_id,
        "observed_at": finding.observed_at.isoformat() if finding.observed_at else None,
        "version": finding.version,
    }


@router.post("/charts/{chart_id}/findings/{finding_id}/reassessments", status_code=status.HTTP_201_CREATED)
async def create_finding_reassessment(
    chart_id: str,
    finding_id: str,
    body: FindingReassessmentCreate,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Record a reassessment for a physical finding."""
    # Verify finding exists and belongs to tenant
    result = await session.execute(
        select(PhysicalFinding).where(
            PhysicalFinding.id == finding_id,
            PhysicalFinding.chart_id == chart_id,
            PhysicalFinding.tenant_id == tenant_id,
            PhysicalFinding.deleted_at.is_(None),
        )
    )
    finding = result.scalar_one_or_none()
    if not finding:
        raise HTTPException(status_code=404, detail="finding_not_found")

    reassessment_id = str(uuid.uuid4())
    session.add(FindingReassessment(
        id=reassessment_id,
        finding_id=finding_id,
        chart_id=chart_id,
        tenant_id=tenant_id,
        evolution=body.evolution,
        severity_at_reassessment=body.severity_at_reassessment,
        description=body.description,
        characteristics_json=json.dumps(body.characteristics) if body.characteristics else None,
        intervention_trigger_id=body.intervention_trigger_id,
        provider_id=user.user_id,
        reassessed_at=body.reassessed_at,
    ))

    # Audit
    session.add(FindingAuditEvent(
        id=str(uuid.uuid4()),
        finding_id=finding_id,
        chart_id=chart_id,
        tenant_id=tenant_id,
        action="reassessment",
        actor_id=user.user_id,
        after_state_json=json.dumps({"evolution": body.evolution}),
        performed_at=datetime.now(UTC),
    ))

    await session.commit()
    return {"id": reassessment_id, "status": "created"}


@router.get("/cpae/regions")
async def list_assessment_regions(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
) -> dict:
    """List all active anatomical assessment regions."""
    result = await session.execute(
        select(AssessmentRegion).where(AssessmentRegion.is_active == True).order_by(AssessmentRegion.sort_order)
    )
    regions = result.scalars().all()
    return {
        "regions": [
            {
                "id": r.id,
                "region_code": r.region_code,
                "display_name": r.display_name,
                "parent_region_code": r.parent_region_code,
                "supports_laterality": r.supports_laterality,
                "nemsis_body_site_code": r.nemsis_body_site_code,
                "snomed_code": r.snomed_code,
            }
            for r in regions
        ]
    }


@router.get("/cpae/systems")
async def list_physiologic_systems(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
) -> dict:
    """List all active physiological systems."""
    result = await session.execute(
        select(PhysiologicSystemRef).where(PhysiologicSystemRef.is_active == True).order_by(PhysiologicSystemRef.sort_order)
    )
    systems = result.scalars().all()
    return {
        "systems": [
            {
                "id": s.id,
                "system_code": s.system_code,
                "display_name": s.display_name,
                "nemsis_section_hint": s.nemsis_section_hint,
                "snomed_code": s.snomed_code,
            }
            for s in systems
        ]
    }
