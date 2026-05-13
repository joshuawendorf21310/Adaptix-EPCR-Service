"""Validation rules for ECustom field values.

Each :class:`epcr_app.models.EpcrECustomFieldDefinition` row declares a
data type and (optionally) an allowed-values list, a required flag, and
a conditional rule. This module enforces those constraints against a
raw inbound value and returns a normalized representation ready to be
JSON-encoded into ``epcr_ecustom_field_value.value_json``.

Failures raise :class:`ValidationError` carrying a list of
``{"field": ..., "message": ...}`` entries so the API layer can surface
field-level diagnostics directly to the frontend.

Conditional rule semantics
--------------------------

``conditional_rule_json`` (when present) is a JSON object of the shape::

    {
        "when": {"field_key": "...", "equals": <value>},
        "then": {"required": true}
    }

The caller passes the current chart's full ``ecustom_values`` mapping
in the ``context`` argument so the validator can resolve the
``when.field_key`` reference and decide whether the ``then`` clause
should apply.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from numbers import Real
from typing import Any, Iterable


DATA_TYPES: frozenset[str] = frozenset(
    {
        "string",
        "number",
        "boolean",
        "date",
        "select",
        "multi_select",
    }
)


class ValidationError(ValueError):
    """Raised when one or more ECustom field values fail validation."""

    def __init__(self, errors: list[dict[str, str]]) -> None:
        self.errors: list[dict[str, str]] = list(errors)
        message = "; ".join(f"{e['field']}: {e['message']}" for e in self.errors)
        super().__init__(message or "ecustom_field_validation_error")


def _allowed_values(definition: Any) -> list[Any] | None:
    raw = getattr(definition, "allowed_values_json", None)
    if raw is None or raw == "":
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if isinstance(parsed, list):
        return parsed
    return None


def _conditional_rule(definition: Any) -> dict[str, Any] | None:
    raw = getattr(definition, "conditional_rule_json", None)
    if raw is None or raw == "":
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def _field_key(definition: Any) -> str:
    return getattr(definition, "field_key", "<unknown>")


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"true", "1", "yes", "y"}:
            return True
        if v in {"false", "0", "no", "n"}:
            return False
    if isinstance(value, int) and not isinstance(value, bool):
        if value in (0, 1):
            return bool(value)
    return None


def _coerce_number(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, Real):
        return value  # type: ignore[return-value]
    if isinstance(value, str):
        v = value.strip()
        if not v:
            return None
        try:
            if "." in v or "e" in v or "E" in v:
                return float(v)
            return int(v)
        except ValueError:
            return None
    return None


def _coerce_date(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            parsed = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return parsed.date().isoformat()
        except ValueError:
            try:
                return date.fromisoformat(s).isoformat()
            except ValueError:
                return None
    return None


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    if isinstance(value, (list, tuple)) and len(value) == 0:
        return True
    return False


def validate_field_value(
    definition: Any,
    raw_value: Any,
    *,
    context: dict[str, Any] | None = None,
) -> Any:
    """Validate ``raw_value`` against ``definition`` and return normalized form.

    Args:
        definition: An ``EpcrECustomFieldDefinition`` row (or any object
            exposing the same attribute surface). Required attributes:
            ``field_key``, ``data_type``, ``required``,
            ``allowed_values_json``, ``conditional_rule_json``.
        raw_value: Value supplied by the frontend (may be ``None``).
        context: Optional mapping of ``field_key -> already-normalized
            value`` used to evaluate ``conditional_rule_json``.

    Returns:
        Normalized value suitable for JSON encoding.

    Raises:
        ValidationError: One or more constraints failed.
    """
    errors: list[dict[str, str]] = []
    field_key = _field_key(definition)
    data_type = getattr(definition, "data_type", None)

    if data_type not in DATA_TYPES:
        raise ValidationError(
            [
                {
                    "field": field_key,
                    "message": (
                        f"definition.data_type {data_type!r} is not one of "
                        f"{sorted(DATA_TYPES)}"
                    ),
                }
            ]
        )

    # Conditional rule may upgrade the required flag.
    required = bool(getattr(definition, "required", False))
    rule = _conditional_rule(definition)
    if rule and isinstance(rule.get("when"), dict):
        when = rule["when"]
        ref_key = when.get("field_key")
        if ref_key is not None and context is not None:
            actual = context.get(ref_key)
            if "equals" in when:
                if actual == when["equals"]:
                    then = rule.get("then") or {}
                    if isinstance(then, dict) and bool(then.get("required")):
                        required = True

    if _is_empty(raw_value):
        if required:
            raise ValidationError(
                [{"field": field_key, "message": "is required"}]
            )
        return None

    allowed = _allowed_values(definition)

    normalized: Any = None
    if data_type == "string":
        if not isinstance(raw_value, str):
            errors.append(
                {"field": field_key, "message": "must be a string"}
            )
        else:
            normalized = raw_value
            if allowed is not None and normalized not in allowed:
                errors.append(
                    {
                        "field": field_key,
                        "message": f"must be one of {sorted(map(str, allowed))}",
                    }
                )

    elif data_type == "number":
        coerced = _coerce_number(raw_value)
        if coerced is None:
            errors.append(
                {"field": field_key, "message": "must be a number"}
            )
        else:
            normalized = coerced
            if allowed is not None and normalized not in allowed:
                errors.append(
                    {
                        "field": field_key,
                        "message": f"must be one of {allowed}",
                    }
                )

    elif data_type == "boolean":
        coerced = _coerce_bool(raw_value)
        if coerced is None:
            errors.append(
                {"field": field_key, "message": "must be a boolean"}
            )
        else:
            normalized = coerced

    elif data_type == "date":
        coerced = _coerce_date(raw_value)
        if coerced is None:
            errors.append(
                {
                    "field": field_key,
                    "message": "must be an ISO 8601 date string",
                }
            )
        else:
            normalized = coerced

    elif data_type == "select":
        if not isinstance(raw_value, (str, int, float, bool)):
            errors.append(
                {
                    "field": field_key,
                    "message": "must be a scalar select value",
                }
            )
        else:
            normalized = raw_value
            if allowed is not None and normalized not in allowed:
                errors.append(
                    {
                        "field": field_key,
                        "message": f"must be one of {allowed}",
                    }
                )
            elif allowed is None:
                errors.append(
                    {
                        "field": field_key,
                        "message": (
                            "select definition is missing allowed_values_json"
                        ),
                    }
                )

    elif data_type == "multi_select":
        if not isinstance(raw_value, (list, tuple)):
            errors.append(
                {
                    "field": field_key,
                    "message": "must be a list of select values",
                }
            )
        else:
            items = list(raw_value)
            if allowed is None:
                errors.append(
                    {
                        "field": field_key,
                        "message": (
                            "multi_select definition is missing "
                            "allowed_values_json"
                        ),
                    }
                )
            else:
                bad = [item for item in items if item not in allowed]
                if bad:
                    errors.append(
                        {
                            "field": field_key,
                            "message": (
                                f"contains values not in allowed set: {bad}"
                            ),
                        }
                    )
            normalized = items

    if errors:
        raise ValidationError(errors)
    return normalized


__all__ = [
    "DATA_TYPES",
    "ValidationError",
    "validate_field_value",
]
