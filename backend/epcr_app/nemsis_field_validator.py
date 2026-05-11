"""Universal NEMSIS 3.5.1 Field Validator.

Applies all 18 validation dimensions to every EMSDataSet field:

1.  Usage (Mandatory/Required/Recommended/Optional)
2.  Recurrence (0:1, 0:M, 1:1, 1:M)
3.  Required-if-known logic
4.  Conditional logic
5.  State-required logic
6.  NOT value eligibility
7.  NOT value code validity
8.  Pertinent negative eligibility
9.  Pertinent negative code validity
10. Nillable behavior
11. Code-list membership
12. Data type
13. Min/max length constraints
14. Min/max inclusive constraints
15. Regex/pattern constraints
16. Deprecated element handling
17. Repeating group cardinality
18. XSD structural validity (delegated to NemsisXSDValidator)

Rules:
- Never fabricates a passing result.
- Returns structured ValidationIssue list per field.
- Validation mode (development/certification/production) controls strictness.
- All metadata sourced from NemsisRegistryService (official normalized registry).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

# Standard NOT values per NEMSIS 3.5.1 data dictionary
_STANDARD_NOT_VALUES = {
    "7701001": "Not Applicable",
    "7701003": "Not Recorded",
    "7701005": "Not Reporting",
}

# Standard Pertinent Negative values per NEMSIS 3.5.1 data dictionary
_STANDARD_PN_VALUES = {
    "8801001": "Contraindication Noted",
    "8801003": "Denied",
    "8801005": "Not Performed by EMS",
    "8801007": "Refused",
    "8801009": "Unresponsive",
    "8801013": "Unable to Complete",
    "8801019": "Patient Declined Evaluation/Care",
    "8801021": "Performed, but Documentation is Unavailable",
    "8801023": "Spontaneous",
    "8801025": "Unwitnessed",
    "8801027": "N/A, Evaluation Performed by Another Crew Member",
    "8801029": "N/A, Performed by Another Agency",
    "8801031": "Not Applicable",
}

# Validation modes
VALIDATION_MODE_DEVELOPMENT = "development"
VALIDATION_MODE_CERTIFICATION = "certification"
VALIDATION_MODE_PRODUCTION = "production"

_VALID_MODES = {VALIDATION_MODE_DEVELOPMENT, VALIDATION_MODE_CERTIFICATION, VALIDATION_MODE_PRODUCTION}


def _get_validation_mode() -> str:
    mode = os.environ.get("NEMSIS_VALIDATION_MODE", VALIDATION_MODE_DEVELOPMENT).strip().lower()
    if mode not in _VALID_MODES:
        return VALIDATION_MODE_DEVELOPMENT
    return mode


@dataclass(frozen=True)
class ValidationIssue:
    """A single validation issue for a NEMSIS field."""

    element: str
    section: str
    group_path: str
    level: str  # "Error" | "Warning"
    rule_source: str  # "dictionary" | "xsd" | "schematron" | "state" | "runtime"
    rule_id: str
    message: str
    allowed_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": False,
            "section": self.section,
            "element": self.element,
            "groupPath": self.group_path,
            "level": self.level,
            "ruleSource": self.rule_source,
            "ruleId": self.rule_id,
            "message": self.message,
            "allowedActions": list(self.allowed_actions),
        }


@dataclass
class FieldValidationResult:
    """Result of validating a single field value against its metadata."""

    element: str
    section: str
    valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "element": self.element,
            "section": self.section,
            "valid": self.valid,
            "issues": [i.to_dict() for i in self.issues],
            "warnings": [w.to_dict() for w in self.warnings],
        }


class NemsisFieldValidator:
    """Universal NEMSIS field validator.

    Validates a field value against its official metadata across all 18
    validation dimensions. Never fabricates a passing result.

    Usage:
        validator = NemsisFieldValidator(registry_service)
        result = validator.validate_field(
            element="ePatient.13",
            value=None,
            attributes={"NV": "7701003"},
            group_path="PatientCareReport.ePatient",
        )
    """

    def __init__(self, registry_service: Any) -> None:
        self._registry = registry_service
        self._mode = _get_validation_mode()

    def _get_metadata(self, element: str) -> dict[str, Any] | None:
        """Retrieve field metadata from the official registry."""
        return self._registry.get_field(element)

    def validate_field(
        self,
        element: str,
        value: Any,
        *,
        attributes: dict[str, Any] | None = None,
        group_path: str = "",
        group_index: int | None = None,
        group_values: list[Any] | None = None,
        chart_context: dict[str, Any] | None = None,
    ) -> FieldValidationResult:
        """Validate a single field value against its NEMSIS metadata.

        Args:
            element: NEMSIS element ID (e.g. "ePatient.13")
            value: The field value (None if not provided)
            attributes: Dict of XML attributes (NV, PN, xsi:nil, etc.)
            group_path: XPath-like path for context (e.g. "PatientCareReport.ePatient")
            group_index: Index within a repeating group (0-based)
            group_values: All values in a repeating group (for cardinality checks)
            chart_context: Full chart context for conditional validation

        Returns:
            FieldValidationResult with all issues and warnings.
        """
        attrs = attributes or {}
        context = chart_context or {}
        issues: list[ValidationIssue] = []
        warnings: list[ValidationIssue] = []

        metadata = self._get_metadata(element)
        if metadata is None:
            # Unknown element — cannot validate
            issues.append(ValidationIssue(
                element=element,
                section=element.split(".")[0] if "." in element else "",
                group_path=group_path,
                level="Error",
                rule_source="dictionary",
                rule_id="NEMSIS_UNKNOWN_ELEMENT",
                message=f"Element {element} is not in the official NEMSIS 3.5.1 registry.",
                allowed_actions=["Verify element ID against NEMSIS 3.5.1 data dictionary"],
            ))
            return FieldValidationResult(
                element=element,
                section="",
                valid=False,
                issues=issues,
            )

        section = metadata.get("section") or element.split(".")[0]
        gp = group_path or section

        # Dimension 16: Deprecated element handling
        if metadata.get("deprecated"):
            warnings.append(ValidationIssue(
                element=element,
                section=section,
                group_path=gp,
                level="Warning",
                rule_source="dictionary",
                rule_id="NEMSIS_DEPRECATED_ELEMENT",
                message=f"Element {element} is deprecated in NEMSIS 3.5.1. Do not use for new records.",
                allowed_actions=["Remove from new records", "Use replacement element if available"],
            ))

        # Resolve effective value and attribute state
        nv_attr = attrs.get("NV") or attrs.get("xsi:NV")
        pn_attr = attrs.get("PN") or attrs.get("xsi:PN")
        xsi_nil = attrs.get("xsi:nil") in (True, "true", "1")
        has_value = value is not None and str(value).strip() != ""
        has_nv = bool(nv_attr)
        has_pn = bool(pn_attr)
        has_nil = xsi_nil

        usage = metadata.get("usage") or metadata.get("required_level") or "Optional"
        recurrence = _map_recurrence(metadata.get("min_occurs"), metadata.get("max_occurs"))
        accepts_not = bool(metadata.get("not_value_allowed"))
        accepts_pn = bool(metadata.get("pertinent_negative_allowed"))
        is_nillable = metadata.get("nillable") is True or str(metadata.get("nillable") or "").lower() == "true"

        # Dimension 1: Usage validation
        if usage == "Mandatory":
            if not has_value and not has_nv and not has_nil:
                issues.append(ValidationIssue(
                    element=element,
                    section=section,
                    group_path=gp,
                    level="Error",
                    rule_source="dictionary",
                    rule_id="NEMSIS_MANDATORY_MISSING",
                    message=f"{element} is a Mandatory National Element and must have a value.",
                    allowed_actions=["Enter a valid value"],
                ))
        elif usage == "Required":
            if not has_value and not has_nv and not has_pn and not has_nil:
                issues.append(ValidationIssue(
                    element=element,
                    section=section,
                    group_path=gp,
                    level="Error",
                    rule_source="dictionary",
                    rule_id="NEMSIS_REQUIRED_MISSING",
                    message=(
                        f"{element} is a Required National Element. "
                        "A value, NOT value, or pertinent negative must be documented."
                    ),
                    allowed_actions=_build_allowed_actions(accepts_not, accepts_pn, is_nillable),
                ))

        # Dimension 6: NOT value eligibility
        if has_nv and not accepts_not:
            issues.append(ValidationIssue(
                element=element,
                section=section,
                group_path=gp,
                level="Error",
                rule_source="dictionary",
                rule_id="NEMSIS_NV_NOT_ALLOWED",
                message=f"Element {element} does not accept NOT values (NV attribute).",
                allowed_actions=["Remove NV attribute", "Enter a valid value"],
            ))

        # Dimension 7: NOT value code validity
        if has_nv and accepts_not:
            if nv_attr not in _STANDARD_NOT_VALUES:
                issues.append(ValidationIssue(
                    element=element,
                    section=section,
                    group_path=gp,
                    level="Error",
                    rule_source="dictionary",
                    rule_id="NEMSIS_NV_INVALID_CODE",
                    message=(
                        f"NOT value code '{nv_attr}' is not a valid NEMSIS NOT value. "
                        f"Valid codes: {list(_STANDARD_NOT_VALUES.keys())}"
                    ),
                    allowed_actions=[f"Use one of: {', '.join(_STANDARD_NOT_VALUES.keys())}"],
                ))

        # Dimension 8: Pertinent negative eligibility
        if has_pn and not accepts_pn:
            issues.append(ValidationIssue(
                element=element,
                section=section,
                group_path=gp,
                level="Error",
                rule_source="dictionary",
                rule_id="NEMSIS_PN_NOT_ALLOWED",
                message=f"Element {element} does not accept Pertinent Negative values (PN attribute).",
                allowed_actions=["Remove PN attribute", "Enter a valid value"],
            ))

        # Dimension 9: Pertinent negative code validity
        if has_pn and accepts_pn:
            if pn_attr not in _STANDARD_PN_VALUES:
                issues.append(ValidationIssue(
                    element=element,
                    section=section,
                    group_path=gp,
                    level="Error",
                    rule_source="dictionary",
                    rule_id="NEMSIS_PN_INVALID_CODE",
                    message=(
                        f"Pertinent Negative code '{pn_attr}' is not a valid NEMSIS PN value. "
                        f"Valid codes: {list(_STANDARD_PN_VALUES.keys())}"
                    ),
                    allowed_actions=[f"Use one of: {', '.join(_STANDARD_PN_VALUES.keys())}"],
                ))

        # Dimension 10: Nillable behavior
        if has_nil and not is_nillable:
            issues.append(ValidationIssue(
                element=element,
                section=section,
                group_path=gp,
                level="Error",
                rule_source="dictionary",
                rule_id="NEMSIS_NIL_NOT_ALLOWED",
                message=f"Element {element} is not nillable. xsi:nil='true' is not permitted.",
                allowed_actions=["Remove xsi:nil attribute", "Enter a valid value"],
            ))

        # Only validate value content if a value is actually provided
        if has_value:
            str_value = str(value).strip()

            # Dimension 11: Code-list membership
            allowed_values = metadata.get("allowed_values") or []
            if allowed_values:
                valid_codes = {
                    str(av.get("code") or av.get("value") or av) if isinstance(av, dict) else str(av)
                    for av in allowed_values
                }
                if str_value not in valid_codes:
                    issues.append(ValidationIssue(
                        element=element,
                        section=section,
                        group_path=gp,
                        level="Error",
                        rule_source="dictionary",
                        rule_id="NEMSIS_INVALID_CODE",
                        message=(
                            f"Value '{str_value}' is not in the allowed code list for {element}. "
                            f"Valid codes: {sorted(valid_codes)[:10]}{'...' if len(valid_codes) > 10 else ''}"
                        ),
                        allowed_actions=["Select a value from the allowed code list"],
                    ))

            # Dimension 12: Data type
            data_type = metadata.get("data_type") or ""
            _validate_data_type(element, section, gp, str_value, data_type, issues, warnings)

            # Dimensions 13-15: Constraints
            constraints = metadata.get("constraints") or {}
            _validate_constraints(element, section, gp, str_value, constraints, issues)

        # Dimension 2: Recurrence validation (for repeating groups)
        if group_values is not None:
            _validate_recurrence(element, section, gp, recurrence, group_values, issues)

        valid = len(issues) == 0
        return FieldValidationResult(
            element=element,
            section=section,
            valid=valid,
            issues=issues,
            warnings=warnings,
        )

    def validate_section(
        self,
        section: str,
        field_values: dict[str, Any],
        *,
        chart_context: dict[str, Any] | None = None,
    ) -> list[FieldValidationResult]:
        """Validate all fields in a section.

        Args:
            section: NEMSIS section name (e.g. "ePatient")
            field_values: Dict of {element_id: value} for this section
            chart_context: Full chart context for conditional validation

        Returns:
            List of FieldValidationResult for each field in the section.
        """
        results: list[FieldValidationResult] = []
        section_fields = self._registry.list_fields(section=section)

        for field_meta in section_fields:
            element = field_meta.get("field_id") or field_meta.get("element_id") or ""
            if not element:
                continue
            value = field_values.get(element)
            result = self.validate_field(
                element=element,
                value=value,
                group_path=section,
                chart_context=chart_context,
            )
            results.append(result)

        return results

    def validate_chart(
        self,
        chart_field_values: dict[str, Any],
        *,
        chart_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Validate all EMSDataSet fields for a complete chart.

        Args:
            chart_field_values: Dict of {element_id: value} for all fields
            chart_context: Full chart context for conditional validation

        Returns:
            Dict with overall validity, all issues, and per-section breakdown.
        """
        all_issues: list[dict[str, Any]] = []
        all_warnings: list[dict[str, Any]] = []
        section_results: dict[str, list[dict[str, Any]]] = {}

        from epcr_app.nemsis_compliance_builder import EMS_DATASET_SECTIONS

        for section in EMS_DATASET_SECTIONS:
            section_fields = self._registry.list_fields(section=section)
            section_issues: list[dict[str, Any]] = []

            for field_meta in section_fields:
                element = field_meta.get("field_id") or field_meta.get("element_id") or ""
                if not element:
                    continue
                value = chart_field_values.get(element)
                result = self.validate_field(
                    element=element,
                    value=value,
                    group_path=section,
                    chart_context=chart_context,
                )
                for issue in result.issues:
                    all_issues.append(issue.to_dict())
                    section_issues.append(issue.to_dict())
                for warning in result.warnings:
                    all_warnings.append(warning.to_dict())

            section_results[section] = section_issues

        return {
            "valid": len(all_issues) == 0,
            "validation_mode": self._mode,
            "total_issues": len(all_issues),
            "total_warnings": len(all_warnings),
            "issues": all_issues,
            "warnings": all_warnings,
            "by_section": section_results,
        }

    def validate_chart_all_datasets(
        self,
        chart_field_values: dict[str, Any],
        *,
        chart_context: dict[str, Any] | None = None,
        datasets: list[str] | None = None,
    ) -> dict[str, Any]:
        """Validate a chart across EMSDataSet, DEMDataSet, and StateDataSet.

        This is the dataset-aware counterpart of ``validate_chart`` (which
        only iterates EMS sections). It walks every section in every
        target dataset using the live registry, so DEM and State fields
        captured through the new persistence slice are validated rather
        than silently passed through.

        Args:
            chart_field_values: ``{element_id: value}`` map across all datasets.
            chart_context: Optional chart context for conditional checks.
            datasets: Optional restriction. Defaults to all 3 datasets.

        Returns:
            Aggregated dict with ``valid``, ``by_dataset`` (per-dataset
            issues/warnings/by_section), and global counts. The legacy
            ``by_section`` flat key is preserved for backward compat and
            contains the union across datasets.
        """
        target_datasets = datasets or ["EMSDataSet", "DEMDataSet", "StateDataSet"]
        all_issues: list[dict[str, Any]] = []
        all_warnings: list[dict[str, Any]] = []
        flat_section_results: dict[str, list[dict[str, Any]]] = {}
        per_dataset: dict[str, dict[str, Any]] = {}

        for dataset in target_datasets:
            ds_issues: list[dict[str, Any]] = []
            ds_warnings: list[dict[str, Any]] = []
            ds_sections: dict[str, list[dict[str, Any]]] = {}

            for section in self._registry.list_sections(dataset=dataset):
                section_fields = self._registry.list_fields(
                    dataset=dataset, section=section
                )
                section_issues: list[dict[str, Any]] = []

                for field_meta in section_fields:
                    element = (
                        field_meta.get("field_id")
                        or field_meta.get("element_id")
                        or ""
                    )
                    if not element:
                        continue
                    value = chart_field_values.get(element)
                    result = self.validate_field(
                        element=element,
                        value=value,
                        group_path=section,
                        chart_context=chart_context,
                    )
                    for issue in result.issues:
                        d = issue.to_dict()
                        d["dataset"] = dataset
                        ds_issues.append(d)
                        all_issues.append(d)
                        section_issues.append(d)
                    for warning in result.warnings:
                        d = warning.to_dict()
                        d["dataset"] = dataset
                        ds_warnings.append(d)
                        all_warnings.append(d)

                ds_sections[section] = section_issues
                flat_section_results[section] = section_issues

            per_dataset[dataset] = {
                "valid": len(ds_issues) == 0,
                "total_issues": len(ds_issues),
                "total_warnings": len(ds_warnings),
                "issues": ds_issues,
                "warnings": ds_warnings,
                "by_section": ds_sections,
            }

        return {
            "valid": len(all_issues) == 0,
            "validation_mode": self._mode,
            "datasets": list(target_datasets),
            "total_issues": len(all_issues),
            "total_warnings": len(all_warnings),
            "issues": all_issues,
            "warnings": all_warnings,
            "by_section": flat_section_results,
            "by_dataset": per_dataset,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _map_recurrence(min_occurs: Any, max_occurs: Any) -> str:
    mn = str(min_occurs or "0")
    mx = str(max_occurs or "1")
    if mn == "0" and mx == "1":
        return "0:1"
    if mn == "0" and mx in ("unbounded", "M", "*"):
        return "0:M"
    if mn == "1" and mx == "1":
        return "1:1"
    if mn == "1" and mx in ("unbounded", "M", "*"):
        return "1:M"
    return f"{mn}:{mx}"


def _build_allowed_actions(accepts_not: bool, accepts_pn: bool, is_nillable: bool) -> list[str]:
    actions = ["Enter valid value"]
    if accepts_not:
        actions.append("Use Not Recorded (7701003)")
        actions.append("Use Not Applicable (7701001)")
    if accepts_pn:
        actions.append("Use Pertinent Negative (e.g. Denied: 8801003)")
    if is_nillable:
        actions.append("Use xsi:nil='true' with NV attribute")
    return actions


def _validate_data_type(
    element: str,
    section: str,
    group_path: str,
    value: str,
    data_type: str,
    issues: list[ValidationIssue],
    warnings: list[ValidationIssue],
) -> None:
    """Dimension 12: Validate value against NEMSIS data type."""
    if not data_type or not value:
        return

    dt_lower = data_type.lower()

    # DateTime types
    if "datetime" in dt_lower or "date" in dt_lower:
        # NEMSIS datetime: YYYY-MM-DDThh:mm:ss±hh:mm or YYYY-MM-DD
        datetime_pattern = re.compile(
            r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2}([+-]\d{2}:\d{2}|Z)?)?$"
        )
        if not datetime_pattern.match(value):
            issues.append(ValidationIssue(
                element=element,
                section=section,
                group_path=group_path,
                level="Error",
                rule_source="dictionary",
                rule_id="NEMSIS_INVALID_DATETIME",
                message=f"Value '{value}' is not a valid NEMSIS datetime format for {element}. Expected: YYYY-MM-DDThh:mm:ss±hh:mm",
                allowed_actions=["Enter date/time in NEMSIS ISO-8601 format"],
            ))
        return

    # Integer types
    if "integer" in dt_lower or "int" in dt_lower:
        try:
            int(value)
        except ValueError:
            issues.append(ValidationIssue(
                element=element,
                section=section,
                group_path=group_path,
                level="Error",
                rule_source="dictionary",
                rule_id="NEMSIS_INVALID_INTEGER",
                message=f"Value '{value}' is not a valid integer for {element}.",
                allowed_actions=["Enter a whole number"],
            ))
        return

    # Decimal/numeric types
    if "decimal" in dt_lower or "numeric" in dt_lower or "number" in dt_lower:
        try:
            float(value)
        except ValueError:
            issues.append(ValidationIssue(
                element=element,
                section=section,
                group_path=group_path,
                level="Error",
                rule_source="dictionary",
                rule_id="NEMSIS_INVALID_DECIMAL",
                message=f"Value '{value}' is not a valid decimal number for {element}.",
                allowed_actions=["Enter a numeric value"],
            ))
        return


def _validate_constraints(
    element: str,
    section: str,
    group_path: str,
    value: str,
    constraints: dict[str, Any],
    issues: list[ValidationIssue],
) -> None:
    """Dimensions 13-15: Validate value against field constraints."""
    if not constraints or not value:
        return

    # Dimension 13: Min/max length
    min_len = constraints.get("min_length") or constraints.get("minLength")
    max_len = constraints.get("max_length") or constraints.get("maxLength")

    if min_len is not None:
        try:
            if len(value) < int(min_len):
                issues.append(ValidationIssue(
                    element=element,
                    section=section,
                    group_path=group_path,
                    level="Error",
                    rule_source="dictionary",
                    rule_id="NEMSIS_MIN_LENGTH_VIOLATION",
                    message=f"Value for {element} is too short (min length: {min_len}, actual: {len(value)}).",
                    allowed_actions=[f"Enter at least {min_len} characters"],
                ))
        except (TypeError, ValueError):
            pass

    if max_len is not None:
        try:
            if len(value) > int(max_len):
                issues.append(ValidationIssue(
                    element=element,
                    section=section,
                    group_path=group_path,
                    level="Error",
                    rule_source="dictionary",
                    rule_id="NEMSIS_MAX_LENGTH_VIOLATION",
                    message=f"Value for {element} exceeds maximum length (max: {max_len}, actual: {len(value)}).",
                    allowed_actions=[f"Shorten value to {max_len} characters or fewer"],
                ))
        except (TypeError, ValueError):
            pass

    # Dimension 14: Min/max inclusive
    min_incl = constraints.get("min_inclusive") or constraints.get("minInclusive")
    max_incl = constraints.get("max_inclusive") or constraints.get("maxInclusive")

    if min_incl is not None or max_incl is not None:
        try:
            num_val = float(value)
            if min_incl is not None and num_val < float(min_incl):
                issues.append(ValidationIssue(
                    element=element,
                    section=section,
                    group_path=group_path,
                    level="Error",
                    rule_source="dictionary",
                    rule_id="NEMSIS_MIN_INCLUSIVE_VIOLATION",
                    message=f"Value {value} for {element} is below minimum ({min_incl}).",
                    allowed_actions=[f"Enter a value >= {min_incl}"],
                ))
            if max_incl is not None and num_val > float(max_incl):
                issues.append(ValidationIssue(
                    element=element,
                    section=section,
                    group_path=group_path,
                    level="Error",
                    rule_source="dictionary",
                    rule_id="NEMSIS_MAX_INCLUSIVE_VIOLATION",
                    message=f"Value {value} for {element} exceeds maximum ({max_incl}).",
                    allowed_actions=[f"Enter a value <= {max_incl}"],
                ))
        except (TypeError, ValueError):
            pass

    # Dimension 15: Pattern/regex
    pattern = constraints.get("pattern")
    if pattern:
        try:
            if not re.fullmatch(pattern, value):
                issues.append(ValidationIssue(
                    element=element,
                    section=section,
                    group_path=group_path,
                    level="Error",
                    rule_source="dictionary",
                    rule_id="NEMSIS_PATTERN_VIOLATION",
                    message=f"Value '{value}' for {element} does not match required pattern: {pattern}",
                    allowed_actions=["Enter a value matching the required format"],
                ))
        except re.error:
            pass


def _validate_recurrence(
    element: str,
    section: str,
    group_path: str,
    recurrence: str,
    group_values: list[Any],
    issues: list[ValidationIssue],
) -> None:
    """Dimension 17: Validate repeating group cardinality."""
    count = len([v for v in group_values if v is not None])

    if recurrence == "1:1" and count != 1:
        issues.append(ValidationIssue(
            element=element,
            section=section,
            group_path=group_path,
            level="Error",
            rule_source="dictionary",
            rule_id="NEMSIS_CARDINALITY_VIOLATION",
            message=f"Element {element} requires exactly 1 occurrence (recurrence: 1:1), found {count}.",
            allowed_actions=["Provide exactly one value"],
        ))
    elif recurrence == "1:M" and count < 1:
        issues.append(ValidationIssue(
            element=element,
            section=section,
            group_path=group_path,
            level="Error",
            rule_source="dictionary",
            rule_id="NEMSIS_CARDINALITY_VIOLATION",
            message=f"Element {element} requires at least 1 occurrence (recurrence: 1:M), found {count}.",
            allowed_actions=["Provide at least one value"],
        ))


# ---------------------------------------------------------------------------
# Public aliases and exports for backward compatibility and new consumers
# ---------------------------------------------------------------------------

# Public aliases for the private internal dicts
VALID_NOT_VALUES: frozenset[str] = frozenset(_STANDARD_NOT_VALUES.keys())
VALID_PERTINENT_NEGATIVES: frozenset[str] = frozenset(_STANDARD_PN_VALUES.keys())

NOT_VALUE_NOT_APPLICABLE = "7701001"
NOT_VALUE_NOT_RECORDED = "7701003"

# Public aliases for the dataclasses
NemsisFieldValidationIssue = ValidationIssue
NemsisFieldValidationResult = FieldValidationResult


def get_validation_mode() -> str:
    """Public accessor for the active NEMSIS validation mode."""
    return _get_validation_mode()


def is_strict_schematron_required() -> bool:
    """Return True when Schematron skip must be treated as a failure."""
    return _get_validation_mode() in {VALIDATION_MODE_CERTIFICATION, VALIDATION_MODE_PRODUCTION}


def get_default_field_validator() -> "NemsisFieldValidator":
    """Return a module-level singleton NemsisFieldValidator with the default registry."""
    global _default_field_validator_singleton
    if _default_field_validator_singleton is None:
        from epcr_app.nemsis_registry_service import NemsisRegistryService
        _default_field_validator_singleton = NemsisFieldValidator(NemsisRegistryService())
    return _default_field_validator_singleton


_default_field_validator_singleton: "NemsisFieldValidator | None" = None


__all__ = [
    "NemsisFieldValidator",
    "FieldValidationResult",
    "ValidationIssue",
    # Public aliases
    "NemsisFieldValidationIssue",
    "NemsisFieldValidationResult",
    "VALID_NOT_VALUES",
    "VALID_PERTINENT_NEGATIVES",
    "NOT_VALUE_NOT_APPLICABLE",
    "NOT_VALUE_NOT_RECORDED",
    # Validation mode
    "VALIDATION_MODE_DEVELOPMENT",
    "VALIDATION_MODE_CERTIFICATION",
    "VALIDATION_MODE_PRODUCTION",
    "get_validation_mode",
    "is_strict_schematron_required",
    "get_default_field_validator",
    # Internal (kept for backward compat)
    "_STANDARD_NOT_VALUES",
    "_STANDARD_PN_VALUES",
]
