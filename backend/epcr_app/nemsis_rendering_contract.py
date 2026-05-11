"""NEMSIS 3.5.1 Universal Field Rendering Contract.

Defines the metadata-driven rendering contract for every NEMSIS field.
Frontend components MUST use this contract to determine how to render
a field. No component may hardcode NEMSIS field behavior.

Contract input:
    {
        "element": "eVitals.06",
        "metadata": {...},  # from NemsisRegistryService
        "value": null,
        "attributes": {
            "NV": null,
            "PN": null,
            "xsi:nil": false
        },
        "groupPath": "eVitals.VitalGroup.BloodPressureGroup"
    }

Contract output (NemsisFieldRenderSpec):
    {
        "element": "eVitals.06",
        "section": "eVitals",
        "label": "...",
        "definition": "...",
        "renderType": "select|multiselect|text|number|datetime|date|textarea|boolean",
        "isRequired": true,
        "isMandatory": false,
        "isRepeatable": false,
        "isGrouped": false,
        "groupPath": "...",
        "acceptsNotValues": true,
        "notValueOptions": [...],
        "acceptsPertinentNegatives": false,
        "pnOptions": [...],
        "isNillable": false,
        "isDeprecated": false,
        "codeList": [...],
        "constraints": {...},
        "dataType": "...",
        "currentValue": null,
        "currentAttributes": {...},
        "validationState": "valid|invalid|warning|unknown"
    }

Rules:
- Never hardcodes field behavior. All behavior derived from metadata.
- If codeList exists -> render select/multiselect based on recurrence.
- If dataType is dateTime -> render datetime input.
- If dataType is number/decimal/integer -> render numeric input.
- If field accepts NOT values -> render NOT value documentation options.
- If field accepts Pertinent Negatives -> render PN documentation options.
- If nillable -> support explicit nil behavior.
- If deprecated -> warn or hide based on compatibility rules.
- If recurrence is 0:M or 1:M -> render repeatable values.
- If field is inside a repeating group -> render group-aware controls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from epcr_app.nemsis_field_validator import _STANDARD_NOT_VALUES, _STANDARD_PN_VALUES


# Render type constants
RENDER_TYPE_SELECT = "select"
RENDER_TYPE_MULTISELECT = "multiselect"
RENDER_TYPE_TEXT = "text"
RENDER_TYPE_NUMBER = "number"
RENDER_TYPE_DATETIME = "datetime"
RENDER_TYPE_DATE = "date"
RENDER_TYPE_TEXTAREA = "textarea"
RENDER_TYPE_BOOLEAN = "boolean"
RENDER_TYPE_UNKNOWN = "unknown"


@dataclass
class CodeOption:
    """A single code list option for a select/multiselect field."""
    code: str
    description: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "description": self.description}


@dataclass
class NemsisFieldRenderSpec:
    """Complete rendering specification for a single NEMSIS field.

    This is the contract between the backend metadata system and the
    frontend rendering layer. Every field rendered in the ePCR UI
    must be derived from this spec.
    """

    element: str
    section: str
    label: str
    definition: str

    render_type: str  # One of RENDER_TYPE_* constants
    is_required: bool  # usage == Required
    is_mandatory: bool  # usage == Mandatory
    is_repeatable: bool  # recurrence is 0:M or 1:M
    is_grouped: bool  # field is inside a repeating group
    group_path: str

    accepts_not_values: bool
    not_value_options: list[CodeOption]

    accepts_pertinent_negatives: bool
    pn_options: list[CodeOption]

    is_nillable: bool
    is_deprecated: bool

    code_list: list[CodeOption]
    constraints: dict[str, Any]
    data_type: str

    current_value: Any
    current_attributes: dict[str, Any]
    validation_state: str  # "valid" | "invalid" | "warning" | "unknown"

    # Recurrence metadata
    min_occurs: int
    max_occurs: int | None  # None = unbounded

    def to_dict(self) -> dict[str, Any]:
        return {
            "element": self.element,
            "section": self.section,
            "label": self.label,
            "definition": self.definition,
            "renderType": self.render_type,
            "isRequired": self.is_required,
            "isMandatory": self.is_mandatory,
            "isRepeatable": self.is_repeatable,
            "isGrouped": self.is_grouped,
            "groupPath": self.group_path,
            "acceptsNotValues": self.accepts_not_values,
            "notValueOptions": [o.to_dict() for o in self.not_value_options],
            "acceptsPertinentNegatives": self.accepts_pertinent_negatives,
            "pnOptions": [o.to_dict() for o in self.pn_options],
            "isNillable": self.is_nillable,
            "isDeprecated": self.is_deprecated,
            "codeList": [o.to_dict() for o in self.code_list],
            "constraints": self.constraints,
            "dataType": self.data_type,
            "currentValue": self.current_value,
            "currentAttributes": self.current_attributes,
            "validationState": self.validation_state,
            "minOccurs": self.min_occurs,
            "maxOccurs": self.max_occurs,
        }


def _determine_render_type(metadata: dict[str, Any]) -> str:
    """Determine the render type from field metadata.

    Priority:
    1. If code list exists -> select or multiselect
    2. If data type is dateTime -> datetime
    3. If data type is date -> date
    4. If data type is integer/decimal/numeric -> number
    5. If data type is boolean -> boolean
    6. If max_length > 255 -> textarea
    7. Default -> text
    """
    allowed_values = metadata.get("allowed_values") or []
    data_type = (metadata.get("data_type") or "").lower()
    max_occurs = str(metadata.get("max_occurs") or "1")
    max_len = None
    constraints = metadata.get("constraints") or {}
    if constraints.get("max_length"):
        try:
            max_len = int(constraints["max_length"])
        except (TypeError, ValueError):
            pass

    # Code list fields
    if allowed_values:
        is_multi = max_occurs in ("unbounded", "M", "*") or (
            max_occurs.isdigit() and int(max_occurs) > 1
        )
        return RENDER_TYPE_MULTISELECT if is_multi else RENDER_TYPE_SELECT

    # DateTime
    if "datetime" in data_type:
        return RENDER_TYPE_DATETIME

    # Date only
    if data_type in ("date", "emsdate"):
        return RENDER_TYPE_DATE

    # Numeric
    if any(t in data_type for t in ("integer", "decimal", "numeric", "number", "int")):
        return RENDER_TYPE_NUMBER

    # Boolean
    if "boolean" in data_type or "bool" in data_type:
        return RENDER_TYPE_BOOLEAN

    # Long text
    if max_len and max_len > 255:
        return RENDER_TYPE_TEXTAREA

    return RENDER_TYPE_TEXT


def _parse_recurrence(min_occurs: Any, max_occurs: Any) -> tuple[int, int | None]:
    """Parse min/max occurs into integers."""
    try:
        mn = int(str(min_occurs or "0"))
    except (TypeError, ValueError):
        mn = 0

    mx_raw = str(max_occurs or "1")
    if mx_raw in ("unbounded", "M", "*"):
        return mn, None
    try:
        return mn, int(mx_raw)
    except (TypeError, ValueError):
        return mn, 1


def build_render_spec(
    element: str,
    metadata: dict[str, Any],
    *,
    value: Any = None,
    attributes: dict[str, Any] | None = None,
    group_path: str = "",
    validation_state: str = "unknown",
) -> NemsisFieldRenderSpec:
    """Build a rendering specification from field metadata.

    Args:
        element: NEMSIS element ID (e.g. "eVitals.06")
        metadata: Field metadata from NemsisRegistryService.get_field()
        value: Current field value (None if not set)
        attributes: Current XML attributes (NV, PN, xsi:nil)
        group_path: XPath-like group path for context
        validation_state: Current validation state

    Returns:
        NemsisFieldRenderSpec ready for frontend consumption.
    """
    attrs = attributes or {}
    section = metadata.get("section") or element.split(".")[0]
    label = (
        metadata.get("official_name")
        or metadata.get("label")
        or metadata.get("name")
        or element
    )
    definition = metadata.get("definition") or ""
    data_type = metadata.get("data_type") or ""
    usage = metadata.get("usage") or metadata.get("required_level") or "Optional"
    accepts_not = bool(metadata.get("not_value_allowed"))
    accepts_pn = bool(metadata.get("pertinent_negative_allowed"))
    is_nillable = (
        metadata.get("nillable") is True
        or str(metadata.get("nillable") or "").lower() == "true"
    )
    is_deprecated = bool(metadata.get("deprecated"))

    min_occ, max_occ = _parse_recurrence(
        metadata.get("min_occurs"), metadata.get("max_occurs")
    )
    is_repeatable = max_occ is None or max_occ > 1
    is_grouped = bool(group_path and "." in group_path)

    # Build code list
    raw_allowed = metadata.get("allowed_values") or []
    code_list: list[CodeOption] = []
    for av in raw_allowed:
        if isinstance(av, dict):
            code = str(av.get("code") or av.get("value") or "")
            desc = str(av.get("description") or av.get("label") or code)
            code_list.append(CodeOption(code=code, description=desc))
        elif isinstance(av, str):
            code_list.append(CodeOption(code=av, description=av))

    # Build NOT value options
    not_value_options: list[CodeOption] = []
    if accepts_not:
        for code, desc in _STANDARD_NOT_VALUES.items():
            not_value_options.append(CodeOption(code=code, description=desc))

    # Build PN options
    pn_options: list[CodeOption] = []
    if accepts_pn:
        for code, desc in _STANDARD_PN_VALUES.items():
            pn_options.append(CodeOption(code=code, description=desc))

    # Constraints
    raw_constraints = metadata.get("constraints") or {}
    constraints: dict[str, Any] = {}
    if raw_constraints.get("min_length"):
        constraints["minLength"] = int(raw_constraints["min_length"])
    if raw_constraints.get("max_length"):
        constraints["maxLength"] = int(raw_constraints["max_length"])
    if raw_constraints.get("min_inclusive"):
        constraints["minInclusive"] = raw_constraints["min_inclusive"]
    if raw_constraints.get("max_inclusive"):
        constraints["maxInclusive"] = raw_constraints["max_inclusive"]
    if raw_constraints.get("pattern") or metadata.get("pattern"):
        constraints["pattern"] = raw_constraints.get("pattern") or metadata.get("pattern")

    render_type = _determine_render_type(metadata)

    return NemsisFieldRenderSpec(
        element=element,
        section=section,
        label=label,
        definition=definition,
        render_type=render_type,
        is_required=usage == "Required",
        is_mandatory=usage == "Mandatory",
        is_repeatable=is_repeatable,
        is_grouped=is_grouped,
        group_path=group_path or section,
        accepts_not_values=accepts_not,
        not_value_options=not_value_options,
        accepts_pertinent_negatives=accepts_pn,
        pn_options=pn_options,
        is_nillable=is_nillable,
        is_deprecated=is_deprecated,
        code_list=code_list,
        constraints=constraints,
        data_type=data_type,
        current_value=value,
        current_attributes=attrs,
        validation_state=validation_state,
        min_occurs=min_occ,
        max_occurs=max_occ,
    )


def build_section_render_specs(
    section: str,
    registry_service: Any,
    *,
    field_values: dict[str, Any] | None = None,
    field_attributes: dict[str, dict[str, Any]] | None = None,
    validation_results: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Build rendering specs for all fields in a section.

    Args:
        section: NEMSIS section name (e.g. "ePatient")
        registry_service: NemsisRegistryService instance
        field_values: Dict of {element_id: value}
        field_attributes: Dict of {element_id: {NV: ..., PN: ..., xsi:nil: ...}}
        validation_results: Dict of {element_id: "valid"|"invalid"|"warning"|"unknown"}

    Returns:
        List of render spec dicts for all fields in the section.
    """
    values = field_values or {}
    attrs = field_attributes or {}
    val_results = validation_results or {}

    section_fields = registry_service.list_fields(section=section)
    specs: list[dict[str, Any]] = []

    for field_meta in section_fields:
        element = field_meta.get("field_id") or field_meta.get("element_id") or ""
        if not element:
            continue

        spec = build_render_spec(
            element=element,
            metadata=field_meta,
            value=values.get(element),
            attributes=attrs.get(element),
            group_path=section,
            validation_state=val_results.get(element, "unknown"),
        )
        specs.append(spec.to_dict())

    return specs


__all__ = [
    "NemsisFieldRenderSpec",
    "CodeOption",
    "build_render_spec",
    "build_section_render_specs",
    "RENDER_TYPE_SELECT",
    "RENDER_TYPE_MULTISELECT",
    "RENDER_TYPE_TEXT",
    "RENDER_TYPE_NUMBER",
    "RENDER_TYPE_DATETIME",
    "RENDER_TYPE_DATE",
    "RENDER_TYPE_TEXTAREA",
    "RENDER_TYPE_BOOLEAN",
]
