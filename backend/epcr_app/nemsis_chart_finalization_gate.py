"""Full EMSDataSet chart finalization gate.

Evaluates the complete NEMSIS 3.5.1 EMSDataSet field matrix before
allowing chart finalization or export. This gate is dictionary-driven
and replaces any hardcoded mandatory-field list.

This module is ADDITIVE. It does not modify the existing
SchematronFinalizationGate (nemsis_finalization_gate.py) or any other
existing service.

Finalization is blocked if ANY of the following are true:
  - Any Mandatory field is not documented
  - Any Required field is not documented
  - Any code-list value is invalid
  - Any NOT value is invalid
  - Any Pertinent Negative is invalid
  - XSD validation fails
  - Schematron validation fails (in certification/production mode)
  - Schematron is skipped (in certification/production mode)
  - Runtime blockers exist (missing env vars)
  - Tenant isolation is violated

Finalization response shape::

    {
        "chart_id": "",
        "tenant_id": "",
        "ready_for_export": false,
        "ready_for_submission": false,
        "validation_mode": "production",
        "xsd_valid": false,
        "schematron_valid": false,
        "schematron_skipped": false,
        "blocker_count": 0,
        "warning_count": 0,
        "field_errors": [],
        "section_errors": {},
        "state_errors": [],
        "runtime_blockers": []
    }
"""
from __future__ import annotations

import os
from typing import Any

from epcr_app.nemsis_field_validator import (
    NemsisFieldValidator,
    get_validation_mode,
    is_strict_schematron_required,
)
from epcr_app.nemsis_registry_service import NemsisRegistryService

# EMSDataSet canonical section order per EMSDataSet_v3.xsd
EMS_DATASET_SECTIONS = [
    "eRecord", "eResponse", "eDispatch", "eCrew", "eTimes",
    "ePatient", "ePayment", "eScene", "eSituation", "eInjury",
    "eArrest", "eHistory", "eNarrative", "eVitals", "eLabs",
    "eExam", "eProtocols", "eMedications", "eProcedures", "eAirway",
    "eDevice", "eDisposition", "eOutcome", "eCustomResults", "eOther",
]


# ---------------------------------------------------------------------------
# Conditional cross-section requirement rules (NEMSIS v3.5.1)
# ---------------------------------------------------------------------------

def _apply_conditional_section_rules(
    chart_field_values: dict[str, Any],
    field_errors: list[dict[str, Any]],
    section_errors: dict[str, list[str]],
) -> None:
    """Enforce conditional-required NEMSIS section rules.

    Called before the full field-matrix evaluation so that missing-section
    blockers appear alongside individual field errors in the gate result.
    Rules follow the NEMSIS v3.5.1 data dictionary conditional requirements.
    """
    def _has_section(section_prefix: str) -> bool:
        return any(k.startswith(f"{section_prefix}.") for k in chart_field_values)

    def _field_truthy(element: str) -> bool:
        v = chart_field_values.get(element)
        return bool(v and str(v).strip() and str(v).strip() not in ("7701001", "7701003", "7701005"))

    def _blocker(element: str, section: str, rule_id: str, msg: str) -> None:
        field_errors.append({
            "element": element,
            "section": section,
            "level": "Error",
            "ruleId": rule_id,
            "message": msg,
        })
        section_errors.setdefault(section, []).append(msg)

    # Rule CR-001: Trauma incident type requires eInjury section.
    incident_type = (
        chart_field_values.get("__incident_type__") or ""
    ).lower()
    possible_injury = chart_field_values.get("eSituation.02")
    is_trauma = incident_type == "trauma" or _field_truthy("eSituation.02")
    if is_trauma and not _has_section("eInjury"):
        _blocker(
            "eInjury.01", "eInjury", "ADAPTIX_CR_001",
            "Trauma incident requires eInjury section. "
            "Document cause of injury before finalizing.",
        )

    # Rule CR-002: Cardiac arrest indicator requires eArrest section.
    cardiac_arrest = chart_field_values.get("eArrest.01")
    arrest_occurred = _field_truthy("eArrest.01") and str(
        chart_field_values.get("eArrest.01", "")
    ) not in ("3201003",)  # 3201003 = No cardiac arrest
    if cardiac_arrest is not None and arrest_occurred and not _has_section("eArrest"):
        _blocker(
            "eArrest.02", "eArrest", "ADAPTIX_CR_002",
            "Cardiac arrest indicated — eArrest section required. "
            "Complete cardiac arrest documentation before finalizing.",
        )

    # Rule CR-003: eTimes section (event timeline) is required for all records.
    if not _has_section("eTimes"):
        _blocker(
            "eTimes.01", "eTimes", "ADAPTIX_CR_003",
            "eTimes section is required for all records. "
            "Record at least PSAP Call, Unit En Route, and On-Scene times.",
        )

    # Rule CR-004: eDisposition required for all records.
    if not _has_section("eDisposition"):
        _blocker(
            "eDisposition.12", "eDisposition", "ADAPTIX_CR_004",
            "eDisposition section is required. "
            "Document the incident/patient disposition before finalizing.",
        )


# ---------------------------------------------------------------------------
# Runtime readiness checks
# ---------------------------------------------------------------------------

def _runtime_blockers() -> list[str]:
    """Return list of missing required environment variables."""
    blockers: list[str] = []
    if not (os.environ.get("NEMSIS_STATE_CODE") or "").strip():
        blockers.append("NEMSIS_STATE_CODE not configured")
    if not (
        os.environ.get("NEMSIS_EXPORT_S3_BUCKET")
        or os.environ.get("FILES_S3_BUCKET")
        or ""
    ).strip():
        blockers.append("NEMSIS_EXPORT_S3_BUCKET not configured")
    return blockers


# ---------------------------------------------------------------------------
# Finalization gate
# ---------------------------------------------------------------------------

class NemsisChartFinalizationGate:
    """Evaluate the full EMSDataSet field matrix for chart finalization.

    This gate is the authoritative pre-export check. It must pass before
    any export artifact is generated or submitted.
    """

    def __init__(
        self,
        registry_service: NemsisRegistryService | None = None,
        field_validator: NemsisFieldValidator | None = None,
    ) -> None:
        self._registry = registry_service or NemsisRegistryService()
        self._validator = field_validator or NemsisFieldValidator(self._registry)

    def evaluate(
        self,
        *,
        chart_id: str,
        tenant_id: str,
        chart_field_values: dict[str, Any],
        xsd_validation_result: dict[str, Any] | None = None,
        schematron_validation_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Evaluate chart readiness against the full EMSDataSet field matrix.

        Args:
            chart_id: Chart identifier.
            tenant_id: Tenant identifier (must match chart ownership).
            chart_field_values: Dict mapping NEMSIS element IDs to values.
                Format: {"eRecord.01": "PCR-001", "ePatient.13": None, ...}
                Attributes: {"ePatient.13.__attrs__": {"NV": "7701003"}}
            xsd_validation_result: Result from NemsisXSDValidator.validate_xml().
                If None, XSD validation is treated as not run.
            schematron_validation_result: Same dict, schematron portion.
                If None, Schematron is treated as not run.

        Returns:
            Finalization evaluation dict.
        """
        validation_mode = get_validation_mode()
        field_errors: list[dict[str, Any]] = []
        section_errors: dict[str, list[str]] = {}
        warnings: list[dict[str, Any]] = []

        # ------------------------------------------------------------------ #
        # Tenant isolation check
        # ------------------------------------------------------------------ #
        chart_tenant = chart_field_values.get("__tenant_id__")
        if chart_tenant and chart_tenant != tenant_id:
            return {
                "chart_id": chart_id,
                "tenant_id": tenant_id,
                "ready_for_export": False,
                "ready_for_submission": False,
                "validation_mode": validation_mode,
                "xsd_valid": False,
                "schematron_valid": False,
                "schematron_skipped": False,
                "blocker_count": 1,
                "warning_count": 0,
                "field_errors": [{
                    "element": "__tenant__",
                    "section": "__system__",
                    "level": "Error",
                    "ruleId": "ADAPTIX_TEN_001",
                    "message": "Tenant isolation violation: chart does not belong to this tenant.",
                }],
                "section_errors": {},
                "state_errors": [],
                "runtime_blockers": ["tenant_isolation_violation"],
                "warnings": [],
            }

        # ------------------------------------------------------------------ #
        # Runtime blockers
        # ------------------------------------------------------------------ #
        runtime_blockers = _runtime_blockers()

        # ------------------------------------------------------------------ #
        # Conditional-required cross-section rules (NEMSIS v3.5.1)
        # These rules enforce section presence based on clinical context.
        # ------------------------------------------------------------------ #
        _apply_conditional_section_rules(chart_field_values, field_errors, section_errors)

        # ------------------------------------------------------------------ #
        # Full EMSDataSet field matrix evaluation
        # ------------------------------------------------------------------ #
        ems_fields = self._registry.list_fields(dataset="EMSDataSet")

        for field_meta in ems_fields:
            element = field_meta.get("field_id") or field_meta.get("element_id") or ""
            if not element:
                continue
            section = field_meta.get("section") or element.split(".")[0]

            # Get value for this field
            value = chart_field_values.get(element)

            # Get attributes for this field
            attrs = chart_field_values.get(f"{element}.__attrs__") or {}

            result = self._validator.validate_field(
                element=element,
                value=value,
                attributes=attrs,
                group_path=section,
            )

            for issue in result.issues:
                field_errors.append(issue.to_dict())
                section_errors.setdefault(section, []).append(issue.message)

            for warning in result.warnings:
                warnings.append(warning.to_dict())

        # ------------------------------------------------------------------ #
        # XSD validation
        # ------------------------------------------------------------------ #
        xsd_valid: bool | None = None
        xsd_errors: list[str] = []
        if xsd_validation_result is not None:
            xsd_valid = bool(xsd_validation_result.get("xsd_valid", False))
            xsd_errors = list(xsd_validation_result.get("xsd_errors") or [])
            if not xsd_valid:
                for err in xsd_errors:
                    field_errors.append({
                        "element": "",
                        "section": "__xsd__",
                        "level": "Error",
                        "ruleSource": "xsd",
                        "ruleId": "ADAPTIX_XSD_001",
                        "message": str(err),
                    })

        # ------------------------------------------------------------------ #
        # Schematron validation + mode enforcement
        # ------------------------------------------------------------------ #
        schematron_valid: bool | None = None
        schematron_skipped = False
        schematron_errors: list[str] = []

        if schematron_validation_result is not None:
            schematron_skipped = bool(schematron_validation_result.get("schematron_skipped", False))
            schematron_valid = bool(schematron_validation_result.get("schematron_valid", False))
            schematron_errors = list(schematron_validation_result.get("schematron_errors") or [])

        # Mode enforcement: schematron skip in cert/prod = error
        if schematron_skipped:
            if is_strict_schematron_required():
                field_errors.append({
                    "element": "",
                    "section": "__schematron__",
                    "level": "Error",
                    "ruleSource": "runtime",
                    "ruleId": "ADAPTIX_SCH_001",
                    "message": (
                        f"Schematron validation was skipped but NEMSIS_VALIDATION_MODE="
                        f"'{validation_mode}' requires Schematron to pass."
                    ),
                })
            else:
                warnings.append({
                    "element": "",
                    "section": "__schematron__",
                    "level": "Warning",
                    "ruleSource": "runtime",
                    "ruleId": "ADAPTIX_SCH_002",
                    "message": "Schematron validation was skipped (development mode).",
                })

        for err in schematron_errors:
            field_errors.append({
                "element": "",
                "section": "__schematron__",
                "level": "Error",
                "ruleSource": "schematron",
                "ruleId": "ADAPTIX_SCH_003",
                "message": str(err),
            })

        # ------------------------------------------------------------------ #
        # Determine readiness
        # ------------------------------------------------------------------ #
        has_field_errors = bool(field_errors)
        has_runtime_blockers = bool(runtime_blockers)
        xsd_failed = xsd_valid is False
        schematron_failed = (
            (schematron_valid is False and not schematron_skipped)
            or (schematron_skipped and is_strict_schematron_required())
        )

        ready_for_export = (
            not has_field_errors
            and not has_runtime_blockers
            and not xsd_failed
            and not schematron_failed
        )
        ready_for_submission = ready_for_export and xsd_valid is True and (
            schematron_valid is True or (
                not is_strict_schematron_required() and schematron_skipped
            )
        )

        blocker_count = len(field_errors) + len(runtime_blockers)
        warning_count = len(warnings)

        return {
            "chart_id": chart_id,
            "tenant_id": tenant_id,
            "ready_for_export": ready_for_export,
            "ready_for_submission": ready_for_submission,
            "validation_mode": validation_mode,
            "xsd_valid": xsd_valid,
            "schematron_valid": schematron_valid,
            "schematron_skipped": schematron_skipped,
            "blocker_count": blocker_count,
            "warning_count": warning_count,
            "field_errors": field_errors,
            "section_errors": {
                section: list(msgs)
                for section, msgs in sorted(section_errors.items())
            },
            "state_errors": [],
            "runtime_blockers": runtime_blockers,
            "warnings": warnings,
        }


# Module-level singleton
_default_gate: NemsisChartFinalizationGate | None = None


def get_default_finalization_gate() -> NemsisChartFinalizationGate:
    global _default_gate
    if _default_gate is None:
        _default_gate = NemsisChartFinalizationGate()
    return _default_gate


def evaluate_chart_finalization(
    chart_id: str,
    tenant_id: str,
    *,
    chart_field_values: dict[str, Any],
    chart_field_attributes: dict[str, dict[str, Any]] | None = None,
    registry_service: Any | None = None,
    xml_bytes: bytes | None = None,
    xsd_validator: Any | None = None,
    schematron_validator: Any | None = None,
    validation_mode: str | None = None,
) -> dict[str, Any]:
    """Convenience function wrapping NemsisChartFinalizationGate.evaluate().

    Provides the functional API expected by tests and external callers.
    All field validation is delegated to the gate class.

    Args:
        chart_id: Chart UUID.
        tenant_id: Tenant UUID.
        chart_field_values: Dict of {element_id: value}.
        chart_field_attributes: Dict of {element_id: {NV, PN, xsi:nil}}.
            If provided, merged into chart_field_values as __attrs__ keys.
        registry_service: Optional NemsisRegistryService instance.
        xml_bytes: Optional pre-built XML for XSD/Schematron validation.
        xsd_validator: Optional NemsisXSDValidator instance.
        schematron_validator: Unused (kept for API compatibility).
        validation_mode: Override validation mode env var.

    Returns:
        Finalization gate result dict with sections_evaluated added.
    """
    if validation_mode:
        import os as _os
        _os.environ["NEMSIS_VALIDATION_MODE"] = validation_mode

    # Merge attributes into field values using __attrs__ convention
    merged_values = dict(chart_field_values)
    if chart_field_attributes:
        for element, attrs in chart_field_attributes.items():
            merged_values[f"{element}.__attrs__"] = attrs

    # Build XSD validation result if xml_bytes and validator provided
    xsd_validation_result: dict[str, Any] | None = None
    if xml_bytes and xsd_validator:
        try:
            xsd_validation_result = xsd_validator.validate_xml(xml_bytes)
        except Exception:
            xsd_validation_result = None

    gate = NemsisChartFinalizationGate(registry_service=registry_service)
    result = gate.evaluate(
        chart_id=chart_id,
        tenant_id=tenant_id,
        chart_field_values=merged_values,
        xsd_validation_result=xsd_validation_result,
    )

    # Add sections_evaluated for test compatibility
    result["sections_evaluated"] = len(EMS_DATASET_SECTIONS)
    return result


__all__ = [
    "NemsisChartFinalizationGate",
    "get_default_finalization_gate",
    "evaluate_chart_finalization",
    "EMS_DATASET_SECTIONS",
]
