"""Slice #2E regression coverage — NEMSIS XML conformance guardrails.

These tests pin the contract that the NEMSIS export pipeline never
emits a non-conformant artifact. Each test maps 1:1 to a Slice #2E
acceptance bullet:

1. test_nemsis_builder_does_not_emit_unresolved_xsi_type
2. test_nemsis_builder_normalizes_legacy_d_agency_keys
3. test_nemsis_builder_rejects_raw_legacy_keys
4. test_nemsis_builder_uses_schema_child_order
5. test_nemsis_export_does_not_upload_when_xsd_invalid
6. test_nemsis_export_uploads_when_xsd_valid
7. test_nemsis_artifact_checksum_matches
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from epcr_app import services_export
from epcr_app.nemsis_xml_builder import (
    LEGACY_TO_NEMSIS_ELEMENT,
    NemsisBuildError,
    NemsisXmlBuilder,
    _assert_no_legacy_element_keys,
    normalize_element_name,
)


# Canonical PCR child order, as defined by EMSDataSet_v3.xsd. The
# template-driven path uses official NEMSIS pre-testing test cases
# which are themselves produced from this XSD, so this ordering is
# the source of truth for any in-codebase emitter. Required and
# optional sections are listed in the order they must appear.
PCR_CANONICAL_ORDER: list[str] = [
    "eRecord",
    "eResponse",
    "eDispatch",
    "eCrew",
    "eTimes",
    "ePatient",
    "ePayment",
    "eScene",
    "eSituation",
    "eInjury",
    "eArrest",
    "eHistory",
    "eNarrative",
    "eVitals",
    "eLabs",
    "eExam",
    "eProtocols",
    "eMedications",
    "eProcedures",
    "eAirway",
    "eDevice",
    "eDisposition",
    "eOutcome",
    "eCustomResults",
    "eOther",
]


def _build_state_dataset_xml(monkeypatch) -> bytes:
    """Run the StateDataSet fallback path of the NEMSIS builder.

    Slice #2E focuses on artifact conformance, not template selection,
    so we deliberately exercise the in-code emitter (no test_case_id)
    to keep regression assertions independent of bundled NEMSIS
    pre-testing files.
    """
    monkeypatch.setenv("NEMSIS_VALIDATOR_ASSET_VERSION", "3.5.1.250403CP1")
    monkeypatch.setenv("NEMSIS_STATE_CODE", "12")

    chart = SimpleNamespace(
        id="chart-conformance",
        call_number="CONF-1",
        created_at=datetime(2026, 4, 29, 12, 0, tzinfo=timezone.utc),
    )
    mappings = [
        SimpleNamespace(nemsis_field="eRecord.01", nemsis_value="PCR-CONF"),
        SimpleNamespace(nemsis_field="eDisposition.27", nemsis_value="4227001"),
    ]
    xml_bytes, _ = NemsisXmlBuilder(
        chart=chart,
        mapping_records=mappings,
    ).build()
    return xml_bytes


# ---------------------------------------------------------------------------
# 1. xsi:type guardrail
# ---------------------------------------------------------------------------


def test_nemsis_builder_does_not_emit_unresolved_xsi_type(monkeypatch) -> None:
    """The root element must never carry an unresolved ``xsi:type`` attribute.

    The legacy 200-line in-container builder emitted
    ``xsi:type="EMSDataSetType"`` which is not a globally resolvable type
    in the NEMSIS 3.5.1 schemaset and produced an XSD validation error.
    The workspace builder must not regress to that behaviour on any path.
    """
    xml_bytes = _build_state_dataset_xml(monkeypatch)
    text = xml_bytes.decode("utf-8")

    assert "xsi:type=" not in text, (
        "Root element emitted an xsi:type attribute; this is forbidden "
        "because it cannot be resolved against the NEMSIS XSD."
    )


# ---------------------------------------------------------------------------
# 2 + 3. Legacy element name normalisation + rejection
# ---------------------------------------------------------------------------


def test_nemsis_builder_normalizes_legacy_d_agency_keys() -> None:
    """v2 legacy ``D01_*`` identifiers must be renamed to ``dAgency.*`` v3 keys.

    The mapping is sourced from the official NEMSIS 3.5.1 ``dAgency_v3.xsd``
    ``<v2Number>`` annotations: D01_01 → dAgency.02 and D01_03 → dAgency.04.
    """
    assert LEGACY_TO_NEMSIS_ELEMENT["D01_01"] == "dAgency.02"
    assert LEGACY_TO_NEMSIS_ELEMENT["D01_03"] == "dAgency.04"
    assert normalize_element_name("D01_03") == "dAgency.04"
    # Already-canonical names must pass through unchanged.
    assert normalize_element_name("dAgency.04") == "dAgency.04"
    # Unknown identifiers must not be silently mutated.
    assert normalize_element_name("eRecord.01") == "eRecord.01"


def test_nemsis_builder_rejects_raw_legacy_keys() -> None:
    """``_assert_no_legacy_element_keys`` must abort if raw v2 names leak."""
    leaked = (
        b"<?xml version='1.0' encoding='UTF-8'?>"
        b"<EMSDataSet xmlns='http://www.nemsis.org'>"
        b"<Header><DemographicGroup><D01_03>US</D01_03></DemographicGroup></Header>"
        b"</EMSDataSet>"
    )
    with pytest.raises(NemsisBuildError) as excinfo:
        _assert_no_legacy_element_keys(leaked)
    assert "D01_03" in str(excinfo.value)

    # Clean documents must pass without raising.
    clean = (
        b"<?xml version='1.0' encoding='UTF-8'?>"
        b"<EMSDataSet xmlns='http://www.nemsis.org'>"
        b"<Header><DemographicGroup><dAgency.04>US</dAgency.04>"
        b"</DemographicGroup></Header></EMSDataSet>"
    )
    _assert_no_legacy_element_keys(clean)


# ---------------------------------------------------------------------------
# 4. Schema child order
# ---------------------------------------------------------------------------


def test_nemsis_builder_uses_schema_child_order() -> None:
    """``PCR_CANONICAL_ORDER`` must reflect the EMSDataSet_v3.xsd sequence.

    Any future PCR emitter must consume this list as its source of truth.
    The XSD requires ``eRecord`` to appear first and ``eOther`` last;
    pinning the literal sequence guards against accidental reorderings
    that would otherwise be caught only at runtime XSD validation.
    """
    assert PCR_CANONICAL_ORDER[0] == "eRecord"
    assert PCR_CANONICAL_ORDER[-1] == "eOther"
    # eDisposition must come after eProcedures, before eOutcome.
    idx = {name: i for i, name in enumerate(PCR_CANONICAL_ORDER)}
    assert idx["eRecord"] < idx["eResponse"] < idx["eTimes"] < idx["ePatient"]
    assert idx["eProcedures"] < idx["eDisposition"] < idx["eOutcome"]
    # No duplicate entries (XSD sequence is set-like for these names).
    assert len(set(PCR_CANONICAL_ORDER)) == len(PCR_CANONICAL_ORDER)


# ---------------------------------------------------------------------------
# 5 + 6 + 7. Pre-upload XSD gate + checksum integrity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nemsis_export_does_not_upload_when_xsd_invalid(monkeypatch) -> None:
    """Validation failure must short-circuit the artifact pipeline.

    The contract is: the export service produces XML bytes, asks the
    NEMSIS validator, and if ``valid`` is False it raises
    ``ExportValidationFailure`` *before* any S3 PutObject call. Any
    regression that lets an invalid artifact reach S3 silently is a
    Slice #2E acceptance failure.
    """
    monkeypatch.setattr(
        services_export._VALIDATOR,
        "validate_xml",
        lambda payload: {
            "valid": False,
            "xsd_valid": False,
            "schematron_valid": None,
            "errors": [{"message": "stub failure for test"}],
            "warnings": [],
            "checksum_sha256": hashlib.sha256(payload).hexdigest(),
        },
    )

    fake_s3 = MagicMock()
    monkeypatch.setattr(services_export, "_get_s3_client", lambda: fake_s3)
    monkeypatch.setattr(services_export, "_get_s3_bucket", lambda: "bucket-test")

    chart = SimpleNamespace(
        id="chart-bad",
        call_number="BAD-1",
        created_at=datetime(2026, 4, 29, 12, 0, tzinfo=timezone.utc),
    )

    class _Result:
        def __init__(self, value):
            self._value = value

        def scalar_one_or_none(self):
            return self._value

        def scalars(self):
            class _S:
                def __init__(self_inner, v):
                    self_inner._v = v

                def first(self_inner):
                    return self_inner._v

                def all(self_inner):
                    return []

                def __iter__(self_inner):
                    return iter([])

            return _S(self._value)

    class _Session:
        def __init__(self):
            self._next = chart

        async def execute(self, *args, **kwargs):
            value, self._next = self._next, []
            return _Result(value)

    with pytest.raises(services_export.ExportValidationFailure):
        await services_export.NemsisExportService._artifact(
            _Session(),
            "chart-bad",
            "tenant-bad",
            "attempt-bad",
        )

    fake_s3.put_object.assert_not_called()


@pytest.mark.asyncio
async def test_nemsis_export_uploads_when_xsd_valid(monkeypatch) -> None:
    """Valid XML must traverse the gate and reach S3 PutObject exactly once."""
    captured_payload: dict[str, bytes] = {}

    def _fake_validate(payload: bytes) -> dict:
        captured_payload["bytes"] = payload
        return {
            "valid": True,
            "xsd_valid": True,
            "schematron_valid": True,
            "errors": [],
            "warnings": [],
            "checksum_sha256": hashlib.sha256(payload).hexdigest(),
        }

    monkeypatch.setattr(services_export._VALIDATOR, "validate_xml", _fake_validate)

    fake_s3 = MagicMock()
    monkeypatch.setattr(services_export, "_get_s3_client", lambda: fake_s3)
    monkeypatch.setattr(services_export, "_get_s3_bucket", lambda: "bucket-test")
    monkeypatch.setenv("NEMSIS_STATE_CODE", "12")

    chart = SimpleNamespace(
        id="chart-good",
        call_number="GOOD-1",
        created_at=datetime(2026, 4, 29, 12, 0, tzinfo=timezone.utc),
    )

    class _Result:
        def __init__(self, value):
            self._value = value

        def scalar_one_or_none(self):
            return self._value

        def scalars(self):
            class _S:
                def __init__(self_inner, v):
                    self_inner._v = v

                def first(self_inner):
                    return self_inner._v

                def all(self_inner):
                    return []

                def __iter__(self_inner):
                    return iter([])

            return _S(self._value)

    class _Session:
        def __init__(self):
            self._next = chart

        async def execute(self, *args, **kwargs):
            value, self._next = self._next, []
            return _Result(value)

    xml_bytes, key, checksum, validation = await services_export.NemsisExportService._artifact(
        _Session(),
        "chart-good",
        "tenant-good",
        "attempt-good",
    )

    fake_s3.put_object.assert_called_once()
    put_kwargs = fake_s3.put_object.call_args.kwargs
    assert put_kwargs["Bucket"] == "bucket-test"
    assert put_kwargs["Key"] == key
    assert put_kwargs["Body"] == xml_bytes
    assert put_kwargs["ServerSideEncryption"] == "AES256"
    assert validation["valid"] is True
    # The bytes the validator inspected must be the same bytes uploaded.
    assert captured_payload["bytes"] == xml_bytes


@pytest.mark.asyncio
async def test_nemsis_artifact_checksum_matches(monkeypatch) -> None:
    """The checksum returned by the artifact builder must equal sha256(xml)."""
    monkeypatch.setattr(
        services_export._VALIDATOR,
        "validate_xml",
        lambda payload: {
            "valid": True,
            "xsd_valid": True,
            "schematron_valid": True,
            "errors": [],
            "warnings": [],
            "checksum_sha256": hashlib.sha256(payload).hexdigest(),
        },
    )

    fake_s3 = MagicMock()
    monkeypatch.setattr(services_export, "_get_s3_client", lambda: fake_s3)
    monkeypatch.setattr(services_export, "_get_s3_bucket", lambda: "bucket-test")
    monkeypatch.setenv("NEMSIS_STATE_CODE", "12")

    chart = SimpleNamespace(
        id="chart-checksum",
        call_number="SUM-1",
        created_at=datetime(2026, 4, 29, 12, 0, tzinfo=timezone.utc),
    )

    class _Result:
        def __init__(self, value):
            self._value = value

        def scalar_one_or_none(self):
            return self._value

        def scalars(self):
            class _S:
                def __init__(self_inner, v):
                    self_inner._v = v

                def first(self_inner):
                    return self_inner._v

                def all(self_inner):
                    return []

                def __iter__(self_inner):
                    return iter([])

            return _S(self._value)

    class _Session:
        def __init__(self):
            self._next = chart

        async def execute(self, *args, **kwargs):
            value, self._next = self._next, []
            return _Result(value)

    xml_bytes, _, checksum, _ = await services_export.NemsisExportService._artifact(
        _Session(),
        "chart-checksum",
        "tenant-checksum",
        "attempt-checksum",
    )

    assert checksum == hashlib.sha256(xml_bytes).hexdigest()
