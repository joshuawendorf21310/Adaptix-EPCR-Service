"""NEMSIS Validation Mode Enforcement.

Controls strictness of NEMSIS validation across the export pipeline.

Modes:
    development:
        - XSD required.
        - Schematron skipped = warning only (does not fail export).

    certification:
        - XSD required.
        - Schematron required.
        - Schematron skipped = FAILURE. Export blocked.

    production:
        - XSD required.
        - Schematron required.
        - Schematron skipped = FAILURE. Export blocked.

Rules:
- Never allows schematron_skipped=True to pass in certification or production.
- Never fabricates a passing result.
- Mode is read from NEMSIS_VALIDATION_MODE env var.
- Default is development (safe for local dev without schematron assets).
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

VALIDATION_MODE_DEVELOPMENT = "development"
VALIDATION_MODE_CERTIFICATION = "certification"
VALIDATION_MODE_PRODUCTION = "production"

_VALID_MODES = frozenset({
    VALIDATION_MODE_DEVELOPMENT,
    VALIDATION_MODE_CERTIFICATION,
    VALIDATION_MODE_PRODUCTION,
})

# Modes that require Schematron to not be skipped
_STRICT_MODES = frozenset({VALIDATION_MODE_CERTIFICATION, VALIDATION_MODE_PRODUCTION})


def get_validation_mode() -> str:
    """Return the current NEMSIS validation mode from environment.

    Returns:
        One of: "development", "certification", "production"
        Defaults to "development" if not set or invalid.
    """
    raw = os.environ.get("NEMSIS_VALIDATION_MODE", VALIDATION_MODE_DEVELOPMENT).strip().lower()
    if raw not in _VALID_MODES:
        logger.warning(
            "Invalid NEMSIS_VALIDATION_MODE=%r; defaulting to 'development'", raw
        )
        return VALIDATION_MODE_DEVELOPMENT
    return raw


def is_strict_mode() -> bool:
    """Return True if current mode requires Schematron validation."""
    return get_validation_mode() in _STRICT_MODES


def enforce_validation_mode(validation_result: dict[str, Any]) -> dict[str, Any]:
    """Apply validation mode enforcement to a raw validator result.

    In certification/production mode:
    - schematron_skipped=True is treated as a FAILURE.
    - valid is set to False.
    - A blocking error is added.

    In development mode:
    - schematron_skipped=True is a warning only.
    - valid is not changed by this function.

    Args:
        validation_result: Raw result dict from NemsisXSDValidator.validate_xml()

    Returns:
        Updated validation result dict with mode enforcement applied.
    """
    mode = get_validation_mode()
    result = dict(validation_result)

    schematron_skipped = result.get("schematron_skipped", False)

    if schematron_skipped and mode in _STRICT_MODES:
        # Schematron skip is a hard failure in certification/production
        blocking_msg = (
            f"Schematron validation was skipped but NEMSIS_VALIDATION_MODE={mode} "
            "requires Schematron validation. Export is blocked. "
            "Install saxonche and ensure NEMSIS_SCHEMATRON_PATH is configured."
        )
        result["valid"] = False
        result["schematron_valid"] = False

        existing_errors = list(result.get("errors") or [])
        existing_errors.insert(0, blocking_msg)
        result["errors"] = existing_errors

        existing_xsd_errors = list(result.get("xsd_errors") or [])
        result["xsd_errors"] = existing_xsd_errors

        existing_sch_errors = list(result.get("schematron_errors") or [])
        existing_sch_errors.insert(0, blocking_msg)
        result["schematron_errors"] = existing_sch_errors

        result["blocking_reason"] = blocking_msg
        result["validation_mode"] = mode
        result["schematron_skip_blocked"] = True

        logger.error(
            "NEMSIS export BLOCKED: Schematron skipped in %s mode. %s",
            mode,
            blocking_msg,
        )

    elif schematron_skipped and mode == VALIDATION_MODE_DEVELOPMENT:
        # Development mode: warn but do not block
        warn_msg = (
            "Schematron validation was skipped (development mode). "
            "This would be a FAILURE in certification/production mode."
        )
        existing_warnings = list(result.get("warnings") or [])
        existing_warnings.append(warn_msg)
        result["warnings"] = existing_warnings
        result["validation_mode"] = mode
        result["schematron_skip_blocked"] = False

        logger.warning("NEMSIS Schematron skipped in development mode (non-blocking).")

    else:
        result["validation_mode"] = mode
        result["schematron_skip_blocked"] = False

    return result


def validate_with_mode_enforcement(
    xml: str | bytes,
    validator: Any,
    export_id: Any = None,
) -> dict[str, Any]:
    """Run XSD+Schematron validation and apply mode enforcement.

    Args:
        xml: XML bytes or string to validate.
        validator: NemsisXSDValidator instance.
        export_id: Optional export ID for logging.

    Returns:
        Validation result dict with mode enforcement applied.
    """
    raw_result = validator.validate_export(xml, export_id=export_id)
    return enforce_validation_mode(raw_result)


__all__ = [
    "VALIDATION_MODE_DEVELOPMENT",
    "VALIDATION_MODE_CERTIFICATION",
    "VALIDATION_MODE_PRODUCTION",
    "get_validation_mode",
    "is_strict_mode",
    "enforce_validation_mode",
    "validate_with_mode_enforcement",
]
