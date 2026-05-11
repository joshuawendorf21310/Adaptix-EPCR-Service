"""Universal NEMSIS 3.5.1 field rendering contract.

Defines the canonical rendering specification for every NEMSIS field.
Frontend components and Android forms MUST consume this contract rather
than hardcoding field behavior.

This module is ADDITIVE and read-only. It never mutates chart state.

Contract shape::

    {
        "element": "eVitals.06",
        "metadata": {...},
        "value": null,
        "attributes": {"NV": null, "PN": null, "xsi:nil": false},
        "groupPath": "eVitals.VitalGroup.BloodPressureGroup",
        "renderSpec": {
            "inputType": "select",
            "isMultiSelect": false,
            "isRepeatable": false,
            "isGroupMember": false,
            "showNotValueOption": true,
            "showPertinentNegativeOption": false,
            "showNilOption": false,
            "showDeprecatedWarning": false,
            "codeList": [...],
            "constraints": {...},
            "placeholder": "Select value...",
            "required": true,
            "readOnly": false,
        }
    }
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Input type constants
# ---------------------------------------------------------------------------

INPUT_TYPE_SELECT = "select"
INPUT_TYPE_MULTISELECT = "multiselect"
INPUT_TYPE_TEXT = "text"
INPUT_TYPE_TEXTAREA = "textarea"
INPUT_TYPE_NUMBER = "number"
INPUT_TYPE_DATETIME = "datetime"
INPUT_TYPE_DATE = "date"
INPUT_TYPE_CHECKBOX = "checkbox"
INPUT_TYPE_HIDDEN = "hidden"


# ---------------------------------------------------------------------------
# Data type → input type mapping
# ---------------------------------------------------------------------------

_DATETIME_TYPES = frozenset({
    "datetime", "timestamp", "emsdatetime", "emstimestamp",
    "datetimedatetime", "datetimedatetimetype",
})
_DATE_TYPES = frozenset({
    "date", "emsdate", "datetype",
})
_NUMBER_TYPES = frozenset({
    "integer", "int", "positiveinteger", "nonnegativeinteger",
    "decimal", "float", "double", "numeric",
})
_BOOLEAN_TYPES = frozenset({
    "boolean", "bool",
})


def _data_type_to_input_type(data_type: str | None) -> str:
    if not data_type:
        return INPUT_TYPE_TEXT
    dt = data_type.lower()
    for t in _DATETIME_TYPES:
        if t in dt:
            return INPUT_TYPE_DATETIME
    for t in _DATE_TYPES:
        if t in dt and "time" not in dt:
            return INPUT_TYPE_DATE
    for t in _NUMBER_TYPES:
        if t in dt:
            return INPUT_TYPE_NUMBER
    for t in _BOOLEAN_TYPES:
        if t in dt:
            return INPUT_TYPE_CHECKBOX
    return INPUT_TYPE_TEXT


# ---------------------------------------------------------------------------
# Rendering contract builder
# ---------------------------------------------------------------------------

class NemsisFieldRendererContract:
    """Build rendering specifications from NEMSIS field metadata.

    This class is the single source of truth for how every NEMSIS field
    should be rendered. No React component or Android form may hardcode
    NEMSIS field behavior if metadata exists.
    """

    def build_render_spec(
        self,
        *,
        element: str,
        metadata: dict[str, Any] | None,
        value: Any = None,
        attributes: dict[str, Any] | None = None,
        group_path: str = "",
        read_only: bool = False,
    ) -> dict[str, Any]:
        """Build a complete rendering specification for a NEMSIS field.

        Args:
            element: NEMSIS element ID (e.g. "eVitals.06").
            metadata: Field metadata from NemsisRegistryService.get_field().
                      If None, returns a minimal unknown spec.
            value: Current field value (scalar or list for repeating fields).
            attributes: Dict with keys "NV", "PN", "xsi:nil".
            group_path: XPath-like group context for repeating groups.
            read_only: Whether the field should be rendered as read-only.

        Returns:
            Full rendering contract dict.
        """
        attrs = attributes or {}

        if metadata is None:
            return {
                "element": element,
                "metadata": None,
                "value": value,
                "attributes": attrs,
                "groupPath": group_path,
                "renderSpec": {
                    "inputType": INPUT_TYPE_TEXT,
                    "isMultiSelect": False,
                    "isRepeatable": False,
                    "isGroupMember": bool(group_path),
                    "showNotValueOption": False,
                    "showPertinentNegativeOption": False,
                    "showNilOption": False,
                    "showDeprecatedWarning": False,
                    "codeList": [],
                    "constraints": {},
                    "placeholder": "Unknown field — metadata unavailable",
                    "required": False,
                    "readOnly": read_only,
                    "metadataAvailable": False,
                },
            }

        usage = (metadata.get("usage") or metadata.get("required_level") or "Optional").strip()
        recurrence = (metadata.get("recurrence") or "0:1").strip()
        data_type = metadata.get("data_type") or ""
        deprecated = bool(metadata.get("deprecated", False))
        accepts_nv = (metadata.get("not_value_allowed") or "").strip().lower() in ("yes", "true", "1", "y")
        accepts_pn = (metadata.get("pertinent_negative_allowed") or "").strip().lower() in ("yes", "true", "1", "y")
        is_nillable = (metadata.get("nillable") or "").strip().lower() in ("yes", "true", "1", "y")

        # Code list from metadata allowed_values
        code_list: list[dict[str, str]] = []
        for row in (metadata.get("allowed_values") or []):
            if isinstance(row, dict):
                code_list.append({
                    "code": str(row.get("code", "")),
                    "description": str(row.get("display") or row.get("description") or row.get("code", "")),
                })
            elif isinstance(row, str):
                code_list.append({"code": row, "description": row})

        # Recurrence analysis
        parts = recurrence.split(":")
        max_occurs_raw = parts[1] if len(parts) > 1 else "1"
        is_repeatable = max_occurs_raw in ("M", "unbounded", "*") or (
            max_occurs_raw.isdigit() and int(max_occurs_raw) > 1
        )
        is_multi_select = bool(code_list) and is_repeatable

        # Input type determination
        if code_list:
            if is_multi_select:
                input_type = INPUT_TYPE_MULTISELECT
            else:
                input_type = INPUT_TYPE_SELECT
        else:
            input_type = _data_type_to_input_type(data_type)

        # Constraints for UI rendering
        constraints: dict[str, Any] = {}
        raw_c = metadata.get("constraints") or {}
        if isinstance(raw_c, dict):
            if raw_c.get("min_length"):
                constraints["minLength"] = int(raw_c["min_length"])
            if raw_c.get("max_length"):
                constraints["maxLength"] = int(raw_c["max_length"])
            if raw_c.get("min_inclusive"):
                constraints["min"] = raw_c["min_inclusive"]
            if raw_c.get("max_inclusive"):
                constraints["max"] = raw_c["max_inclusive"]
            if raw_c.get("pattern"):
                constraints["pattern"] = raw_c["pattern"]

        # Required flag
        is_required = usage in ("Mandatory", "Required")

        # Placeholder text
        if deprecated:
            placeholder = f"⚠ Deprecated — {metadata.get('label', element)}"
        elif code_list:
            placeholder = f"Select {metadata.get('label', element)}..."
        elif input_type == INPUT_TYPE_DATETIME:
            placeholder = "YYYY-MM-DDTHH:MM:SS±HH:MM"
        elif input_type == INPUT_TYPE_DATE:
            placeholder = "YYYY-MM-DD"
        elif input_type == INPUT_TYPE_NUMBER:
            placeholder = "Enter number..."
        else:
            placeholder = f"Enter {metadata.get('label', element)}..."

        return {
            "element": element,
            "metadata": {
                "label": metadata.get("label") or metadata.get("official_name") or element,
                "definition": metadata.get("definition") or "",
                "usage": usage,
                "recurrence": recurrence,
                "dataType": data_type,
                "nationalElement": (metadata.get("national_element") or "").lower() in ("national", "yes", "true"),
                "stateElement": (metadata.get("state_element") or "").lower() in ("state", "yes", "true"),
                "deprecated": deprecated,
            },
            "value": value,
            "attributes": {
                "NV": attrs.get("NV"),
                "PN": attrs.get("PN"),
                "xsi:nil": attrs.get("xsi:nil", False),
            },
            "groupPath": group_path,
            "renderSpec": {
                "inputType": input_type,
                "isMultiSelect": is_multi_select,
                "isRepeatable": is_repeatable,
                "isGroupMember": bool(group_path),
                "showNotValueOption": accepts_nv,
                "showPertinentNegativeOption": accepts_pn,
                "showNilOption": is_nillable,
                "showDeprecatedWarning": deprecated,
                "codeList": code_list,
                "constraints": constraints,
                "placeholder": placeholder,
                "required": is_required,
                "readOnly": read_only,
                "metadataAvailable": True,
            },
        }

    def build_section_render_specs(
        self,
        *,
        section: str,
        fields: list[dict[str, Any]],
        chart_values: dict[str, Any] | None = None,
        read_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Build rendering specs for all fields in a section.

        Args:
            section: Section name (e.g. "ePatient").
            fields: List of field metadata dicts for this section.
            chart_values: Dict mapping element IDs to current values.
            read_only: Whether all fields should be read-only.

        Returns:
            List of rendering contract dicts, one per field.
        """
        chart_values = chart_values or {}
        specs: list[dict[str, Any]] = []
        for field_meta in fields:
            element = field_meta.get("field_id") or field_meta.get("element_id") or ""
            if not element:
                continue
            value = chart_values.get(element)
            attrs = chart_values.get(f"{element}.__attrs__") or {}
            specs.append(self.build_render_spec(
                element=element,
                metadata=field_meta,
                value=value,
                attributes=attrs,
                read_only=read_only,
            ))
        return specs


# Module-level singleton
_default_renderer: NemsisFieldRendererContract | None = None


def get_default_renderer() -> NemsisFieldRendererContract:
    global _default_renderer
    if _default_renderer is None:
        _default_renderer = NemsisFieldRendererContract()
    return _default_renderer


__all__ = [
    "NemsisFieldRendererContract",
    "get_default_renderer",
    "INPUT_TYPE_SELECT",
    "INPUT_TYPE_MULTISELECT",
    "INPUT_TYPE_TEXT",
    "INPUT_TYPE_TEXTAREA",
    "INPUT_TYPE_NUMBER",
    "INPUT_TYPE_DATETIME",
    "INPUT_TYPE_DATE",
    "INPUT_TYPE_CHECKBOX",
    "INPUT_TYPE_HIDDEN",
]
