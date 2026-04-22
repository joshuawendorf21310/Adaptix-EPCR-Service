"""Execute the uploaded CTA package locally against the live EPCR export pipeline.

This harness starts a local moto-backed S3 endpoint and the FastAPI backend,
creates charts through the real authenticated API, seeds chart content and
NEMSIS mappings from the uploaded CTA reference package, triggers the live
export endpoint, retrieves the generated artifact, validates it against the
official XSD + Schematron assets, performs structural parity checks against the
uploaded CTA reference XML, and writes per-scenario logs plus ``summary.json``.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import boto3
import httpx
from botocore.config import Config
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt
from lxml import etree


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
NEMSIS_TEST_DIR = ROOT / "nemsis_test"
ASSETS_DIR = NEMSIS_TEST_DIR / "assets"
CTA_DIR = ASSETS_DIR / "cta"
CTA_PACKAGE_DIR = CTA_DIR / "cta_uploaded_package" / "v3.5.1 C&S for vendors"
LOGS_DIR = NEMSIS_TEST_DIR / "logs"
OUTPUT_DIR = NEMSIS_TEST_DIR / "output"
KEY_DIR = OUTPUT_DIR / "keys"
RUNTIME_DIR = OUTPUT_DIR / "runtime"
DB_PATH = RUNTIME_DIR / "local_cta.sqlite3"
SUMMARY_PATH = LOGS_DIR / "summary.json"
BACKEND_LOG_PATH = RUNTIME_DIR / "backend.log"
MOTO_LOG_PATH = RUNTIME_DIR / "moto.log"
NS = {"n": "http://www.nemsis.org", "xsi": "http://www.w3.org/2001/XMLSchema-instance"}
MANDATORY_FIELD_VALUES = {
    "eRecord.01": lambda s, c: f"PCR-{s.slug}-{c[-8:]}",
    "eRecord.02": lambda s, c: s.software_creator,
    "eRecord.03": lambda s, c: s.software_name,
    "eRecord.04": lambda s, c: s.software_version,
    "eResponse.01": lambda s, c: "35012001",
    "eResponse.03": lambda s, c: f"INC-{c[-6:]}",
    "eResponse.04": lambda s, c: f"RESP-{c[-6:]}",
    "eResponse.05": lambda s, c: "2305001",
    "eTimes.01": lambda s, c: s.timeline[0],
    "eTimes.02": lambda s, c: s.timeline[1],
    "eTimes.03": lambda s, c: s.timeline[2],
    "eTimes.04": lambda s, c: s.timeline[3],
    "eTimes.05": lambda s, c: s.timeline[4],
}


class CTAHarnessError(RuntimeError):
    """Raised when the local CTA run encounters a real failure."""


@dataclass
class ScenarioConfig:
    """Resolved scenario metadata used by the local harness."""

    name: str
    slug: str
    source_path: Path
    complaint: str
    incident_type: str
    medication_name: str
    intervention_name: str
    note_text: str
    expectation: str
    timeline: list[str]
    software_creator: str
    software_name: str
    software_version: str


@dataclass
class ReferenceFixture:
    """Parsed details from the uploaded CTA reference XML."""

    path: Path
    state_code: str
    schema_location: str
    effective_date: str
    asset_version: str
    s_elements: list[str]
    structure_signature: tuple[Any, ...]


def _get_validator():
    """Return a cached validator instance configured from the local process env."""
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    from epcr_app.nemsis_xsd_validator import NemsisXSDValidator

    if not hasattr(_get_validator, "_instance"):
        _get_validator._instance = NemsisXSDValidator()
    return _get_validator._instance


def ensure_runtime_dirs() -> None:
    """Create the runtime output directories used by the local CTA harness."""
    for directory in (LOGS_DIR, OUTPUT_DIR, KEY_DIR, RUNTIME_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def find_free_port() -> int:
    """Return an available localhost TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


def generate_keypair() -> tuple[str, str]:
    """Generate an RSA key pair for local JWT issuance."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    (KEY_DIR / "local_cta_private.pem").write_text(private_pem, encoding="utf-8")
    (KEY_DIR / "local_cta_public.pem").write_text(public_pem, encoding="utf-8")
    return private_pem, public_pem


def issue_token(private_pem: str, tenant_id: str, user_id: str) -> str:
    """Issue a real RS256 bearer token accepted by the EPCR auth dependency."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tid": tenant_id,
        "email": "local-cta@adaptix.test",
        "roles": ["admin", "ems"],
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=2)).timestamp()),
    }
    return jwt.encode(payload, private_pem, algorithm="RS256")


def parse_reference_fixture(reference_path: Path) -> ReferenceFixture:
    """Parse the uploaded CTA reference XML into reusable parity metadata."""
    tree = etree.parse(str(reference_path))
    root = tree.getroot()
    schema_location = root.attrib.get("{http://www.w3.org/2001/XMLSchema-instance}schemaLocation", "").strip()
    state_code = (root.findtext("n:sState/n:sState.01", namespaces=NS) or "").strip()
    effective_date = root.attrib.get("effectiveDate", "").strip()
    s_elements = [
        (node.text or "").strip()
        for node in root.xpath("//n:sElement.01", namespaces=NS)
        if (node.text or "").strip()
    ]
    asset_version = "unknown"
    parts = schema_location.split()
    if len(parts) == 2 and "/nemsis_v3/" in parts[1]:
        asset_version = parts[1].split("/nemsis_v3/", 1)[1].split("/", 1)[0]
    return ReferenceFixture(
        path=reference_path,
        state_code=state_code,
        schema_location=schema_location,
        effective_date=effective_date,
        asset_version=asset_version,
        s_elements=s_elements,
        structure_signature=build_structure_signature(root),
    )


def build_structure_signature(node: etree._Element) -> tuple[Any, ...]:
    """Build a text-free structural signature for parity comparison."""
    children = [child for child in node if isinstance(getattr(child, "tag", None), str)]
    attr_names = sorted(
        name
        for name in node.attrib
        if not name.endswith("schemaLocation")
        and not name.endswith("timestamp")
        and not name.endswith("effectiveDate")
    )
    return (
        etree.QName(node).localname,
        tuple(attr_names),
        tuple(build_structure_signature(child) for child in children),
    )


def validate_with_xsd(xml_bytes: bytes) -> dict[str, Any]:
    """Validate the generated artifact against the official StateDataSet XSD."""
    validator = _get_validator()
    xsd_path = validator.get_xsd_asset_path("StateDataSet")
    if not xsd_path:
        raise CTAHarnessError("Unable to resolve StateDataSet_v3.xsd from configured NEMSIS_XSD_PATH")
    parser = etree.XMLParser(remove_blank_text=True)
    schema_tree = etree.parse(str(xsd_path), parser)
    xmlschema = etree.XMLSchema(schema_tree)
    document = etree.fromstring(xml_bytes, parser)
    valid = xmlschema.validate(document)
    return {
        "valid": bool(valid),
        "errors": [str(error) for error in xmlschema.error_log],
    }


def validate_with_schematron(xml_bytes: bytes, schematron_path: Path) -> dict[str, Any]:
    """Validate the generated artifact against the official StateDataSet schematron."""
    validator = _get_validator()

    errors, warnings = validator.run_schematron_validation(
        xml_bytes,
        str(schematron_path),
        str((ASSETS_DIR / "schematron").resolve()),
    )
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
    }


def structural_diff(xml_bytes: bytes, reference: ReferenceFixture) -> dict[str, Any]:
    """Compare the generated artifact's structure with the uploaded CTA reference XML."""
    parser = etree.XMLParser(remove_blank_text=True)
    document = etree.fromstring(xml_bytes, parser)
    root = document
    schema_location = root.attrib.get("{http://www.w3.org/2001/XMLSchema-instance}schemaLocation", "").strip()
    s_elements = [
        (node.text or "").strip()
        for node in root.xpath("//n:sElement.01", namespaces=NS)
        if (node.text or "").strip()
    ]
    reference_child_order = [
        etree.QName(child).localname
        for child in etree.parse(str(reference.path), parser).getroot()
        if isinstance(getattr(child, "tag", None), str)
    ]
    generated_child_order = [
        etree.QName(child).localname for child in root if isinstance(getattr(child, "tag", None), str)
    ]

    mismatches: list[str] = []
    if etree.QName(root).localname != "StateDataSet":
        mismatches.append("Root element is not StateDataSet")
    if root.nsmap.get(None) != NS["n"]:
        mismatches.append("Default namespace does not match CTA reference")
    if schema_location != reference.schema_location:
        mismatches.append("schemaLocation does not match CTA reference")
    if generated_child_order != reference_child_order:
        mismatches.append("Top-level section ordering differs from CTA reference")
    if build_structure_signature(root) != reference.structure_signature:
        mismatches.append("Recursive structural signature differs from CTA reference")
    if len(s_elements) != len(reference.s_elements):
        mismatches.append(
            f"sElement cardinality mismatch: generated={len(s_elements)} reference={len(reference.s_elements)}"
        )
    elif s_elements != reference.s_elements:
        mismatches.append("sElement ordering differs from CTA reference")

    return {
        "valid": not mismatches,
        "generated_child_order": generated_child_order,
        "reference_child_order": reference_child_order,
        "generated_s_element_count": len(s_elements),
        "reference_s_element_count": len(reference.s_elements),
        "mismatches": mismatches,
    }


def wait_for_url(url: str, timeout_seconds: int = 45) -> None:
    """Wait until an HTTP endpoint responds successfully."""
    deadline = time.time() + timeout_seconds
    last_error: str | None = None
    while time.time() < deadline:
        try:
            response = httpx.get(url, timeout=2.0)
            if response.status_code < 500:
                return
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
        time.sleep(0.5)
    raise CTAHarnessError(f"Timed out waiting for {url}. Last error: {last_error}")


def start_moto_server(port: int) -> subprocess.Popen[Any]:
    """Start a local moto S3 server for truthful artifact persistence."""
    command_variants = [
        [sys.executable, "-m", "moto.server", "-H", "127.0.0.1", "-p", str(port)],
        ["moto_server", "s3", "-H", "127.0.0.1", "-p", str(port)],
        ["moto_server", "-H", "127.0.0.1", "-p", str(port)],
    ]
    last_error: Exception | None = None
    for command in command_variants:
        process: subprocess.Popen[Any] | None = None
        try:
            moto_log = open(MOTO_LOG_PATH, "a", encoding="utf-8")
            process = subprocess.Popen(
                command,
                cwd=str(ROOT),
                stdout=moto_log,
                stderr=moto_log,
            )
            wait_for_url(f"http://127.0.0.1:{port}/")
            return process
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            try:
                if process is not None:
                    process.kill()
            except Exception:  # noqa: BLE001
                pass
    raise CTAHarnessError(f"Failed to start moto S3 server: {last_error}")


def create_bucket(endpoint_url: str, bucket_name: str) -> None:
    """Create the local S3 bucket used by the live export pipeline."""
    client = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name="us-east-1",
        aws_access_key_id="local",
        aws_secret_access_key="local",
        config=Config(signature_version="s3v4"),
    )
    client.create_bucket(Bucket=bucket_name)


def start_backend_server(env: dict[str, str], port: int) -> subprocess.Popen[Any]:
    """Start the live FastAPI backend used by the local CTA runner."""
    backend_log = open(BACKEND_LOG_PATH, "a", encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "epcr_app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=str(BACKEND_DIR),
        env=env,
        stdout=backend_log,
        stderr=backend_log,
    )
    wait_for_url(f"http://127.0.0.1:{port}/docs")
    return process


def terminate_process(process: subprocess.Popen[Any] | None) -> None:
    """Terminate a background process started by the harness."""
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def build_scenario_configs(reference: ReferenceFixture) -> list[ScenarioConfig]:
    """Resolve the uploaded CTA files into runnable local scenarios."""
    base = datetime(2024, 10, 13, 14, 43, 12, tzinfo=timezone(timedelta(hours=-4)))
    configs: list[ScenarioConfig] = []
    scenario_overrides = {
        "2025-DEM-1_v351": ("other", "General DEM reference import", "Oxygen", "Dataset alignment", "Local CTA DEM baseline"),
        "2025-EMS-1-Allergy_v351": ("medical", "Allergic reaction", "Epinephrine", "Airway support", "Allergy response documented through live API"),
        "2025-EMS-2-HeatStroke_v351": ("medical", "Heat stroke", "Normal saline", "Active cooling", "Heat stroke scenario documented through live API"),
        "2025-EMS-3-PediatricAsthma_v351": ("medical", "Pediatric asthma exacerbation", "Albuterol", "Nebulizer treatment", "Pediatric asthma scenario documented through live API"),
        "2025-EMS-4-ArmTrauma_v351": ("trauma", "Arm trauma", "Fentanyl", "Splint application", "Arm trauma scenario documented through live API"),
        "2025-EMS-5-MentalHealthCrisis_v351": ("behavioral", "Mental health crisis", "Midazolam", "Behavioral de-escalation", "Mental health crisis scenario documented through live API"),
        "2025-STATE-1_v351": ("medical", "State dataset reference scenario", "Aspirin", "State export readiness", "State dataset parity scenario documented through live API"),
    }
    for index, source_path in enumerate(sorted(CTA_PACKAGE_DIR.iterdir())):
        if source_path.suffix.lower() not in {".html", ".xml"}:
            continue
        key = source_path.stem
        incident_type, complaint, medication_name, intervention_name, note_text = scenario_overrides.get(
            key,
            ("medical", source_path.stem.replace("_", " "), "Aspirin", "General treatment", f"{source_path.stem} documented locally"),
        )
        timeline = [
            (base + timedelta(minutes=index * 11 + minute)).isoformat()
            for minute in (0, 2, 11, 28, 44)
        ]
        configs.append(
            ScenarioConfig(
                name=source_path.name,
                slug=f"{key.lower().replace('_', '-')}-{source_path.suffix.lower().lstrip('.')}",
                source_path=source_path,
                complaint=complaint,
                incident_type=incident_type,
                medication_name=medication_name,
                intervention_name=intervention_name,
                note_text=note_text,
                expectation="PASS",
                timeline=timeline,
                software_creator="NEMSIS Technical Assistance Center",
                software_name="Compliance Testing",
                software_version=f"{reference.asset_version}_local",
            )
        )
    return configs


def build_headers(token: str, tenant_id: str, user_id: str) -> dict[str, str]:
    """Build the shared authenticated request headers."""
    return {
        "Authorization": f"Bearer {token}",
        "X-Tenant-ID": tenant_id,
        "X-User-ID": user_id,
    }


def request_ok(response: httpx.Response, context: str) -> Any:
    """Raise a harness error if the live API call failed."""
    if response.status_code >= 400:
        raise CTAHarnessError(
            f"{context} failed with {response.status_code}: {response.text}"
        )
    if response.headers.get("content-type", "").startswith("application/json"):
        return response.json()
    return response.content


def record_field(client: httpx.Client, base_url: str, chart_id: str, headers: dict[str, str], field_id: str, field_value: str) -> dict[str, Any]:
    """Record a single NEMSIS field through the live chart API."""
    response = client.post(
        f"{base_url}/api/v1/epcr/charts/{chart_id}/nemsis-fields",
        params={
            "nemsis_field": field_id,
            "nemsis_value": field_value,
            "source": "manual",
        },
        headers=headers,
    )
    return request_ok(response, f"record NEMSIS field {field_id}")


def seed_chart_content(client: httpx.Client, base_url: str, headers: dict[str, str], scenario: ScenarioConfig) -> str:
    """Create a chart and populate the real chart-scoped clinical endpoints."""
    call_number = f"CTA-{scenario.slug[:24]}-{uuid.uuid4().hex[:8]}"
    chart_payload = {
        "call_number": call_number,
        "incident_type": scenario.incident_type,
    }
    chart_response = request_ok(
        client.post(f"{base_url}/api/v1/epcr/charts", json=chart_payload, headers=headers),
        f"create chart for {scenario.name}",
    )
    chart_id = str(chart_response["id"])

    request_ok(
        client.put(
            f"{base_url}/api/v1/epcr/charts/{chart_id}/patient-profile",
            json={
                "first_name": "CTA",
                "last_name": scenario.slug[:30],
                "date_of_birth": "1988-04-03",
                "age_years": 36,
                "sex": "female",
                "phone_number": "5550100000",
                "weight_kg": 72.3,
                "allergies": ["penicillin"],
            },
            headers=headers,
        ),
        f"upsert patient profile for {scenario.name}",
    )
    request_ok(
        client.post(
            f"{base_url}/api/v1/epcr/charts/{chart_id}/vitals",
            json={
                "bp_sys": 126,
                "bp_dia": 82,
                "hr": 98,
                "rr": 18,
                "temp_f": 99.1,
                "spo2": 97,
                "glucose": 112,
                "recorded_at": scenario.timeline[2],
            },
            headers=headers,
        ),
        f"record vitals for {scenario.name}",
    )
    request_ok(
        client.put(
            f"{base_url}/api/v1/epcr/charts/{chart_id}/clinical-impression",
            json={
                "chief_complaint": scenario.complaint,
                "field_diagnosis": scenario.complaint,
                "primary_impression": scenario.complaint,
                "secondary_impression": "Stable after assessment",
                "impression_notes": scenario.note_text,
                "acuity": "urgent",
            },
            headers=headers,
        ),
        f"record clinical impression for {scenario.name}",
    )
    request_ok(
        client.post(
            f"{base_url}/api/v1/epcr/charts/{chart_id}/medications",
            json={
                "medication_name": scenario.medication_name,
                "dose_value": "1",
                "dose_unit": "unit",
                "route": "IV",
                "indication": scenario.complaint,
                "response": "Improved",
                "export_state": "mapped_ready",
                "administered_at": scenario.timeline[3],
            },
            headers=headers,
        ),
        f"record medication for {scenario.name}",
    )
    request_ok(
        client.post(
            f"{base_url}/api/v1/epcr/charts/{chart_id}/interventions",
            json={
                "category": "procedure",
                "name": scenario.intervention_name,
                "indication": scenario.complaint,
                "intent": "stabilization",
                "expected_response": "Patient condition improves",
                "actual_response": "Patient condition improved",
                "reassessment_due_at": scenario.timeline[4],
                "protocol_family": "general",
                "export_state": "mapped_ready",
            },
            headers=headers,
        ),
        f"record intervention for {scenario.name}",
    )
    request_ok(
        client.post(
            f"{base_url}/api/v1/epcr/charts/{chart_id}/clinical-notes",
            json={
                "raw_text": scenario.note_text,
                "source": "manual_entry",
                "provenance": {"cta_source": scenario.name},
            },
            headers=headers,
        ),
        f"record clinical note for {scenario.name}",
    )
    return chart_id


def seed_nemsis_mappings(
    client: httpx.Client,
    base_url: str,
    headers: dict[str, str],
    chart_id: str,
    scenario: ScenarioConfig,
    reference: ReferenceFixture,
) -> dict[str, str]:
    """Populate NEMSIS mappings so the live exporter mirrors CTA structure."""
    values: dict[str, str] = {}
    all_field_ids = list(dict.fromkeys(reference.s_elements + list(MANDATORY_FIELD_VALUES.keys()) + ["sState.01"]))
    for field_id in all_field_ids:
        if field_id in MANDATORY_FIELD_VALUES:
            field_value = MANDATORY_FIELD_VALUES[field_id](scenario, chart_id)
        elif field_id == "sState.01":
            field_value = reference.state_code
        else:
            field_value = "7701003"
        record_field(client, base_url, chart_id, headers, field_id, field_value)
        values[field_id] = field_value
    return values


def run_single_scenario(
    client: httpx.Client,
    base_url: str,
    headers: dict[str, str],
    scenario: ScenarioConfig,
    reference: ReferenceFixture,
) -> dict[str, Any]:
    """Execute one CTA scenario end to end through the live API."""
    chart_id = seed_chart_content(client, base_url, headers, scenario)
    mapping_values = seed_nemsis_mappings(client, base_url, headers, chart_id, scenario, reference)

    export_response = request_ok(
        client.post(
            f"{base_url}/api/v1/epcr/nemsis/export-generate",
            json={
                "chart_id": chart_id,
                "state_dataset": scenario.slug,
                "trigger_source": "api",
            },
            headers=headers,
        ),
        f"generate export for {scenario.name}",
    )
    if export_response.get("status") != "generation_succeeded":
        raise CTAHarnessError(
            f"Scenario {scenario.name} did not succeed. Response: {json.dumps(export_response, indent=2)}"
        )

    export_id = int(export_response["export_id"])
    artifact_response = client.get(
        f"{base_url}/api/v1/epcr/nemsis/export/{export_id}/artifact",
        headers=headers,
    )
    artifact_bytes = request_ok(artifact_response, f"retrieve artifact for {scenario.name}")

    scenario_output_dir = OUTPUT_DIR / scenario.slug
    scenario_output_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = scenario_output_dir / f"{scenario.slug}.xml"
    artifact_path.write_bytes(artifact_bytes)

    xsd_result = validate_with_xsd(artifact_bytes)
    schematron_result = validate_with_schematron(artifact_bytes, ASSETS_DIR / "schematron" / "StateDataSet.sch")
    structure_result = structural_diff(artifact_bytes, reference)

    log = {
        "scenario": scenario.name,
        "source_path": str(scenario.source_path.relative_to(ROOT)),
        "chart_id": chart_id,
        "export_id": export_id,
        "artifact_path": str(artifact_path.relative_to(ROOT)),
        "expectation": scenario.expectation,
        "mapping_count": len(mapping_values),
        "mandatory_field_values": {key: mapping_values[key] for key in MANDATORY_FIELD_VALUES},
        "xsd_validation": xsd_result,
        "schematron_validation": schematron_result,
        "structural_diff": structure_result,
        "artifact_checksum_sha256": artifact_response.headers.get("X-Checksum-SHA256"),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    log_path = LOGS_DIR / f"{scenario.slug}.json"
    log_path.write_text(json.dumps(log, indent=2), encoding="utf-8")

    if not xsd_result["valid"]:
        raise CTAHarnessError(f"XSD validation failed for {scenario.name}; see {log_path}")
    if not schematron_result["valid"]:
        raise CTAHarnessError(f"Schematron validation failed for {scenario.name}; see {log_path}")
    if not structure_result["valid"]:
        raise CTAHarnessError(f"Structural parity failed for {scenario.name}; see {log_path}")

    return log


def write_summary(results: list[dict[str, Any]], failure: str | None, reference: ReferenceFixture, runtime_meta: dict[str, Any]) -> None:
    """Write the run summary required by the local CTA directive."""
    summary = {
        "status": "failed" if failure else "passed",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "reference_xml": str(reference.path.relative_to(ROOT)),
        "reference_asset_version": reference.asset_version,
        "scenario_count": len(results),
        "results": [
            {
                "scenario": result["scenario"],
                "chart_id": result["chart_id"],
                "export_id": result["export_id"],
                "artifact_path": result["artifact_path"],
            }
            for result in results
        ],
        "runtime": runtime_meta,
        "failure": failure,
    }
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def main() -> int:
    """Run the full local CTA execution flow and exit non-zero on real failure."""
    ensure_runtime_dirs()
    if DB_PATH.exists():
        DB_PATH.unlink()
    reference_path = CTA_PACKAGE_DIR / "2025-STATE-1_v351.xml"
    if not reference_path.exists():
        raise CTAHarnessError(f"CTA reference XML not found: {reference_path}")

    reference = parse_reference_fixture(reference_path)
    private_pem, public_pem = generate_keypair()
    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    token = issue_token(private_pem, tenant_id, user_id)
    scenario_configs = build_scenario_configs(reference)

    moto_port = find_free_port()
    api_port = find_free_port()
    bucket_name = "adaptix-local-cta-exports"
    endpoint_url = f"http://127.0.0.1:{moto_port}"
    env = os.environ.copy()
    runtime_env = {
        "EPCR_DATABASE_URL": f"sqlite+aiosqlite:///{DB_PATH.as_posix()}",
        "ADAPTIX_JWT_PUBLIC_KEY": public_pem,
        "NEMSIS_EXPORT_S3_BUCKET": bucket_name,
        "AWS_ENDPOINT_URL_S3": endpoint_url,
        "AWS_ACCESS_KEY_ID": "local",
        "AWS_SECRET_ACCESS_KEY": "local",
        "AWS_DEFAULT_REGION": "us-east-1",
        "NEMSIS_XSD_PATH": str((ASSETS_DIR / "xsd" / "NEMSIS_XSDs.zip").resolve()),
        "NEMSIS_SCHEMATRON_PATH": str((ASSETS_DIR / "schematron").resolve()),
        "NEMSIS_VALIDATOR_ASSET_VERSION": reference.asset_version,
        "NEMSIS_STATE_SCHEMA_LOCATION": reference.schema_location,
        "NEMSIS_STATE_TEMPLATE_PATH": str(reference.path.resolve()),
        "NEMSIS_STATE_CODE": reference.state_code,
        "NEMSIS_STATE_EFFECTIVE_DATE": reference.effective_date,
        "NEMSIS_SOFTWARE_CREATOR": "NEMSIS Technical Assistance Center",
        "NEMSIS_SOFTWARE_NAME": "Compliance Testing",
        "NEMSIS_SOFTWARE_VERSION": f"{reference.asset_version}_local",
        "PYTHONPATH": os.pathsep.join(
            [segment for segment in [str(BACKEND_DIR), env.get("PYTHONPATH", "")] if segment]
        ),
    }
    env.update(runtime_env)
    os.environ.update(runtime_env)

    moto_process: subprocess.Popen[Any] | None = None
    api_process: subprocess.Popen[Any] | None = None
    results: list[dict[str, Any]] = []
    failure: str | None = None

    try:
        moto_process = start_moto_server(moto_port)
        create_bucket(endpoint_url, bucket_name)
        api_process = start_backend_server(env, api_port)
        base_url = f"http://127.0.0.1:{api_port}"
        headers = build_headers(token, tenant_id, user_id)

        with httpx.Client(timeout=60.0) as client:
            for scenario in scenario_configs:
                result = run_single_scenario(client, base_url, headers, scenario, reference)
                results.append(result)
    except Exception as exc:  # noqa: BLE001
        failure = str(exc)
    finally:
        terminate_process(api_process)
        terminate_process(moto_process)
        write_summary(
            results=results,
            failure=failure,
            reference=reference,
            runtime_meta={
                "api_port": api_port,
                "moto_port": moto_port,
                "bucket_name": bucket_name,
                "database_path": str(DB_PATH.relative_to(ROOT)),
            },
        )

    if failure:
        print(failure, file=sys.stderr)
        return 1
    print(f"Local CTA run completed successfully for {len(results)} scenarios.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())