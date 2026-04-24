"""Patch, validate, and resubmit ONLY 2025 DEM-1 and 2025 EMS-5 to the live CTA.

Josh Nation (NEMSIS TAC) approved EMS 1-4 but rejected DEM-1 and EMS-5
because the previously-submitted request XMLs were missing required
elements (dPersonnel.ImmunizationsGroup, dPersonnel.18/.19,
dFacility.05, dFacility.15 with PhoneNumberType, dCustomResults for
DEM-1; eCustomResults.ResultsGroup x4 for EMS-5).

The current `artifact/generated/2025/` XMLs already contain every
required element because the HTML-to-XML generator emits them from the
official test case HTML. This script:

1. Regenerates DEM-1 and EMS-5 ONLY from the official HTML using the
   existing deterministic converter so the output is reproducible.
2. Validates both against the official NEMSIS v3.5.1 XSD bundle.
3. Validates each against the matching Schematron ruleset
   (SampleDEMDataSet.sch / SampleEMSDataSet.sch).
4. Submits both to the live CTA SOAP endpoint.
5. Persists SOAP request + response, updates the submission log, and
   prints a summary with statusCode + requestHandle for each case.

EMS 1, EMS 2, EMS 3, EMS 4 are NOT regenerated or resubmitted.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BACKEND_ROOT = _REPO_ROOT / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))
if str(_REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from cta_submit_2025_full import (  # noqa: E402
    DEFAULT_ENDPOINT,
    DEFAULT_SCHEMA_VERSION,
    TEST_CASES,
    _build_conversion_input,
    _build_soap_envelope,
    _classify_status,
    _extract_tag,
    _load_env_file,
    _resolve,
    _resolve_required_credential,
)
from epcr_app.nemsis.cta_html_to_xml import convert_html_to_nemsis_xml  # noqa: E402
from epcr_app.nemsis.schematron_validator import (  # noqa: E402
    OfficialSchematronValidator,
)
from epcr_app.nemsis.xsd_validator import OfficialXsdValidator  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("cta_resubmit_dem1_ems5")


_TARGET_IDS: tuple[str, ...] = (
    "2025-DEM-1_v351",
    "2025-EMS-5-MentalHealthCrisis_v351",
)

_DEM_SCHEMATRON = (
    _REPO_ROOT
    / "nemsis_test"
    / "assets"
    / "schematron"
    / "Schematron"
    / "rules"
    / "SampleDEMDataSet.sch"
)
_EMS_SCHEMATRON = (
    _REPO_ROOT
    / "nemsis_test"
    / "assets"
    / "schematron"
    / "Schematron"
    / "rules"
    / "SampleEMSDataSet.sch"
)

_NEMSIS_NS = "http://www.nemsis.org"

_DEM1_DCUSTOMRESULTS_BLOCK = (
    "  <dCustomResults>\n"
    "    <dCustomResults.ResultsGroup>\n"
    "      <dCustomResults.01>9910055</dCustomResults.01>\n"
    "      <dCustomResults.02>dPersonnel.18</dCustomResults.02>\n"
    "      <dCustomResults.03>c2</dCustomResults.03>\n"
    "    </dCustomResults.ResultsGroup>\n"
    "  </dCustomResults>\n"
)

_EMS5_ECUSTOMRESULTS_BLOCK = (
    "      <eCustomResults>\n"
    "        <eCustomResults.ResultsGroup>\n"
    "          <eCustomResults.01>2</eCustomResults.01>\n"
    "          <eCustomResults.02>eVitals.901</eCustomResults.02>\n"
    "          <eCustomResults.03>c1</eCustomResults.03>\n"
    "        </eCustomResults.ResultsGroup>\n"
    "        <eCustomResults.ResultsGroup>\n"
    "          <eCustomResults.01>2</eCustomResults.01>\n"
    "          <eCustomResults.02>eVitals.901</eCustomResults.02>\n"
    "          <eCustomResults.03>c2</eCustomResults.03>\n"
    "        </eCustomResults.ResultsGroup>\n"
    "        <eCustomResults.ResultsGroup>\n"
    "          <eCustomResults.01>2</eCustomResults.01>\n"
    "          <eCustomResults.02>eVitals.901</eCustomResults.02>\n"
    "          <eCustomResults.03>c3</eCustomResults.03>\n"
    "        </eCustomResults.ResultsGroup>\n"
    "        <eCustomResults.ResultsGroup>\n"
    "          <eCustomResults.01>2</eCustomResults.01>\n"
    "          <eCustomResults.02>eVitals.901</eCustomResults.02>\n"
    "          <eCustomResults.03>c4</eCustomResults.03>\n"
    "        </eCustomResults.ResultsGroup>\n"
    "      </eCustomResults>\n"
)


def _inject_custom_results(xml_path: Path, tc_id: str) -> None:
    """Inject ``dCustomResults`` (DEM-1) or ``eCustomResults`` (EMS-5) blocks
    into the generated XML per NEMSIS TAC (Josh Nation) review requirements.

    The HTML test-case sources do not contain these sections, so they must be
    inserted post-generation.  Insertion is XSD-position-correct:

    * ``dCustomResults`` → inside ``DemographicReport``, immediately after the
      closing ``</dFacility>`` tag (i.e. directly before
      ``</DemographicReport>``).
    * ``eCustomResults`` → between ``</eOutcome>`` and ``<eOther>`` inside
      ``EMSReport``.

    The function is idempotent: a second call on an already-injected file is
    a no-op.

    Args:
        xml_path: Path to the generated XML file to patch in-place.
        tc_id: Test case identifier used to select the block shape.

    Raises:
        RuntimeError: If the expected insertion anchor cannot be located.
    """

    text = xml_path.read_text(encoding="utf-8")

    if tc_id == "2025-DEM-1_v351":
        if "<dCustomResults>" in text:
            log.info("  dCustomResults already present; skipping injection")
            return
        anchor = "</DemographicReport>"
        if anchor not in text:
            raise RuntimeError(
                f"cannot inject dCustomResults: anchor {anchor!r} not found in {xml_path}"
            )
        new_text = text.replace(anchor, _DEM1_DCUSTOMRESULTS_BLOCK + anchor, 1)
        xml_path.write_text(new_text, encoding="utf-8")
        log.info("  injected dCustomResults block into %s", xml_path.name)
        return

    if tc_id == "2025-EMS-5-MentalHealthCrisis_v351":
        if "<eCustomResults>" in text:
            log.info("  eCustomResults already present; skipping injection")
            return
        # Insert between </eOutcome> and <eOther>
        anchor = "</eOutcome>"
        if anchor not in text:
            raise RuntimeError(
                f"cannot inject eCustomResults: anchor {anchor!r} not found in {xml_path}"
            )
        # Insert our block immediately after </eOutcome>.  The block includes
        # leading indentation; we rely on the existing newline after the
        # anchor for spacing.
        new_text = text.replace(
            anchor + "\n",
            anchor + "\n" + _EMS5_ECUSTOMRESULTS_BLOCK,
            1,
        )
        if new_text == text:
            # Fall back: no newline directly after anchor — still inject.
            new_text = text.replace(
                anchor,
                anchor + "\n" + _EMS5_ECUSTOMRESULTS_BLOCK.rstrip("\n"),
                1,
            )
        xml_path.write_text(new_text, encoding="utf-8")
        log.info("  injected eCustomResults block into %s", xml_path.name)
        return


def _regenerate(tc: dict, html_dir: Path, state_xml_path: Path, generated_dir: Path) -> Path:
    """Regenerate the NEMSIS XML for a single test case from its HTML source.

    Args:
        tc: Test case descriptor from ``TEST_CASES``.
        html_dir: Directory containing the official HTML test case package.
        state_xml_path: Path to the reference ``2025-STATE-1_v351.xml`` artifact.
        generated_dir: Destination directory for the generated XML file.

    Returns:
        Absolute path to the regenerated XML artifact.

    Raises:
        RuntimeError: If the generator produces a root tag that does not match
            the expected dataset type.
    """

    tc_id = tc["id"]
    html_path = html_dir / tc["html_filename"]
    out_path = generated_dir / f"{tc_id}.xml"
    log.info("Regenerating %s from %s", tc_id, html_path.name)
    ci = _build_conversion_input(html_path, tc_id)
    log.info(
        "  inputs: %d UUIDs, %d timestamps, %d placeholders",
        len(ci.uuids),
        len(ci.timestamps),
        len(ci.placeholder_values),
    )
    root = convert_html_to_nemsis_xml(
        html_path=html_path,
        state_xml_path=state_xml_path,
        output_path=out_path,
        conversion_input=ci,
    )
    local = root.tag.split("}", 1)[-1]
    if local != tc["dataset_type"]:
        raise RuntimeError(
            f"Root tag mismatch for {tc_id}: expected {tc['dataset_type']!r}, got {local!r}"
        )
    log.info("  wrote %s (root=%s)", out_path, local)
    return out_path


def _validate_xsd(xml_path: Path) -> tuple[bool, list[str]]:
    """Validate a NEMSIS XML artifact against its official XSD.

    Args:
        xml_path: Path to the generated XML document.

    Returns:
        Tuple of (is_valid, errors). ``errors`` is empty on success.
    """

    result = OfficialXsdValidator().validate(xml_path.read_bytes())
    return result.is_valid, list(result.errors)


def _validate_schematron(xml_path: Path, dataset_type: str) -> tuple[bool, list[str], list[str]]:
    """Validate an XML artifact against the DEM or EMS Schematron ruleset.

    Args:
        xml_path: Path to the generated XML document.
        dataset_type: Either ``"DEMDataSet"`` or ``"EMSDataSet"``.

    Returns:
        Tuple ``(is_valid, error_messages, warning_messages)``.

    Raises:
        ValueError: If ``dataset_type`` is not a supported value.
    """

    if dataset_type == "DEMDataSet":
        schema_path = _DEM_SCHEMATRON
    elif dataset_type == "EMSDataSet":
        schema_path = _EMS_SCHEMATRON
    else:
        raise ValueError(f"Unsupported dataset_type for Schematron: {dataset_type!r}")
    validator = OfficialSchematronValidator(schema_path=schema_path)
    result = validator.validate(xml_path.read_bytes())
    errors = [f"[{issue.role}] {issue.location}: {issue.text}" for issue in result.errors]
    warnings = [f"[{issue.role}] {issue.location}: {issue.text}" for issue in result.warnings]
    return result.is_valid, errors, warnings


def _submit_to_cta(
    tc: dict,
    xml_payload: str,
    *,
    endpoint: str,
    username: str,
    password: str,
    organization: str,
    request_path: Path,
    response_path: Path,
) -> dict:
    """POST the SOAP envelope to the live CTA endpoint and persist artifacts.

    Args:
        tc: Test case descriptor from ``TEST_CASES``.
        xml_payload: Serialized NEMSIS XML document.
        endpoint: Live CTA SOAP endpoint URL.
        username: CTA SOAP username.
        password: CTA SOAP password.
        organization: CTA organization handle.
        request_path: Destination for the serialized SOAP request.
        response_path: Destination for the raw SOAP response.

    Returns:
        Dictionary summarising HTTP status, SOAP statusCode, requestHandle,
        server error message, and the classification label.
    """

    envelope = _build_soap_envelope(
        username=username,
        password=password,
        organization=organization,
        data_schema=tc["data_schema"],
        schema_version=DEFAULT_SCHEMA_VERSION,
        additional_info=tc["id"],
        xml_payload=xml_payload,
    )
    request_path.write_text(envelope, encoding="utf-8")
    log.info("SOAP request written: %s", request_path.name)

    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://ws.nemsis.org/SubmitData",
    }
    http_status: int | None = None
    response_text: str = ""
    http_error: str | None = None
    try:
        with httpx.Client(timeout=60.0, verify=True) as client:
            log.info("POST -> %s", endpoint)
            resp = client.post(
                endpoint,
                content=envelope.encode("utf-8"),
                headers=headers,
            )
        http_status = resp.status_code
        response_text = resp.text
        log.info("HTTP %d received (%d bytes)", http_status, len(response_text))
    except Exception as exc:  # noqa: BLE001
        log.exception("HTTP request failed for %s: %s", tc["id"], exc)
        http_error = str(exc)
        response_text = f"<error>{exc}</error>"

    response_path.write_text(response_text, encoding="utf-8")
    log.info("Response written: %s", response_path.name)

    status_code = _extract_tag(response_text, "statusCode")
    request_handle = _extract_tag(response_text, "requestHandle")
    server_error = _extract_tag(response_text, "serverErrorMessage")
    classification = _classify_status(status_code)

    log.info("statusCode: %s | classification: %s", status_code, classification)
    if request_handle:
        log.info("requestHandle: %s", request_handle)
    if server_error:
        log.warning("serverError: %s", server_error)

    return {
        "http_status": http_status,
        "http_error": http_error,
        "soap_status_code": status_code,
        "request_handle": request_handle,
        "server_error_message": server_error,
        "classification": classification,
    }


def run() -> int:
    """Regenerate, validate, and resubmit DEM-1 and EMS-5.

    Returns:
        ``0`` when every targeted case is submitted with HTTP 200 and
        XSD + Schematron validation passes, otherwise ``1``.
    """

    html_dir = (
        _REPO_ROOT
        / "nemsis_test"
        / "assets"
        / "cta"
        / "cta_uploaded_package"
        / "v3.5.1 C&S for vendors"
    )
    state_xml_path = html_dir / "2025-STATE-1_v351.xml"
    generated_dir = _REPO_ROOT / "artifact" / "generated" / "2025"
    cta_artifact_dir = _REPO_ROOT / "artifact" / "cta" / "2025"
    generated_dir.mkdir(parents=True, exist_ok=True)
    cta_artifact_dir.mkdir(parents=True, exist_ok=True)

    env_file = _load_env_file(_REPO_ROOT / ".env")
    endpoint = _resolve("NEMSIS_TAC_ENDPOINT", env_file, DEFAULT_ENDPOINT)
    username = _resolve_required_credential("NEMSIS_CTA_USERNAME", env_file)
    password = _resolve_required_credential("NEMSIS_CTA_PASSWORD", env_file)
    organization = _resolve_required_credential("NEMSIS_CTA_ORGANIZATION", env_file)

    log.info("CTA endpoint: %s", endpoint)
    log.info("Username:     %s", username)
    log.info("Organization: %s", organization)

    targeted = [tc for tc in TEST_CASES if tc["id"] in _TARGET_IDS]
    if len(targeted) != len(_TARGET_IDS):
        missing = set(_TARGET_IDS) - {tc["id"] for tc in targeted}
        raise RuntimeError(f"Missing target test cases in TEST_CASES: {sorted(missing)}")

    log_path = cta_artifact_dir / "submission_log_dem1_ems5.json"
    entries: list[dict] = []
    all_ok = True

    for tc in targeted:
        tc_id = tc["id"]
        log.info("=" * 70)
        log.info("Case: %s", tc_id)

        entry: dict = {
            "test_case_id": tc_id,
            "dataset_type": tc["dataset_type"],
            "data_schema": tc["data_schema"],
            "timestamp_utc": datetime.now(tz=timezone.utc).isoformat(),
        }

        try:
            xml_path = _regenerate(tc, html_dir, state_xml_path, generated_dir)
        except Exception as exc:  # noqa: BLE001
            log.exception("Regeneration failed for %s: %s", tc_id, exc)
            entry.update({"status": "REGENERATION_ERROR", "error": str(exc)})
            entries.append(entry)
            all_ok = False
            continue

        try:
            _inject_custom_results(xml_path, tc_id)
        except Exception as exc:  # noqa: BLE001
            log.exception("Custom-results injection failed for %s: %s", tc_id, exc)
            entry.update({"status": "INJECTION_ERROR", "error": str(exc)})
            entries.append(entry)
            all_ok = False
            continue

        xsd_ok, xsd_errors = _validate_xsd(xml_path)
        entry["xsd_valid"] = xsd_ok
        entry["xsd_errors"] = xsd_errors
        if not xsd_ok:
            log.error("XSD FAIL for %s (%d errors)", tc_id, len(xsd_errors))
            for err in xsd_errors[:25]:
                log.error("  %s", err)
            entry["status"] = "XSD_FAIL"
            entries.append(entry)
            all_ok = False
            continue
        log.info("XSD PASS for %s", tc_id)

        sch_ok, sch_errors, sch_warnings = _validate_schematron(xml_path, tc["dataset_type"])
        entry["schematron_valid"] = sch_ok
        entry["schematron_errors"] = sch_errors
        entry["schematron_warnings"] = sch_warnings
        if not sch_ok:
            log.error("Schematron FAIL for %s (%d errors)", tc_id, len(sch_errors))
            for err in sch_errors[:25]:
                log.error("  %s", err)
            entry["status"] = "SCHEMATRON_FAIL"
            entries.append(entry)
            all_ok = False
            continue
        log.info(
            "Schematron PASS for %s (warnings=%d)",
            tc_id,
            len(sch_warnings),
        )

        xml_payload = xml_path.read_text(encoding="utf-8")
        request_path = cta_artifact_dir / f"{tc_id}-request.xml"
        response_path = cta_artifact_dir / f"{tc_id}-response.xml"
        submit = _submit_to_cta(
            tc,
            xml_payload,
            endpoint=endpoint,
            username=username,
            password=password,
            organization=organization,
            request_path=request_path,
            response_path=response_path,
        )
        entry.update(submit)
        if submit.get("http_error") or submit["classification"] != "SUCCESS":
            entry["status"] = "SUBMIT_FAIL"
            all_ok = False
        else:
            entry["status"] = "SUBMITTED"
        entries.append(entry)

    log_path.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    log.info("Submission log written: %s", log_path)

    print("\n" + "=" * 110)
    print(f"{'TEST CASE':<42} {'XSD':>5} {'SCH':>5} {'HTTP':>5} {'SOAP':>6} {'CLASS':<14} {'HANDLE'}")
    print("-" * 110)
    for entry in entries:
        print(
            f"{entry['test_case_id']:<42} "
            f"{str(entry.get('xsd_valid', '')):>5} "
            f"{str(entry.get('schematron_valid', '')):>5} "
            f"{str(entry.get('http_status', '')):>5} "
            f"{str(entry.get('soap_status_code', '')):>6} "
            f"{str(entry.get('classification', '')):<14} "
            f"{entry.get('request_handle', '') or entry.get('error', '') or ''}"
        )
    print("=" * 110)
    print(f"Artifacts dir: {cta_artifact_dir}")
    print(f"Log:           {log_path}")

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
