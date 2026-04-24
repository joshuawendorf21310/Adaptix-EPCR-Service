"""Services for the local CTA testing portal.

Owns encrypted local CTA credential storage, scenario orchestration, run
artifact persistence, and artifact retrieval for the browser-based CTA lab.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import mimetypes
import os
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from cryptography.fernet import Fernet

from epcr_app.api_nemsis_scenarios import _find_scenario, _generate_pretesting_xml_or_500
from epcr_app.local_auth import PortalAuthClaims
from epcr_app.nemsis.cta_client import CtaSubmissionClient
from epcr_app.nemsis_xsd_validator import NemsisXSDValidator


_PORTAL_SCENARIO_CODES = (
    "2025_DEM_1",
    "2025_EMS_1",
    "2025_EMS_2",
    "2025_EMS_3",
    "2025_EMS_4",
    "2025_EMS_5",
)

_SUMMARY_FILE = "summary.json"
_XML_FILE = "generated.xml"
_VALIDATION_FILE = "validation.json"
_SOAP_REQUEST_FILE = "soap-request.xml"
_SOAP_RESPONSE_FILE = "soap-response.xml"
_PARSED_RESULT_FILE = "parsed-result.json"


@dataclass(frozen=True)
class StoredCtaCredentials:
    """Encrypted CTA credentials used by the local portal runner."""

    username: str
    password: str
    organization: str
    endpoint: str
    updated_at: str


def _repo_root() -> Path:
    """Return the repository root path."""

    return Path(__file__).resolve().parents[2]


def _backend_root() -> Path:
    """Return the backend root path."""

    return Path(__file__).resolve().parents[1]


def _runtime_root() -> Path:
    """Return the runtime root for CTA portal data."""

    configured = os.environ.get("CTA_TESTING_PORTAL_RUNTIME_ROOT", "").strip()
    if configured:
        return Path(configured)
    return _repo_root() / "artifact" / "cta" / "testing-portal"


def _secret_root() -> Path:
    """Return the secret root for encrypted credential material."""

    configured = os.environ.get("CTA_TESTING_PORTAL_SECRET_ROOT", "").strip()
    if configured:
        return Path(configured)
    return _backend_root() / ".local" / "cta_portal"


def _credential_key_path() -> Path:
    """Return the credential encryption key file path."""

    return _secret_root() / "credentials.key"


def _credential_store_path() -> Path:
    """Return the encrypted credential store file path."""

    return _secret_root() / "credentials.enc"


def _runs_root() -> Path:
    """Return the persisted CTA run root directory."""

    return _runtime_root() / "runs"


def _utc_now_iso() -> str:
    """Return the current UTC timestamp as ISO-8601 text."""

    return datetime.now(UTC).isoformat()


def _mask_username(username: str) -> str:
    """Mask a username for browser display without leaking the raw value."""

    if len(username) <= 4:
        return "*" * len(username)
    return f"{username[:2]}{'*' * max(2, len(username) - 4)}{username[-2:]}"


def _sanitize_soap_request(request_body: str | None) -> str | None:
    """Redact password values from SOAP request payloads before persistence."""

    if request_body is None:
        return None
    return re.sub(r"(<ws:password>)(.*?)(</ws:password>)", r"\1[REDACTED]\3", request_body, flags=re.DOTALL)


def _ensure_parents(path: Path) -> None:
    """Ensure a file path's parent directory exists."""

    path.parent.mkdir(parents=True, exist_ok=True)


def _guess_mime_type(path: Path) -> str:
    """Guess a MIME type for an artifact file."""

    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "text/plain"


class CtaPortalCredentialStore:
    """Encrypted local credential store for the CTA testing portal."""

    def _get_fernet(self) -> Fernet:
        """Return the Fernet instance used for credential encryption."""

        key_path = _credential_key_path()
        _ensure_parents(key_path)
        if key_path.exists():
            key = key_path.read_bytes()
        else:
            key = Fernet.generate_key()
            key_path.write_bytes(key)
        return Fernet(key)

    def save(self, *, username: str, password: str, organization: str, endpoint: str) -> dict[str, Any]:
        """Encrypt and persist CTA credentials locally.

        Args:
            username: CTA username.
            password: CTA password.
            organization: CTA organization/vendor string.
            endpoint: CTA SOAP endpoint URL.

        Returns:
            dict[str, Any]: Status summary safe for browser display.
        """

        payload = StoredCtaCredentials(
            username=username.strip(),
            password=password,
            organization=organization.strip(),
            endpoint=endpoint.strip(),
            updated_at=_utc_now_iso(),
        )
        encrypted = self._get_fernet().encrypt(json.dumps(payload.__dict__).encode("utf-8"))
        store_path = _credential_store_path()
        _ensure_parents(store_path)
        store_path.write_bytes(encrypted)
        return self.status()

    def load(self) -> StoredCtaCredentials | None:
        """Load and decrypt saved CTA credentials.

        Returns:
            StoredCtaCredentials | None: Saved credentials when present.
        """

        store_path = _credential_store_path()
        if not store_path.exists():
            return None
        decrypted = self._get_fernet().decrypt(store_path.read_bytes())
        return StoredCtaCredentials(**json.loads(decrypted.decode("utf-8")))

    def delete(self) -> None:
        """Delete the saved credential file if it exists."""

        store_path = _credential_store_path()
        if store_path.exists():
            store_path.unlink()

    def status(self) -> dict[str, Any]:
        """Return non-secret saved-credential status for the UI."""

        saved = self.load()
        if saved is None:
            return {
                "saved": False,
                "username_masked": None,
                "organization": None,
                "endpoint": None,
                "updated_at": None,
            }
        return {
            "saved": True,
            "username_masked": _mask_username(saved.username),
            "organization": saved.organization,
            "endpoint": saved.endpoint,
            "updated_at": saved.updated_at,
        }


class CtaTestingPortalService:
    """Execute CTA test runs and persist browser-viewable artifacts."""

    def __init__(self) -> None:
        """Initialize local services used by the CTA testing portal."""

        self._credential_store = CtaPortalCredentialStore()

    def list_scenarios(self) -> list[dict[str, Any]]:
        """List supported CTA portal scenarios.

        Returns:
            list[dict[str, Any]]: Supported CTA testing scenarios.
        """

        scenarios: list[dict[str, Any]] = []
        for code in _PORTAL_SCENARIO_CODES:
            scenario = _find_scenario(code)
            if scenario is None:
                continue
            scenarios.append(
                {
                    "scenario_code": scenario["scenario_code"],
                    "title": scenario["title"],
                    "description": scenario["description"],
                    "year": scenario["year"],
                    "category": scenario["category"],
                    "data_schema": "62" if scenario["category"] == "DEM" else "61",
                }
            )
        return scenarios

    def credential_status(self) -> dict[str, Any]:
        """Return local CTA credential store status."""

        return self._credential_store.status()

    def save_credentials(self, *, username: str, password: str, organization: str, endpoint: str) -> dict[str, Any]:
        """Persist encrypted CTA credentials after input validation."""

        if not username.strip():
            raise ValueError("CTA username is required.")
        if not password:
            raise ValueError("CTA password is required.")
        if not organization.strip():
            raise ValueError("CTA organization is required.")
        normalized_endpoint = endpoint.strip()
        if not normalized_endpoint.startswith("http://") and not normalized_endpoint.startswith("https://"):
            raise ValueError("CTA endpoint must be an absolute HTTP or HTTPS URL.")
        return self._credential_store.save(
            username=username,
            password=password,
            organization=organization,
            endpoint=normalized_endpoint,
        )

    def delete_credentials(self) -> None:
        """Remove saved CTA credentials from local encrypted storage."""

        self._credential_store.delete()

    def list_runs(self) -> list[dict[str, Any]]:
        """Return CTA runs sorted by most recent first."""

        runs: list[dict[str, Any]] = []
        runs_root = _runs_root()
        if not runs_root.exists():
            return runs

        for summary_path in runs_root.glob(f"*/{_SUMMARY_FILE}"):
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            runs.append(summary)

        return sorted(runs, key=lambda item: item.get("started_at", ""), reverse=True)

    def get_run(self, run_id: str) -> dict[str, Any]:
        """Load a single run summary.

        Args:
            run_id: Run identifier.

        Returns:
            dict[str, Any]: Run summary document.

        Raises:
            FileNotFoundError: If the run does not exist.
        """

        summary_path = _runs_root() / run_id / _SUMMARY_FILE
        if not summary_path.exists():
            raise FileNotFoundError(run_id)
        return json.loads(summary_path.read_text(encoding="utf-8"))

    def get_artifact(self, run_id: str, artifact_name: str) -> dict[str, Any]:
        """Return a persisted artifact for browser viewing.

        Args:
            run_id: Run identifier.
            artifact_name: Artifact file name.

        Returns:
            dict[str, Any]: Artifact payload.

        Raises:
            FileNotFoundError: If the artifact does not exist.
        """

        artifact_path = _runs_root() / run_id / artifact_name
        if not artifact_path.exists() or not artifact_path.is_file():
            raise FileNotFoundError(artifact_name)
        return {
            "artifact_name": artifact_name,
            "mime_type": _guess_mime_type(artifact_path),
            "content": artifact_path.read_text(encoding="utf-8"),
        }

    async def execute_run(self, *, scenario_code: str, actor: PortalAuthClaims) -> dict[str, Any]:
        """Execute a full generate → validate → submit CTA run.

        Args:
            scenario_code: Supported CTA scenario code.
            actor: Authenticated local portal actor.

        Returns:
            dict[str, Any]: Persisted run summary.

        Raises:
            ValueError: If the scenario is unsupported or credentials are missing.
        """

        if scenario_code not in _PORTAL_SCENARIO_CODES:
            raise ValueError(f"Unsupported CTA scenario '{scenario_code}'.")

        saved_credentials = self._credential_store.load()
        if saved_credentials is None:
            raise ValueError("Save CTA credentials before running a CTA test.")

        scenario = _find_scenario(scenario_code)
        if scenario is None:
            raise ValueError(f"CTA scenario '{scenario_code}' could not be resolved.")

        run_id = str(uuid4())
        started_at = _utc_now_iso()
        run_dir = _runs_root() / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        xml_bytes = _generate_pretesting_xml_or_500(scenario_code, scenario)
        (run_dir / _XML_FILE).write_bytes(xml_bytes)

        validator = NemsisXSDValidator()
        validation_result = validator.validate_xml(xml_bytes)
        (run_dir / _VALIDATION_FILE).write_text(json.dumps(validation_result, indent=2), encoding="utf-8")

        submission_result: dict[str, Any] | None = None
        status = "validation_failed"
        success = False

        if validation_result.get("validation_skipped", False):
            status = "validation_skipped"
        elif validation_result.get("valid", False):
            client = CtaSubmissionClient(
                endpoint=saved_credentials.endpoint,
                username=saved_credentials.username,
                password=saved_credentials.password,
                organization=saved_credentials.organization,
            )
            client_result = await client.submit(
                xml_bytes,
                integration_enabled=True,
                data_schema="62" if scenario["category"] == "DEM" else "61",
                submission_label=f"PORTAL-{scenario_code}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
            )
            submission_result = client_result.to_dict()
            sanitized_request = _sanitize_soap_request(submission_result.get("request_body"))
            (run_dir / _SOAP_REQUEST_FILE).write_text(sanitized_request or "", encoding="utf-8")
            (run_dir / _SOAP_RESPONSE_FILE).write_text(submission_result.get("response_body") or "", encoding="utf-8")
            (run_dir / _PARSED_RESULT_FILE).write_text(json.dumps(submission_result, indent=2), encoding="utf-8")
            success = bool(submission_result.get("submitted"))
            status = "cta_passed" if success else "cta_failed"

        summary = {
            "run_id": run_id,
            "scenario_code": scenario["scenario_code"],
            "title": scenario["title"],
            "description": scenario["description"],
            "category": scenario["category"],
            "status": status,
            "success": success,
            "started_at": started_at,
            "completed_at": _utc_now_iso(),
            "actor": {
                "user_id": actor.user_id,
                "tenant_id": actor.tenant_id,
                "email": actor.email,
            },
            "credentials": {
                "username_masked": _mask_username(saved_credentials.username),
                "organization": saved_credentials.organization,
                "endpoint": saved_credentials.endpoint,
                "updated_at": saved_credentials.updated_at,
            },
            "validation": validation_result,
            "submission": submission_result,
            "artifacts": [
                {"name": _XML_FILE, "label": "Generated XML", "mime_type": "application/xml"},
                {"name": _VALIDATION_FILE, "label": "Validation Result", "mime_type": "application/json"},
                *(
                    [
                        {"name": _SOAP_REQUEST_FILE, "label": "SOAP Request", "mime_type": "application/xml"},
                        {"name": _SOAP_RESPONSE_FILE, "label": "SOAP Response", "mime_type": "application/xml"},
                        {"name": _PARSED_RESULT_FILE, "label": "Parsed CTA Result", "mime_type": "application/json"},
                    ]
                    if submission_result is not None
                    else []
                ),
            ],
        }
        (run_dir / _SUMMARY_FILE).write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary