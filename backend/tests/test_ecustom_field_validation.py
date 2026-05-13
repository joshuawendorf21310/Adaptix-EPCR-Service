"""Validator-level tests for ECustom field payloads."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from epcr_app.services.ecustom_field_validation import (
    ValidationError,
    validate_field_value,
)


def _definition(**overrides):
    base = {
        "field_key": "exposure_type",
        "data_type": "string",
        "required": False,
        "allowed_values_json": None,
        "conditional_rule_json": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_required_field_rejects_empty() -> None:
    defn = _definition(required=True)
    with pytest.raises(ValidationError) as exc:
        validate_field_value(defn, None)
    assert any(e["message"] == "is required" for e in exc.value.errors)


def test_required_field_rejects_empty_string() -> None:
    defn = _definition(required=True)
    with pytest.raises(ValidationError):
        validate_field_value(defn, "   ")


def test_non_required_empty_returns_none() -> None:
    defn = _definition(required=False)
    assert validate_field_value(defn, None) is None


def test_select_enum_accepts_allowed_value() -> None:
    defn = _definition(
        data_type="select",
        allowed_values_json=json.dumps(["smoke", "chemical"]),
    )
    assert validate_field_value(defn, "smoke") == "smoke"


def test_select_enum_rejects_disallowed_value() -> None:
    defn = _definition(
        data_type="select",
        allowed_values_json=json.dumps(["smoke", "chemical"]),
    )
    with pytest.raises(ValidationError):
        validate_field_value(defn, "lava")


def test_multi_select_validates_membership() -> None:
    defn = _definition(
        data_type="multi_select",
        allowed_values_json=json.dumps(["a", "b", "c"]),
    )
    assert validate_field_value(defn, ["a", "c"]) == ["a", "c"]
    with pytest.raises(ValidationError):
        validate_field_value(defn, ["a", "z"])


def test_number_type_coercion_from_string() -> None:
    defn = _definition(data_type="number")
    assert validate_field_value(defn, "42") == 42
    assert validate_field_value(defn, "3.14") == pytest.approx(3.14)
    with pytest.raises(ValidationError):
        validate_field_value(defn, "not-a-number")


def test_boolean_type_coercion() -> None:
    defn = _definition(data_type="boolean")
    assert validate_field_value(defn, "true") is True
    assert validate_field_value(defn, "false") is False
    assert validate_field_value(defn, True) is True
    with pytest.raises(ValidationError):
        validate_field_value(defn, "maybe")


def test_date_type_normalizes_to_iso_date() -> None:
    defn = _definition(data_type="date")
    assert validate_field_value(defn, "2026-05-12") == "2026-05-12"
    assert (
        validate_field_value(defn, "2026-05-12T10:00:00Z") == "2026-05-12"
    )
    with pytest.raises(ValidationError):
        validate_field_value(defn, "not-a-date")


def test_conditional_rule_upgrades_required() -> None:
    """When a referenced field equals a sentinel, the dependent becomes required."""
    defn = _definition(
        field_key="exposure_detail",
        data_type="string",
        required=False,
        conditional_rule_json=json.dumps(
            {
                "when": {"field_key": "exposure_type", "equals": "chemical"},
                "then": {"required": True},
            }
        ),
    )
    # No context -> rule cannot fire, empty is OK.
    assert validate_field_value(defn, None) is None
    # Context with non-trigger value -> still optional.
    assert (
        validate_field_value(defn, None, context={"exposure_type": "smoke"})
        is None
    )
    # Context with trigger value -> now required.
    with pytest.raises(ValidationError):
        validate_field_value(
            defn, None, context={"exposure_type": "chemical"}
        )


def test_string_type_with_allowed_values_enforces_set() -> None:
    defn = _definition(
        data_type="string",
        allowed_values_json=json.dumps(["yes", "no"]),
    )
    assert validate_field_value(defn, "yes") == "yes"
    with pytest.raises(ValidationError):
        validate_field_value(defn, "maybe")


def test_unknown_data_type_raises() -> None:
    defn = _definition(data_type="bogus")
    with pytest.raises(ValidationError):
        validate_field_value(defn, "anything")
