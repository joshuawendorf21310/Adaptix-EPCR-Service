"""Convert and submit all 6 official 2025 NEMSIS v3.5.1 CTA test cases.

Pipeline per test case
----------------------
1. Pre-scan the HTML with :class:`HtmlParser` to discover every UUID,
   timestamp and ``[Your ...]`` placeholder key.
2. Construct a deterministic :class:`ConversionInput`:
   * UUIDs are derived by ``uuid.uuid5(NAMESPACE_URL, "urn:adaptix:cta:2025:<occurrence_key>")``
     so the same input always yields the same UUID.
   * Timestamps use a fixed submission anchor ``SUBMISSION_TIMESTAMP``.
   * ``[Your ...]`` placeholders resolve from ``PLACEHOLDER_VALUES`` and
     per-case ``PCR_NUMBERS``.
3. Call :func:`convert_html_to_nemsis_xml` to produce the NEMSIS XML.
4. Assert the generated root tag matches the expected dataset type.
5. Build the CTA SOAP envelope and POST to the live CTA endpoint.
6. Persist artifacts:
   * ``artifact/generated/2025/<test_case_id>.xml`` — generated NEMSIS XML
   * ``artifact/cta/2025/<test_case_id>-request.xml`` — SOAP request
   * ``artifact/cta/2025/<test_case_id>-response.xml`` — raw SOAP response
   * ``artifact/cta/2025/submission_log.json`` — structured log

CTA statusCode classification
-----------------------------
* ``> 0``  — SUCCESS (CTA imported the file)
* ``-1``   — AUTH failure (invalid credentials)
* ``-16``  — EXTERNAL COLLECT DATA BLOCK (key-element mismatch)
* other ``< 0`` — FAILURE with ``serverErrorMessage``

Credentials resolve from OS env -> repo ``.env`` file ONLY. No hardcoded
fallback values are permitted: if ``NEMSIS_CTA_USERNAME``,
``NEMSIS_CTA_PASSWORD`` or ``NEMSIS_CTA_ORGANIZATION`` are missing, the
script must fail explicitly before contacting CTA. SOAP credentials must
be retrieved from the CTA portal (https://cta.nemsis.org) by the operator
logged in with the organisation's Okta identity.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BACKEND_ROOT = _REPO_ROOT / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from epcr_app.nemsis.cta_html_to_xml import (
    ConversionInput,
    HtmlParser,
    convert_html_to_nemsis_xml,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


DEFAULT_ENDPOINT = (
    "https://cta.nemsis.org/ComplianceTestingWs/endpoints/compliancetestingws"
)
DEFAULT_SCHEMA_VERSION = "3.5.1"

_REQUIRED_CREDENTIAL_KEYS: tuple[str, ...] = (
    "NEMSIS_CTA_USERNAME",
    "NEMSIS_CTA_PASSWORD",
    "NEMSIS_CTA_ORGANIZATION",
)

SUBMISSION_TIMESTAMP = "2026-04-24T00:00:00-05:00"

UUID_NAMESPACE_SEED = "urn:adaptix:cta:2025"

PLACEHOLDER_VALUES: dict[str, str] = {
    "Software Creator": "Adaptix",
    "Software Name": "Adaptix ePCR",
    "Software Version": "1.0.0",
}

PCR_NUMBERS: dict[str, str] = {
    "2025-EMS-1-Allergy_v351": "FEMSQ-2025-EMS-00001",
    "2025-EMS-2-HeatStroke_v351": "FEMSQ-2025-EMS-00002",
    "2025-EMS-3-PediatricAsthma_v351": "FEMSQ-2025-EMS-00003",
    "2025-EMS-4-ArmTrauma_v351": "FEMSQ-2025-EMS-00004",
    "2025-EMS-5-MentalHealthCrisis_v351": "FEMSQ-2025-EMS-00005",
}


DEM_REFERENCES_GLOBAL: dict[str, str] = {}


DEM_REFERENCES: dict[str, dict[str, str]] = {}


TEST_CASES = [
    {
        "id": "2025-DEM-1_v351",
        "html_filename": "2025-DEM-1_v351.html",
        "data_schema": "62",
        "dataset_type": "DEMDataSet",
    },
    {
        "id": "2025-EMS-1-Allergy_v351",
        "html_filename": "2025-EMS-1-Allergy_v351.html",
        "data_schema": "61",
        "dataset_type": "EMSDataSet",
    },
    {
        "id": "2025-EMS-2-HeatStroke_v351",
        "html_filename": "2025-EMS-2-HeatStroke_v351.html",
        "data_schema": "61",
        "dataset_type": "EMSDataSet",
    },
    {
        "id": "2025-EMS-3-PediatricAsthma_v351",
        "html_filename": "2025-EMS-3-PediatricAsthma_v351.html",
        "data_schema": "61",
        "dataset_type": "EMSDataSet",
    },
    {
        "id": "2025-EMS-4-ArmTrauma_v351",
        "html_filename": "2025-EMS-4-ArmTrauma_v351.html",
        "data_schema": "61",
        "dataset_type": "EMSDataSet",
    },
    {
        "id": "2025-EMS-5-MentalHealthCrisis_v351",
        "html_filename": "2025-EMS-5-MentalHealthCrisis_v351.html",
        "data_schema": "61",
        "dataset_type": "EMSDataSet",
    },
]


def _load_env_file(env_path: Path) -> dict[str, str]:
    """Parse a ``.env`` file into a dict.

    Args:
        env_path: Path to the ``.env`` file.

    Returns:
        Mapping of variable names to values with surrounding quotes stripped.
    """

    result: dict[str, str] = {}
    if not env_path.exists():
        return result
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        result[key.strip()] = val.strip().strip('"').strip("'")
    return result


def _resolve(key: str, env_file: dict[str, str], default: str) -> str:
    """Resolve a config value from OS env, then .env file, then default.

    Args:
        key: Environment variable name.
        env_file: Mapping of values parsed from ``.env``.
        default: Fallback value when neither source provides one.

    Returns:
        Stripped resolved string.
    """

    val = os.environ.get(key) or env_file.get(key) or default
    return val.strip()


def _resolve_required_credential(key: str, env_file: dict[str, str]) -> str:
    """Resolve a required CTA SOAP credential with no silent fallback.

    Looks up ``key`` in OS env first, then in the parsed ``.env`` file.
    If the resolved value is empty or missing, raise a ``RuntimeError``
    containing explicit remediation instructions. Hardcoded default
    credentials are deliberately not accepted.

    Args:
        key: Credential environment-variable name (e.g. ``NEMSIS_CTA_USERNAME``).
        env_file: Mapping parsed from the repository ``.env`` file.

    Returns:
        The resolved credential value, stripped of surrounding whitespace.

    Raises:
        RuntimeError: If the credential is absent or empty.
    """

    raw = os.environ.get(key) or env_file.get(key) or ""
    val = raw.strip()
    if not val:
        raise RuntimeError(
            f"CTA SOAP credential '{key}' is not configured. "
            f"Set {', '.join(_REQUIRED_CREDENTIAL_KEYS)} in the "
            f"repository .env file or OS environment. "
            "Retrieve the official SOAP API username/password/organization "
            "from the CTA portal at https://cta.nemsis.org after logging in "
            "with the organisation's Okta identity. No hardcoded fallback "
            "credentials are permitted."
        )
    return val


def _stable_uuid(occurrence_key: str) -> str:
    """Return a deterministic UUID for an occurrence key.

    Args:
        occurrence_key: ``<element_id>[<index>]`` key produced by the parser.

    Returns:
        Deterministic UUID4-shaped string derived via UUID5.
    """

    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{UUID_NAMESPACE_SEED}:{occurrence_key}"))


def _build_conversion_input(html_path: Path, test_case_id: str) -> ConversionInput:
    """Pre-scan an HTML test case and construct its ConversionInput.

    Args:
        html_path: Path to the HTML test case.
        test_case_id: Identifier of the test case (used to pick PCR number).

    Returns:
        Fully-populated :class:`ConversionInput` for deterministic conversion.
    """

    parser = HtmlParser()
    _root_tag, cells = parser.parse(html_path)

    uuids: dict[str, str] = {}
    timestamps: dict[str, str] = {}
    placeholders: dict[str, str] = dict(PLACEHOLDER_VALUES)
    if test_case_id in PCR_NUMBERS:
        placeholders["Patient Care Report Number"] = PCR_NUMBERS[test_case_id]

    for cell in cells:
        if cell.needs_uuid_attr:
            uuids[cell.occurrence_key] = _stable_uuid(cell.occurrence_key)
        if cell.needs_timestamp_attr:
            timestamps[cell.occurrence_key] = SUBMISSION_TIMESTAMP

    return ConversionInput(
        uuids=uuids,
        timestamps=timestamps,
        placeholder_values=placeholders,
        dem_references={**DEM_REFERENCES_GLOBAL, **DEM_REFERENCES.get(test_case_id, {})},
    )


def _build_soap_envelope(
    *,
    username: str,
    password: str,
    organization: str,
    data_schema: str,
    schema_version: str,
    additional_info: str,
    xml_payload: str,
) -> str:
    """Build the NEMSIS CTA SOAP SubmitDataRequest envelope.

    Args:
        username: CTA SOAP username (VSA).
        password: CTA SOAP password.
        organization: Vendor/organisation name.
        data_schema: NEMSIS data schema code per WSDL NemsisDataSchema
            (``"61"`` = EMS / EMSDataSet, ``"62"`` = Demographics / DEMDataSet).
        schema_version: NEMSIS schema version string (e.g. ``"3.5.1"``).
        additional_info: Submission identifier for additionalInfo.
        xml_payload: Serialised NEMSIS XML string (any ``<?xml ... ?>``
            declaration is stripped before embedding).

    Returns:
        The SOAP envelope as a UTF-8 string.
    """

    payload_clean = re.sub(r"<\?xml[^?]*\?>\s*", "", xml_payload, count=1)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<soapenv:Envelope"
        ' xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"'
        ' xmlns:ws="http://ws.nemsis.org/">'
        "<soapenv:Header/>"
        "<soapenv:Body>"
        "<ws:SubmitDataRequest>"
        f"<ws:username>{username}</ws:username>"
        f"<ws:password>{password}</ws:password>"
        f"<ws:organization>{organization}</ws:organization>"
        "<ws:requestType>SubmitData</ws:requestType>"
        "<ws:submitPayload>"
        "<ws:payloadOfXmlElement>"
        f"{payload_clean}"
        "</ws:payloadOfXmlElement>"
        "</ws:submitPayload>"
        f"<ws:requestDataSchema>{data_schema}</ws:requestDataSchema>"
        f"<ws:schemaVersion>{schema_version}</ws:schemaVersion>"
        f"<ws:additionalInfo>{additional_info}</ws:additionalInfo>"
        "</ws:SubmitDataRequest>"
        "</soapenv:Body>"
        "</soapenv:Envelope>"
    )


def _extract_tag(xml_text: str, tag_name: str) -> str | None:
    """Extract the first matching tag value from a SOAP response.

    Args:
        xml_text: SOAP response body.
        tag_name: Local tag name to locate.

    Returns:
        The stripped text content, or ``None`` if the tag is absent/empty.
    """

    try:
        root = ET.fromstring(xml_text)
        for el in root.iter():
            if el.tag.endswith(tag_name):
                return (el.text or "").strip() or None
    except ET.ParseError:
        pass
    m = re.search(
        fr"<[^>]*{tag_name}[^>]*>(.*?)</[^>]*{tag_name}>", xml_text, re.DOTALL
    )
    if m:
        return m.group(1).strip() or None
    return None


def _classify_status(status_code: str | None) -> str:
    """Classify a CTA numeric statusCode into a human-readable label.

    Args:
        status_code: Numeric string from the ``statusCode`` response element.

    Returns:
        Classification label.
    """

    if status_code is None:
        return "UNKNOWN"
    try:
        code = int(status_code)
    except ValueError:
        return f"UNPARSEABLE_CODE({status_code})"
    if code > 0:
        return "SUCCESS"
    if code == -1:
        return "AUTH_FAILURE"
    if code == -16:
        return "EXTERNAL_COLLECT_DATA_BLOCK"
    return f"FAILURE(code={code})"


def run_submissions() -> None:
    """Convert and submit every CTA test case end-to-end.

    Returns:
        None.
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
    organization = _resolve_required_credential(
        "NEMSIS_CTA_ORGANIZATION", env_file
    )

    log.info("CTA endpoint: %s", endpoint)
    log.info("Username:     %s", username)
    log.info("Organization: %s", organization)

    log_path = cta_artifact_dir / "submission_log.json"
    submission_log: list[dict] = []
    summary_rows: list[dict] = []

    for tc in TEST_CASES:
        tc_id = tc["id"]
        html_path = html_dir / tc["html_filename"]
        output_xml_path = generated_dir / f"{tc_id}.xml"
        request_path = cta_artifact_dir / f"{tc_id}-request.xml"
        response_path = cta_artifact_dir / f"{tc_id}-response.xml"

        log.info("=" * 70)
        log.info("Processing: %s", tc_id)

        entry: dict = {
            "test_case_id": tc_id,
            "dataset_type": tc["dataset_type"],
            "data_schema": tc["data_schema"],
            "html_path": str(html_path),
            "generated_xml_path": str(output_xml_path),
            "submission_timestamp_utc": SUBMISSION_TIMESTAMP,
        }

        try:
            conversion_input = _build_conversion_input(html_path, tc_id)
            log.info(
                "Discovered: %d UUIDs, %d timestamps, %d placeholders",
                len(conversion_input.uuids),
                len(conversion_input.timestamps),
                len(conversion_input.placeholder_values),
            )

            xml_root = convert_html_to_nemsis_xml(
                html_path=html_path,
                state_xml_path=state_xml_path,
                output_path=output_xml_path,
                conversion_input=conversion_input,
            )
            log.info("Generated XML: %s", output_xml_path.name)

            ns_uri = "http://www.nemsis.org"
            generated_root_tag = xml_root.tag.replace(f"{{{ns_uri}}}", "")
            expected_root_tag = tc["dataset_type"]
            if generated_root_tag != expected_root_tag:
                msg = (
                    f"Root tag mismatch for {tc_id}: "
                    f"expected {expected_root_tag!r}, got {generated_root_tag!r}"
                )
                log.error(msg)
                entry["error"] = msg
                entry["status"] = "CONVERSION_ERROR"
                submission_log.append(entry)
                summary_rows.append(
                    {
                        "test_case": tc_id,
                        "http_status": None,
                        "soap_status_code": None,
                        "request_handle": None,
                        "classification": "CONVERSION_ERROR",
                        "error": msg,
                    }
                )
                continue

            xml_payload = output_xml_path.read_text(encoding="utf-8")

        except Exception as exc:
            log.exception("Conversion failed for %s: %s", tc_id, exc)
            entry["error"] = str(exc)
            entry["status"] = "CONVERSION_ERROR"
            submission_log.append(entry)
            summary_rows.append(
                {
                    "test_case": tc_id,
                    "http_status": None,
                    "soap_status_code": None,
                    "request_handle": None,
                    "classification": "CONVERSION_ERROR",
                    "error": str(exc),
                }
            )
            continue

        soap_envelope = _build_soap_envelope(
            username=username,
            password=password,
            organization=organization,
            data_schema=tc["data_schema"],
            schema_version=DEFAULT_SCHEMA_VERSION,
            additional_info=tc_id,
            xml_payload=xml_payload,
        )
        request_path.write_text(soap_envelope, encoding="utf-8")
        log.info("SOAP request written: %s", request_path.name)

        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": "http://ws.nemsis.org/SubmitData",
        }
        http_status: int | None = None
        response_text: str = ""
        try:
            with httpx.Client(timeout=60.0, verify=True) as client:
                log.info("POST -> %s", endpoint)
                resp = client.post(
                    endpoint,
                    content=soap_envelope.encode("utf-8"),
                    headers=headers,
                )
            http_status = resp.status_code
            response_text = resp.text
            log.info("HTTP %d received (%d bytes)", http_status, len(response_text))
        except Exception as exc:
            log.exception("HTTP request failed for %s: %s", tc_id, exc)
            entry["http_error"] = str(exc)
            entry["status"] = "HTTP_ERROR"
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

        entry.update(
            {
                "http_status": http_status,
                "soap_status_code": status_code,
                "request_handle": request_handle,
                "server_error_message": server_error,
                "classification": classification,
                "status": "SUBMITTED",
            }
        )
        submission_log.append(entry)
        summary_rows.append(
            {
                "test_case": tc_id,
                "http_status": http_status,
                "soap_status_code": status_code,
                "request_handle": request_handle,
                "classification": classification,
                "error": server_error,
            }
        )

    log_path.write_text(json.dumps(submission_log, indent=2), encoding="utf-8")
    log.info("Submission log written: %s", log_path)

    print("\n" + "=" * 110)
    print(
        f"{'TEST CASE':<42} {'HTTP':>5} {'SOAP':>6} {'CLASSIFICATION':<28} {'HANDLE/ERROR'}"
    )
    print("-" * 110)
    for row in summary_rows:
        handle_or_err = row.get("request_handle") or row.get("error") or ""
        if isinstance(handle_or_err, str) and len(handle_or_err) > 45:
            handle_or_err = handle_or_err[:45] + "..."
        print(
            f"{row['test_case']:<42} "
            f"{str(row['http_status'] or '')!s:>5} "
            f"{str(row['soap_status_code'] or '')!s:>6} "
            f"{row['classification']:<28} "
            f"{handle_or_err}"
        )
    print("=" * 110)
    print(f"\nArtifacts in: {cta_artifact_dir}")
    print(f"Log file:     {log_path}")


if __name__ == "__main__":
    run_submissions()
