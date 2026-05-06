"""Schematron-driven finalization gate for ePCR charts.

This module is **additive**. It does not modify any existing NEMSIS validator,
XML builder, CTA client, submission router, pack manager, runtime injector,
or template loader/resolver. It only **calls** their public surfaces.

TAC contract this gate enforces (see TAC Testing Web Conference checklist):

* Schematron **error** result → record cannot be finalized (gate blocks).
* Schematron **warning** result → record can still be finalized (gate permits
  finalization but surfaces the natural-language warning).
* Schematron unavailable (e.g. saxonche or schema assets not present in the
  current environment) → gate returns ``unavailable`` and DOES NOT block,
  preserving the previously documented behavior of the finalize endpoint.

The gate is intentionally honest about three failure modes:

1. ``ok``           — gate ran, no blocking errors.
2. ``blocked``      — gate ran, schematron raised at least one error-severity
                      assertion. Finalization must be rejected.
3. ``unavailable``  — gate could not run (no schema, no saxonche, no built
                      XML, etc.). Finalization is NOT blocked here, because
                      blocking on uncertainty would be a fake-success of the
                      opposite polarity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol


GATE_STATUS_OK = "ok"
GATE_STATUS_BLOCKED = "blocked"
GATE_STATUS_UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class SchematronGateIssue:
    """Normalized natural-language schematron issue surfaced to API/UI."""

    severity: str  # "error" or "warning"
    message: str
    location: str
    test: str | None
    role: str


@dataclass(frozen=True)
class SchematronGateEvaluation:
    """Outcome of evaluating the schematron finalization gate.

    Attributes:
        can_finalize: True if finalization should be permitted.
        blocked: True if the gate explicitly blocked finalization.
        status: One of ``ok``, ``blocked``, ``unavailable``.
        errors: Natural-language error issues (always empty when not blocked
            by errors; warnings never appear in this list).
        warnings: Natural-language warning issues (do not block finalization).
        blocking_reason: Human-readable summary of why finalization was
            blocked, or ``None`` when not blocked.
        unavailable_reason: Human-readable reason the schematron path could
            not execute, or ``None`` when it executed.
    """

    can_finalize: bool
    blocked: bool
    status: str
    errors: list[SchematronGateIssue] = field(default_factory=list)
    warnings: list[SchematronGateIssue] = field(default_factory=list)
    blocking_reason: str | None = None
    unavailable_reason: str | None = None

    def to_payload(self) -> dict[str, Any]:
        """Serialize the evaluation into a JSON-safe dict for API responses."""

        return {
            "can_finalize": self.can_finalize,
            "blocked": self.blocked,
            "status": self.status,
            "blocking_reason": self.blocking_reason,
            "unavailable_reason": self.unavailable_reason,
            "errors": [_issue_to_dict(issue) for issue in self.errors],
            "warnings": [_issue_to_dict(issue) for issue in self.warnings],
        }


def _issue_to_dict(issue: SchematronGateIssue) -> dict[str, Any]:
    return {
        "severity": issue.severity,
        "natural_language_message": issue.message,
        "location": issue.location,
        "test": issue.test,
        "role": issue.role,
    }


class _SchematronValidatorLike(Protocol):
    """Minimal structural type for any schematron validator the gate accepts.

    Matches ``OfficialSchematronValidator.validate`` from
    ``epcr_app.nemsis.schematron_validator`` without importing or modifying
    that module's internals.
    """

    def validate(self, xml_bytes: bytes) -> Any:  # pragma: no cover - structural
        ...


class SchematronFinalizationGate:
    """Evaluate schematron output and decide whether finalize is permitted.

    The gate accepts either a pre-built XML bytestring or a structured
    schematron result. It never invents a "passing" verdict when the
    underlying validator could not run.
    """

    def evaluate(
        self,
        xml_bytes: bytes | None,
        *,
        validator: _SchematronValidatorLike | None = None,
    ) -> SchematronGateEvaluation:
        """Run schematron against ``xml_bytes`` and decide gate outcome.

        Args:
            xml_bytes: Built NEMSIS XML for the chart, or ``None`` if the
                chart could not be lifted to XML in this environment.
            validator: Optional injectable validator. When ``None``, the
                official validator is constructed lazily; if construction
                fails (missing assets, missing saxonche), the gate degrades
                to ``unavailable`` instead of fabricating success.

        Returns:
            SchematronGateEvaluation describing the outcome.
        """

        if xml_bytes is None:
            return SchematronGateEvaluation(
                can_finalize=True,
                blocked=False,
                status=GATE_STATUS_UNAVAILABLE,
                unavailable_reason="No NEMSIS XML available for this chart.",
            )

        active_validator = validator
        if active_validator is None:
            try:
                # Imported lazily so test environments without saxonche / schema
                # assets can still import this module and run unit tests
                # against the gate's decision logic via injected validators.
                from epcr_app.nemsis.schematron_validator import (
                    OfficialSchematronValidator,
                )

                active_validator = OfficialSchematronValidator()
            except Exception as exc:  # noqa: BLE001 — explicit unavailability
                return SchematronGateEvaluation(
                    can_finalize=True,
                    blocked=False,
                    status=GATE_STATUS_UNAVAILABLE,
                    unavailable_reason=(
                        f"Schematron validator unavailable: {exc}"
                    ),
                )

        try:
            result = active_validator.validate(xml_bytes)
        except Exception as exc:  # noqa: BLE001 — explicit unavailability
            return SchematronGateEvaluation(
                can_finalize=True,
                blocked=False,
                status=GATE_STATUS_UNAVAILABLE,
                unavailable_reason=(
                    f"Schematron validation could not execute: {exc}"
                ),
            )

        errors = _normalize_issues(getattr(result, "errors", ()) or (), "error")
        warnings = _normalize_issues(
            getattr(result, "warnings", ()) or (), "warning"
        )

        if errors:
            return SchematronGateEvaluation(
                can_finalize=False,
                blocked=True,
                status=GATE_STATUS_BLOCKED,
                errors=errors,
                warnings=warnings,
                blocking_reason=(
                    f"Schematron reported {len(errors)} error-severity "
                    f"assertion(s). Finalization is blocked until each "
                    f"natural-language error is resolved."
                ),
            )

        return SchematronGateEvaluation(
            can_finalize=True,
            blocked=False,
            status=GATE_STATUS_OK,
            errors=[],
            warnings=warnings,
        )


def _normalize_issues(
    raw_issues: Iterable[Any], severity: str
) -> list[SchematronGateIssue]:
    """Normalize the validator's per-issue dataclass into a transport shape."""

    normalized: list[SchematronGateIssue] = []
    for issue in raw_issues:
        message = _safe_str(getattr(issue, "text", "")).strip()
        location = _safe_str(getattr(issue, "location", "")).strip()
        test = getattr(issue, "test", None)
        test_str = _safe_str(test).strip() if test is not None else None
        role = _safe_str(getattr(issue, "role", severity)).strip() or severity
        normalized.append(
            SchematronGateIssue(
                severity=severity,
                message=message or "(no natural-language message provided)",
                location=location,
                test=test_str,
                role=role,
            )
        )
    return normalized


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


__all__ = [
    "GATE_STATUS_BLOCKED",
    "GATE_STATUS_OK",
    "GATE_STATUS_UNAVAILABLE",
    "SchematronFinalizationGate",
    "SchematronGateEvaluation",
    "SchematronGateIssue",
]
