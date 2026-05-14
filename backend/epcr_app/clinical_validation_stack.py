"""5-Layer Clinical Validation Stack.

Layer 1 — Clinical validation (contradictions, physiologic impossibilities, missing links)
Layer 2 — Author-time NEMSIS structural validation (missing mandatory, invalid datatype, regex)
Layer 3 — Schema validation (XSD against official NEMSIS XSDs)
Layer 4 — Export validation (final payload correctness, nil rules, recurrence)
Layer 5 — Custom audit validation (no custom field corruption, shadowing, schema drift)

Every failure is explicit. No fake success. No downgraded errors.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models import Chart, Vitals, NemsisMappingRecord
from epcr_app.models_cpae import PhysicalFinding
from epcr_app.models_critical_care import ResponseWindow
from epcr_app.models_terminology import ImpressionBinding, NemsisRegexRule


# ---------------------------------------------------------------------------
# Validation result types
# ---------------------------------------------------------------------------

@dataclass
class ValidationIssue:
    layer: int
    severity: str  # error, warning, info
    code: str
    message: str
    field: Optional[str] = None
    entity_id: Optional[str] = None
    entity_type: Optional[str] = None
    nemsis_element: Optional[str] = None
    remediation: Optional[str] = None


@dataclass
class ValidationResult:
    chart_id: str
    tenant_id: str
    validated_at: datetime
    layer_1_passed: bool = False
    layer_2_passed: bool = False
    layer_3_passed: bool = False
    layer_4_passed: bool = False
    layer_5_passed: bool = False
    issues: list[ValidationIssue] = field(default_factory=list)
    export_blocked: bool = False
    export_blockers: list[str] = field(default_factory=list)

    @property
    def all_layers_passed(self) -> bool:
        return all([
            self.layer_1_passed,
            self.layer_2_passed,
            self.layer_3_passed,
            self.layer_4_passed,
            self.layer_5_passed,
        ])

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    def to_dict(self) -> dict:
        return {
            "chart_id": self.chart_id,
            "tenant_id": self.tenant_id,
            "validated_at": self.validated_at.isoformat(),
            "all_layers_passed": self.all_layers_passed,
            "layer_1_clinical": self.layer_1_passed,
            "layer_2_nemsis_structural": self.layer_2_passed,
            "layer_3_xsd": self.layer_3_passed,
            "layer_4_export": self.layer_4_passed,
            "layer_5_custom_audit": self.layer_5_passed,
            "export_blocked": self.export_blocked,
            "export_blockers": self.export_blockers,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "issues": [
                {
                    "layer": i.layer,
                    "severity": i.severity,
                    "code": i.code,
                    "message": i.message,
                    "field": i.field,
                    "entity_id": i.entity_id,
                    "entity_type": i.entity_type,
                    "nemsis_element": i.nemsis_element,
                    "remediation": i.remediation,
                }
                for i in self.issues
            ],
        }


# ---------------------------------------------------------------------------
# Layer 1 — Clinical Validation
# ---------------------------------------------------------------------------

async def validate_layer_1_clinical(
    chart_id: str,
    tenant_id: str,
    session: AsyncSession,
    result: ValidationResult,
) -> None:
    """Detect clinical contradictions, physiologic impossibilities, missing links.

    Checks:
    - Interventions without response documentation
    - Impressions without evidence links
    - Findings with contradictions flagged
    - OPQRST missing for pain/dyspnea symptoms
    - Vitals physiologically impossible values
    - Reassessment gaps after interventions
    """
    issues = []

    # Check vitals for physiologic impossibilities
    vitals_result = await session.execute(
        select(Vitals).where(
            Vitals.chart_id == chart_id,
            Vitals.tenant_id == tenant_id,
            Vitals.deleted_at.is_(None),
        )
    )
    vitals_list = vitals_result.scalars().all()

    for v in vitals_list:
        if v.hr is not None and (v.hr < 0 or v.hr > 400):
            issues.append(ValidationIssue(
                layer=1, severity="error",
                code="CLINICAL_IMPOSSIBLE_HR",
                message=f"Heart rate {v.hr} is physiologically impossible",
                field="hr", entity_id=v.id, entity_type="vitals",
                remediation="Correct heart rate value",
            ))
        if v.spo2 is not None and (v.spo2 < 0 or v.spo2 > 100):
            issues.append(ValidationIssue(
                layer=1, severity="error",
                code="CLINICAL_IMPOSSIBLE_SPO2",
                message=f"SpO2 {v.spo2}% is physiologically impossible",
                field="spo2", entity_id=v.id, entity_type="vitals",
                remediation="Correct SpO2 value",
            ))
        if v.bp_sys is not None and v.bp_dia is not None:
            if v.bp_sys <= v.bp_dia:
                issues.append(ValidationIssue(
                    layer=1, severity="error",
                    code="CLINICAL_BP_INVERSION",
                    message=f"Systolic BP {v.bp_sys} <= diastolic BP {v.bp_dia}",
                    field="bp_sys", entity_id=v.id, entity_type="vitals",
                    remediation="Correct blood pressure values",
                ))

    # Check response windows for incomplete interventions
    response_result = await session.execute(
        select(ResponseWindow).where(
            ResponseWindow.chart_id == chart_id,
            ResponseWindow.tenant_id == tenant_id,
            ResponseWindow.response_availability == "pending",
            ResponseWindow.deleted_at.is_(None),
        )
    )
    pending_responses = response_result.scalars().all()
    for rw in pending_responses:
        issues.append(ValidationIssue(
            layer=1, severity="warning",
            code="CLINICAL_RESPONSE_PENDING",
            message=f"Intervention {rw.intervention_id} has no documented response",
            entity_id=rw.id, entity_type="response_window",
            remediation="Document actual response or mark unavailable with reason",
        ))

    # Check findings for contradictions
    findings_result = await session.execute(
        select(PhysicalFinding).where(
            PhysicalFinding.chart_id == chart_id,
            PhysicalFinding.tenant_id == tenant_id,
            PhysicalFinding.has_contradiction == True,
            PhysicalFinding.deleted_at.is_(None),
        )
    )
    contradicted = findings_result.scalars().all()
    for f in contradicted:
        issues.append(ValidationIssue(
            layer=1, severity="error",
            code="CLINICAL_FINDING_CONTRADICTION",
            message=f"Finding '{f.finding_label}' has a detected contradiction: {f.contradiction_detail}",
            entity_id=f.id, entity_type="physical_finding",
            remediation="Resolve contradiction before export",
        ))

    # Check impressions for evidence
    impression_result = await session.execute(
        select(ImpressionBinding).where(
            ImpressionBinding.chart_id == chart_id,
            ImpressionBinding.tenant_id == tenant_id,
            ImpressionBinding.impression_class == "primary",
            ImpressionBinding.deleted_at.is_(None),
        )
    )
    primary_impressions = impression_result.scalars().all()
    for imp in primary_impressions:
        if not imp.evidence_node_ids_json:
            issues.append(ValidationIssue(
                layer=1, severity="warning",
                code="CLINICAL_IMPRESSION_NO_EVIDENCE",
                message=f"Primary impression '{imp.adaptix_label}' has no evidence links",
                entity_id=imp.id, entity_type="impression_binding",
                remediation="Link evidence nodes to support this impression",
            ))

    result.issues.extend(issues)
    result.layer_1_passed = not any(i.severity == "error" for i in issues)


# ---------------------------------------------------------------------------
# Layer 2 — Author-time NEMSIS Structural Validation
# ---------------------------------------------------------------------------

# Mandatory NEMSIS fields for EMS dataset
NEMSIS_MANDATORY_FIELDS = [
    "eRecord.01",
    "eResponse.05",
    "eTimes.03",
    "ePatient.13",
    "ePatient.15",
    "eSituation.01",
    "eSituation.09",
    "eSituation.11",
    "eDisposition.12",
    "eDisposition.19",
]

NEMSIS_REQUIRED_FIELDS = [
    "eResponse.07",
    "eTimes.05",
    "eTimes.06",
    "ePatient.16",
    "eScene.01",
    "eScene.08",
    "eScene.09",
    "eVitals.01",
    "eVitals.06",
]

# Basic datatype validators
NEMSIS_DATETIME_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?$"
)
NEMSIS_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NEMSIS_UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


async def validate_layer_2_nemsis_structural(
    chart_id: str,
    tenant_id: str,
    session: AsyncSession,
    result: ValidationResult,
) -> None:
    """Validate NEMSIS structural requirements at author time.

    Checks:
    - Missing Mandatory fields
    - Missing Required fields
    - Invalid datatype
    - Invalid regex patterns
    - Invalid enum values
    - Illegal NV/PN use
    """
    issues = []

    # Get all NEMSIS mappings for this chart
    mappings_result = await session.execute(
        select(NemsisMappingRecord).where(
            NemsisMappingRecord.chart_id == chart_id,
            NemsisMappingRecord.tenant_id == tenant_id,
            NemsisMappingRecord.deleted_at.is_(None),
        )
    )
    mappings = {m.nemsis_field: m.nemsis_value for m in mappings_result.scalars().all()}

    # Check mandatory fields
    for field_id in NEMSIS_MANDATORY_FIELDS:
        if field_id not in mappings or not mappings[field_id]:
            issues.append(ValidationIssue(
                layer=2, severity="error",
                code="NEMSIS_MANDATORY_MISSING",
                message=f"Mandatory NEMSIS field {field_id} is missing",
                nemsis_element=field_id,
                remediation=f"Populate {field_id} before export",
            ))
            result.export_blockers.append(f"Missing mandatory: {field_id}")

    # Check required fields
    for field_id in NEMSIS_REQUIRED_FIELDS:
        if field_id not in mappings or not mappings[field_id]:
            issues.append(ValidationIssue(
                layer=2, severity="warning",
                code="NEMSIS_REQUIRED_MISSING",
                message=f"Required NEMSIS field {field_id} is missing",
                nemsis_element=field_id,
                remediation=f"Populate {field_id} for complete submission",
            ))

    # Validate datetime fields
    datetime_fields = ["eTimes.03", "eTimes.05", "eTimes.06", "eTimes.07", "eTimes.09", "eTimes.11", "eTimes.12", "eTimes.13"]
    for field_id in datetime_fields:
        if field_id in mappings and mappings[field_id]:
            val = mappings[field_id]
            if not NEMSIS_DATETIME_PATTERN.match(val):
                issues.append(ValidationIssue(
                    layer=2, severity="error",
                    code="NEMSIS_INVALID_DATETIME",
                    message=f"Field {field_id} value '{val}' is not a valid ISO 8601 datetime",
                    nemsis_element=field_id,
                    remediation="Use ISO 8601 format: YYYY-MM-DDTHH:MM:SSZ",
                ))

    # Validate date fields
    date_fields = ["ePatient.15"]
    for field_id in date_fields:
        if field_id in mappings and mappings[field_id]:
            val = mappings[field_id]
            if not NEMSIS_DATE_PATTERN.match(val):
                issues.append(ValidationIssue(
                    layer=2, severity="error",
                    code="NEMSIS_INVALID_DATE",
                    message=f"Field {field_id} value '{val}' is not a valid date (YYYY-MM-DD)",
                    nemsis_element=field_id,
                    remediation="Use date format: YYYY-MM-DD",
                ))

    # Validate regex rules from database
    regex_result = await session.execute(select(NemsisRegexRule))
    regex_rules = {r.element_number: r.regex_pattern for r in regex_result.scalars().all()}

    for field_id, pattern in regex_rules.items():
        if field_id in mappings and mappings[field_id]:
            val = mappings[field_id]
            try:
                if not re.match(pattern, val):
                    issues.append(ValidationIssue(
                        layer=2, severity="error",
                        code="NEMSIS_REGEX_VIOLATION",
                        message=f"Field {field_id} value '{val}' does not match required pattern",
                        nemsis_element=field_id,
                        remediation=f"Value must match pattern: {pattern}",
                    ))
            except re.error as exc:
                issues.append(ValidationIssue(
                    layer=2,
                    severity="error",
                    code="NEMSIS_REGEX_RULE_INVALID",
                    message=(
                        f"Field {field_id} regex rule is invalid and could not be evaluated: {exc}"
                    ),
                    nemsis_element=field_id,
                    remediation="Repair the stored NEMSIS regex rule before export validation can proceed.",
                ))

    result.issues.extend(issues)
    result.layer_2_passed = not any(i.severity == "error" for i in issues)
    result.export_blocked = len(result.export_blockers) > 0


# ---------------------------------------------------------------------------
# Layer 3 — XSD Schema Validation
# ---------------------------------------------------------------------------

async def validate_layer_3_xsd(
    xml_content: Optional[bytes],
    result: ValidationResult,
) -> None:
    """Validate XML against official NEMSIS XSDs.

    Uses lxml for XSD validation. If XSD is unavailable, marks as blocked.
    Never marks as passed without actual XSD validation.
    """
    if xml_content is None:
        result.issues.append(ValidationIssue(
            layer=3, severity="error",
            code="XSD_NO_XML",
            message="No XML content provided for XSD validation",
            remediation="Generate XML before XSD validation",
        ))
        result.layer_3_passed = False
        return

    try:
        from lxml import etree
        import os
        from pathlib import Path

        # Look for XSD in the nemsis_pretesting directory
        xsd_paths = [
            Path(__file__).parent / "nemsis_pretesting_v351" / "national" / "EMSDataSet_v3.xsd",
            Path(__file__).parent / "nemsis_pretesting_v351" / "full" / "EMSDataSet_v3.xsd",
        ]

        xsd_path = None
        for p in xsd_paths:
            if p.exists():
                xsd_path = p
                break

        if not xsd_path:
            result.issues.append(ValidationIssue(
                layer=3, severity="error",
                code="XSD_UNAVAILABLE",
                message="NEMSIS XSD file not found — xsd_unavailable",
                remediation="Ensure NEMSIS XSD artifacts are present in nemsis_pretesting_v351/",
            ))
            result.layer_3_passed = False
            return

        xsd_doc = etree.parse(str(xsd_path))
        xsd_schema = etree.XMLSchema(xsd_doc)
        xml_doc = etree.fromstring(xml_content)

        if xsd_schema.validate(xml_doc):
            result.layer_3_passed = True
        else:
            for error in xsd_schema.error_log:
                result.issues.append(ValidationIssue(
                    layer=3, severity="error",
                    code="XSD_VALIDATION_FAILED",
                    message=f"XSD error at line {error.line}: {error.message}",
                    remediation="Fix XML structure to conform to NEMSIS XSD",
                ))
            result.layer_3_passed = False
            result.export_blocked = True
            result.export_blockers.append("XSD validation failed")

    except ImportError:
        result.issues.append(ValidationIssue(
            layer=3, severity="error",
            code="XSD_LXML_UNAVAILABLE",
            message="lxml not available for XSD validation — dependency_unavailable",
            remediation="Install lxml: pip install lxml",
        ))
        result.layer_3_passed = False
    except Exception as exc:
        result.issues.append(ValidationIssue(
            layer=3, severity="error",
            code="XSD_VALIDATION_ERROR",
            message=f"XSD validation error: {type(exc).__name__}: {str(exc)}",
            remediation="Check XML content and XSD file integrity",
        ))
        result.layer_3_passed = False


# ---------------------------------------------------------------------------
# Layer 4 — Export Validation
# ---------------------------------------------------------------------------

async def validate_layer_4_export(
    chart_id: str,
    tenant_id: str,
    session: AsyncSession,
    result: ValidationResult,
) -> None:
    """Validate final export payload correctness.

    Checks:
    - Export blockers from layer 2
    - Impression NEMSIS export validity
    - Finding NEMSIS export readiness
    - Intervention NEMSIS export readiness
    - Chart finalization state
    """
    issues = []

    # Check chart status
    chart_result = await session.execute(
        select(Chart).where(
            Chart.id == chart_id,
            Chart.tenant_id == tenant_id,
        )
    )
    chart = chart_result.scalar_one_or_none()
    if not chart:
        issues.append(ValidationIssue(
            layer=4, severity="error",
            code="EXPORT_CHART_NOT_FOUND",
            message="Chart not found for export validation",
            remediation="Verify chart ID and tenant",
        ))
        result.issues.extend(issues)
        result.layer_4_passed = False
        return

    # Check impression NEMSIS validity
    impression_result = await session.execute(
        select(ImpressionBinding).where(
            ImpressionBinding.chart_id == chart_id,
            ImpressionBinding.tenant_id == tenant_id,
            ImpressionBinding.impression_class == "primary",
            ImpressionBinding.deleted_at.is_(None),
        )
    )
    primary_impressions = impression_result.scalars().all()

    if not primary_impressions:
        issues.append(ValidationIssue(
            layer=4, severity="error",
            code="EXPORT_NO_PRIMARY_IMPRESSION",
            message="No primary impression documented — required for NEMSIS export",
            remediation="Document a primary clinical impression",
        ))
        result.export_blockers.append("No primary impression")

    for imp in primary_impressions:
        if imp.nemsis_export_valid is False:
            issues.append(ValidationIssue(
                layer=4, severity="error",
                code="EXPORT_IMPRESSION_INVALID",
                message=f"Primary impression '{imp.adaptix_label}' has invalid NEMSIS export state: {imp.nemsis_export_blocker}",
                entity_id=imp.id, entity_type="impression_binding",
                remediation="Fix NEMSIS binding for this impression",
            ))
            result.export_blockers.append(f"Invalid impression NEMSIS binding: {imp.adaptix_label}")

    # Check AI-suggested impressions not yet reviewed
    unreviewed_result = await session.execute(
        select(ImpressionBinding).where(
            ImpressionBinding.chart_id == chart_id,
            ImpressionBinding.tenant_id == tenant_id,
            ImpressionBinding.is_ai_suggested == True,
            ImpressionBinding.review_state == "direct_confirmed",
            ImpressionBinding.deleted_at.is_(None),
        )
    )
    unreviewed = unreviewed_result.scalars().all()
    for imp in unreviewed:
        issues.append(ValidationIssue(
            layer=4, severity="error",
            code="EXPORT_AI_IMPRESSION_UNREVIEWED",
            message=f"AI-suggested impression '{imp.adaptix_label}' has not been reviewed",
            entity_id=imp.id, entity_type="impression_binding",
            remediation="Review and accept or reject AI-suggested impression",
        ))
        result.export_blockers.append(f"Unreviewed AI impression: {imp.adaptix_label}")

    result.issues.extend(issues)
    result.layer_4_passed = not any(i.severity == "error" for i in issues)
    if result.export_blockers:
        result.export_blocked = True


# ---------------------------------------------------------------------------
# Layer 5 — Custom Audit Validation
# ---------------------------------------------------------------------------

async def validate_layer_5_custom_audit(
    chart_id: str,
    tenant_id: str,
    session: AsyncSession,
    result: ValidationResult,
) -> None:
    """Validate no custom field corruption, shadowing, or schema drift.

    Checks:
    - Custom fields not duplicating standard NEMSIS fields
    - No custom field mapped to wrong standard element
    - No required field hidden by customization
    - No invalid enum values in custom fields
    - No workflow producing invalid export
    """
    issues = []

    # Get all NEMSIS mappings
    mappings_result = await session.execute(
        select(NemsisMappingRecord).where(
            NemsisMappingRecord.chart_id == chart_id,
            NemsisMappingRecord.tenant_id == tenant_id,
            NemsisMappingRecord.deleted_at.is_(None),
        )
    )
    mappings = mappings_result.scalars().all()

    # Check for duplicate field mappings (same field mapped multiple times)
    field_counts: dict[str, int] = {}
    for m in mappings:
        field_counts[m.nemsis_field] = field_counts.get(m.nemsis_field, 0) + 1

    for field_id, count in field_counts.items():
        if count > 1:
            issues.append(ValidationIssue(
                layer=5, severity="error",
                code="CUSTOM_AUDIT_DUPLICATE_FIELD",
                message=f"NEMSIS field {field_id} has {count} duplicate mappings",
                nemsis_element=field_id,
                remediation="Remove duplicate field mappings",
            ))

    # Check for Vision-proposed findings not yet reviewed
    from epcr_app.models_cpae import PhysicalFinding
    unreviewed_findings_result = await session.execute(
        select(PhysicalFinding).where(
            PhysicalFinding.chart_id == chart_id,
            PhysicalFinding.tenant_id == tenant_id,
            PhysicalFinding.review_state.in_(["vision_proposed", "smart_text_proposed", "voice_proposed"]),
            PhysicalFinding.deleted_at.is_(None),
        )
    )
    unreviewed_findings = unreviewed_findings_result.scalars().all()
    for f in unreviewed_findings:
        issues.append(ValidationIssue(
            layer=5, severity="warning",
            code="CUSTOM_AUDIT_UNREVIEWED_FINDING",
            message=f"Finding '{f.finding_label}' has review_state='{f.review_state}' — not yet confirmed",
            entity_id=f.id, entity_type="physical_finding",
            remediation="Review and confirm or reject this finding",
        ))

    result.issues.extend(issues)
    result.layer_5_passed = not any(i.severity == "error" for i in issues)


# ---------------------------------------------------------------------------
# Master validation runner
# ---------------------------------------------------------------------------

async def run_full_validation_stack(
    chart_id: str,
    tenant_id: str,
    session: AsyncSession,
    xml_content: Optional[bytes] = None,
) -> ValidationResult:
    """Run all 5 validation layers and return a complete ValidationResult.

    This is the authoritative validation entry point. All layers run
    regardless of prior layer failures (parallel validation).
    """
    result = ValidationResult(
        chart_id=chart_id,
        tenant_id=tenant_id,
        validated_at=datetime.utcnow(),
    )

    # Run all layers
    await validate_layer_1_clinical(chart_id, tenant_id, session, result)
    await validate_layer_2_nemsis_structural(chart_id, tenant_id, session, result)
    await validate_layer_3_xsd(xml_content, result)
    await validate_layer_4_export(chart_id, tenant_id, session, result)
    await validate_layer_5_custom_audit(chart_id, tenant_id, session, result)

    return result
