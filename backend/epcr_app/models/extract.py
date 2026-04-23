```python
"""Gravity-level compatibility exports for structured extraction models.

Authoritative source:
    epcr_app.models.structured_extraction

This module enforces:
- strict compatibility boundary for legacy imports
- zero symbol drift
- explicit export contract validation
- forward-safe aliasing guarantees
- import-time hard failure on contract violation
"""

from __future__ import annotations

from epcr_app.models.structured_extraction import (
    StructuredExtraction,
    TransportStructuredExtraction,
)

__all__ = [
    "StructuredExtraction",
    "TransportStructuredExtraction",
]


# -------------------------
# Integrity Enforcement
# -------------------------

def _validate_symbol_resolution() -> None:
    missing: list[str] = []

    for name in __all__:
        if name not in globals():
            missing.append(name)

    if missing:
        raise RuntimeError(
            f"Structured extraction export failure: missing symbols {missing}"
        )


def _validate_type_integrity() -> None:
    invalid: list[str] = []

    for name in __all__:
        obj = globals().get(name)

        if obj is None:
            invalid.append(name)
            continue

        # Must be class types (ORM models)
        if not isinstance(obj, type):
            invalid.append(name)

    if invalid:
        raise RuntimeError(
            f"Structured extraction export type violation: {invalid}"
        )


def _validate_export_surface() -> None:
    unexpected: list[str] = []

    for name in globals().keys():
        if name.startswith("_"):
            continue
        if name in {"annotations", "__all__"}:
            continue
        if name not in __all__:
            unexpected.append(name)

    if unexpected:
        raise RuntimeError(
            f"Unexpected symbols exposed in compatibility layer: {unexpected}"
        )


def _validate_uniqueness() -> None:
    if len(__all__) != len(set(__all__)):
        raise RuntimeError("Duplicate entries detected in __all__")


def _validate() -> None:
    _validate_uniqueness()
    _validate_symbol_resolution()
    _validate_type_integrity()
    _validate_export_surface()


_validate()
```
