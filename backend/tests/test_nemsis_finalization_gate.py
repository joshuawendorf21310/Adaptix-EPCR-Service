"""Tests for the Schematron Finalization Gate (Slice 2).

Covers:
* gate decision logic (errors block, warnings permit, unavailable does not block)
* natural-language messages preserved through normalization
* response shape distinguishes blocking vs non-blocking
* ``unavailable`` outcomes never fabricate a passing schematron verdict
* unit tests inject a fake schematron validator and pre-built XML so the
  tests do not require saxonche or the official schema assets to be present.

The official schematron validator is *protected* and is NOT modified, mocked
internally, or re-implemented. The gate only consumes its public surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from epcr_app.nemsis_finalization_gate import (
    GATE_STATUS_BLOCKED,
    GATE_STATUS_OK,
    GATE_STATUS_UNAVAILABLE,
    SchematronFinalizationGate,
    SchematronGateEvaluation,
)


# ---------------------------------------------------------------------------
# Fake validator matching the OfficialSchematronValidator structural contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _FakeIssue:
    role: str
    location: str
    text: str
    test: str | None = None


@dataclass(frozen=True)
class _FakeResult:
    is_valid: bool
    errors: list[_FakeIssue]
    warnings: list[_FakeIssue]


class _FakeValidator:
    def __init__(self, result: _FakeResult) -> None:
        self._result = result

    def validate(self, xml_bytes: bytes) -> _FakeResult:  # noqa: D401
        assert isinstance(xml_bytes, (bytes, bytearray))
        return self._result


class _RaisingValidator:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def validate(self, xml_bytes: bytes) -> Any:
        raise self._exc


SAMPLE_XML = b"<?xml version='1.0'?><EMSDataSet/>"


# ---------------------------------------------------------------------------
# Decision tests
# ---------------------------------------------------------------------------


class TestSchematronGateDecisions:
    def test_error_severity_blocks_finalization(self) -> None:
        validator = _FakeValidator(
            _FakeResult(
                is_valid=False,
                errors=[
                    _FakeIssue(
                        role="error",
                        location="/EMSDataSet/Header/AgencyName",
                        text="Agency name must not be empty.",
                        test="string-length(.) > 0",
                    )
                ],
                warnings=[],
            )
        )

        evaluation = SchematronFinalizationGate().evaluate(
            SAMPLE_XML, validator=validator
        )

        assert evaluation.blocked is True
        assert evaluation.can_finalize is False
        assert evaluation.status == GATE_STATUS_BLOCKED
        assert len(evaluation.errors) == 1
        assert evaluation.errors[0].severity == "error"
        assert evaluation.errors[0].message == "Agency name must not be empty."
        assert evaluation.errors[0].location.endswith("AgencyName")
        assert evaluation.blocking_reason is not None
        assert "1 error-severity" in evaluation.blocking_reason

    def test_warning_only_permits_finalization(self) -> None:
        validator = _FakeValidator(
            _FakeResult(
                is_valid=True,
                errors=[],
                warnings=[
                    _FakeIssue(
                        role="warning",
                        location="/EMSDataSet/Header/AgencyState",
                        text="Agency state is recommended but missing.",
                        test="exists(.)",
                    )
                ],
            )
        )

        evaluation = SchematronFinalizationGate().evaluate(
            SAMPLE_XML, validator=validator
        )

        assert evaluation.blocked is False
        assert evaluation.can_finalize is True
        assert evaluation.status == GATE_STATUS_OK
        assert evaluation.errors == []
        assert len(evaluation.warnings) == 1
        assert evaluation.warnings[0].severity == "warning"
        assert (
            evaluation.warnings[0].message
            == "Agency state is recommended but missing."
        )
        assert evaluation.blocking_reason is None

    def test_no_issues_returns_ok(self) -> None:
        validator = _FakeValidator(
            _FakeResult(is_valid=True, errors=[], warnings=[])
        )

        evaluation = SchematronFinalizationGate().evaluate(
            SAMPLE_XML, validator=validator
        )

        assert evaluation.status == GATE_STATUS_OK
        assert evaluation.blocked is False
        assert evaluation.can_finalize is True
        assert evaluation.errors == []
        assert evaluation.warnings == []

    def test_errors_and_warnings_together_block_but_surface_warnings(
        self,
    ) -> None:
        validator = _FakeValidator(
            _FakeResult(
                is_valid=False,
                errors=[
                    _FakeIssue(
                        role="error",
                        location="/EMSDataSet/Patient/DOB",
                        text="Patient date of birth is invalid.",
                        test="matches(., '\\d{4}-\\d{2}-\\d{2}')",
                    )
                ],
                warnings=[
                    _FakeIssue(
                        role="warning",
                        location="/EMSDataSet/Patient/Race",
                        text="Patient race is recommended.",
                        test="exists(.)",
                    )
                ],
            )
        )

        evaluation = SchematronFinalizationGate().evaluate(
            SAMPLE_XML, validator=validator
        )

        assert evaluation.blocked is True
        assert evaluation.can_finalize is False
        assert len(evaluation.errors) == 1
        assert len(evaluation.warnings) == 1
        # Distinction: blocking issues live in errors, non-blocking in warnings.
        assert evaluation.errors[0].severity == "error"
        assert evaluation.warnings[0].severity == "warning"


# ---------------------------------------------------------------------------
# Unavailability tests (gate must NEVER fabricate a passing schematron verdict)
# ---------------------------------------------------------------------------


class TestSchematronGateUnavailability:
    def test_no_xml_returns_unavailable_without_blocking(self) -> None:
        evaluation = SchematronFinalizationGate().evaluate(None)

        assert evaluation.status == GATE_STATUS_UNAVAILABLE
        assert evaluation.blocked is False
        assert evaluation.can_finalize is True
        assert evaluation.unavailable_reason is not None
        assert "No NEMSIS XML" in evaluation.unavailable_reason

    def test_validator_raises_returns_unavailable_without_blocking(self) -> None:
        validator = _RaisingValidator(RuntimeError("saxonche missing"))

        evaluation = SchematronFinalizationGate().evaluate(
            SAMPLE_XML, validator=validator
        )

        assert evaluation.status == GATE_STATUS_UNAVAILABLE
        assert evaluation.blocked is False
        assert evaluation.can_finalize is True
        assert evaluation.unavailable_reason is not None
        assert "saxonche missing" in evaluation.unavailable_reason

    def test_unavailable_status_never_claims_passing_verdict(self) -> None:
        evaluation = SchematronFinalizationGate().evaluate(None)

        # Unavailable means we did not run schematron. The evaluation must
        # never claim status == "ok" in that case.
        assert evaluation.status != GATE_STATUS_OK
        assert evaluation.status != GATE_STATUS_BLOCKED


# ---------------------------------------------------------------------------
# Payload shape tests
# ---------------------------------------------------------------------------


class TestSchematronGatePayload:
    def test_payload_distinguishes_blocking_vs_non_blocking(self) -> None:
        validator = _FakeValidator(
            _FakeResult(
                is_valid=False,
                errors=[
                    _FakeIssue(
                        role="error",
                        location="/EMSDataSet/Patient/Last",
                        text="Patient last name is required.",
                        test="exists(.)",
                    )
                ],
                warnings=[
                    _FakeIssue(
                        role="warning",
                        location="/EMSDataSet/Patient/Middle",
                        text="Middle name not provided.",
                        test="exists(.)",
                    )
                ],
            )
        )

        payload = (
            SchematronFinalizationGate()
            .evaluate(SAMPLE_XML, validator=validator)
            .to_payload()
        )

        assert payload["can_finalize"] is False
        assert payload["blocked"] is True
        assert payload["status"] == GATE_STATUS_BLOCKED
        assert payload["blocking_reason"] is not None
        assert len(payload["errors"]) == 1
        assert len(payload["warnings"]) == 1
        assert payload["errors"][0]["severity"] == "error"
        assert (
            payload["errors"][0]["natural_language_message"]
            == "Patient last name is required."
        )
        assert payload["warnings"][0]["severity"] == "warning"

    def test_natural_language_message_preserved_for_warnings(self) -> None:
        validator = _FakeValidator(
            _FakeResult(
                is_valid=True,
                errors=[],
                warnings=[
                    _FakeIssue(
                        role="warning",
                        location="/EMSDataSet/Times/Dispatch",
                        text="Dispatch time is recommended for QA review.",
                        test="exists(.)",
                    )
                ],
            )
        )

        payload = (
            SchematronFinalizationGate()
            .evaluate(SAMPLE_XML, validator=validator)
            .to_payload()
        )

        assert payload["can_finalize"] is True
        assert payload["blocked"] is False
        assert payload["status"] == GATE_STATUS_OK
        assert payload["warnings"][0]["natural_language_message"] == (
            "Dispatch time is recommended for QA review."
        )

    def test_unavailable_payload_does_not_claim_pass_or_block(self) -> None:
        payload = (
            SchematronFinalizationGate().evaluate(None).to_payload()
        )

        assert payload["can_finalize"] is True
        assert payload["blocked"] is False
        assert payload["status"] == GATE_STATUS_UNAVAILABLE
        assert payload["blocking_reason"] is None
        assert payload["unavailable_reason"] is not None
        assert payload["errors"] == []
        assert payload["warnings"] == []

    def test_missing_message_text_does_not_silently_drop_issue(self) -> None:
        validator = _FakeValidator(
            _FakeResult(
                is_valid=False,
                errors=[
                    _FakeIssue(
                        role="error",
                        location="/EMSDataSet/Patient/Sex",
                        text="",  # validator emitted an empty message
                        test=None,
                    )
                ],
                warnings=[],
            )
        )

        evaluation: SchematronGateEvaluation = (
            SchematronFinalizationGate().evaluate(
                SAMPLE_XML, validator=validator
            )
        )
        assert evaluation.blocked is True
        assert evaluation.errors[0].message != ""
        # Honesty: a missing natural-language string is disclosed, not faked.
        assert "no natural-language" in evaluation.errors[0].message.lower()


# ---------------------------------------------------------------------------
# Default validator construction failure path
# ---------------------------------------------------------------------------


def test_default_validator_construction_failure_returns_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the official validator cannot be constructed, gate is unavailable."""

    import epcr_app.nemsis_finalization_gate as gate_module

    real_evaluate = gate_module.SchematronFinalizationGate.evaluate

    # Force the lazy import inside ``evaluate`` to fail, simulating a
    # missing ``saxonche`` or absent schematron schema files in this env.
    import sys

    fake_module_name = "epcr_app.nemsis.schematron_validator"
    saved = sys.modules.get(fake_module_name)

    class _Boom:
        def __getattr__(self, item: str) -> Any:
            raise RuntimeError("simulated missing schematron asset")

    sys.modules[fake_module_name] = _Boom()  # type: ignore[assignment]
    try:
        evaluation = real_evaluate(
            gate_module.SchematronFinalizationGate(),
            SAMPLE_XML,
        )
    finally:
        if saved is None:
            sys.modules.pop(fake_module_name, None)
        else:
            sys.modules[fake_module_name] = saved

    assert evaluation.status == GATE_STATUS_UNAVAILABLE
    assert evaluation.blocked is False
    assert evaluation.can_finalize is True
    assert evaluation.unavailable_reason is not None
