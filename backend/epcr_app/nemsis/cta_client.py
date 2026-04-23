from __future__ import annotations

"""Submit validated NEMSIS EMSDataSet XML to CTA with explicit integration gating."""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import os
import re
import xml.etree.ElementTree as ET

import httpx


CTA_NAMESPACE = {"soap": "http://schemas.xmlsoap.org/soap/envelope/"}
DEFAULT_DATA_SCHEMA = "61"
DEFAULT_ENDPOINT = "https://cta.nemsis.org:443/ComplianceTestingWs/endpoints/"
DEFAULT_SCHEMA_VERSION = "3.5.1"


def _iter_env_sources() -> list[dict[str, str]]:
    """Load environment values from process env and local `.env` files.

    Args:
        None.

    Returns:
        Ordered list of environment mappings, highest precedence first.
    """

    backend_root = Path(__file__).resolve().parents[3]
    repo_root = backend_root.parent
    env_sources: list[dict[str, str]] = [dict(os.environ)]
    for candidate in (backend_root / ".env", repo_root / ".env"):
        if not candidate.exists():
            continue
        parsed: dict[str, str] = {}
        for raw_line in candidate.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            parsed[key.strip()] = value.strip().strip('"').strip("'")
        env_sources.append(parsed)
    return env_sources


def _resolve_env_value(*names: str) -> str | None:
    """Resolve the first non-placeholder value across process env and local env files.

    Args:
        *names: Environment variable names in precedence order.

    Returns:
        The first usable value found, otherwise `None`.
    """

    placeholder_markers = (
        "placeholder",
        "example.invalid",
        "your-",
        "replace-with-",
    )
    for source in _iter_env_sources():
        for name in names:
            value = (source.get(name) or "").strip()
            if not value:
                continue
            if any(marker in value.lower() for marker in placeholder_markers):
                continue
            return value
    return None


@dataclass(frozen=True)
class CtaSubmissionResult:
    """Structured CTA submission response and evidence payload."""

    integration_enabled: bool
    submitted: bool
    request_timestamp_utc: str
    endpoint: str
    http_status: int | None
    response_status: str
    status_code: str | None
    request_handle: str | None
    message: str | None
    request_body: str | None
    response_body: str | None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the CTA submission result to a JSON-friendly mapping.

        Args:
            None.

        Returns:
            JSON-safe dictionary representation.
        """

        return asdict(self)


class CtaSubmissionClient:
    """Execute SOAP CTA submissions only when the explicit integration gate is enabled."""

    def __init__(
        self,
        endpoint: str | None = None,
        username: str | None = None,
        password: str | None = None,
        client_factory: Any | None = None,
    ) -> None:
        """Initialize CTA client configuration.

        Args:
            endpoint: Optional CTA SOAP endpoint.
            username: Optional CTA username.
            password: Optional CTA password.
            client_factory: Optional callable returning an `httpx.AsyncClient`.

        Returns:
            None.
        """

        self._endpoint = endpoint or _resolve_env_value(
            "NEMSIS_CTA_ENDPOINT",
            "NEMSIS_TAC_ENDPOINT",
            "NEMSIS_TAC_ENDPOINT_URL",
            "NEMSIS_STATE_ENDPOINT_URL",
        ) or DEFAULT_ENDPOINT
        self._username = username or _resolve_env_value(
            "NEMSIS_CTA_USERNAME",
            "NEMSIS_TAC_USERNAME",
            "NEMSIS_SOAP_USERNAME",
        )
        self._password = password or _resolve_env_value(
            "NEMSIS_CTA_PASSWORD",
            "NEMSIS_TAC_PASSWORD",
            "NEMSIS_SOAP_PASSWORD",
        )
        self._organization = _resolve_env_value(
            "NEMSIS_CTA_ORGANIZATION",
            "NEMSIS_TAC_ORGANIZATION",
        )
        self._schema_version = _resolve_env_value("NEMSIS_SCHEMA_VERSION") or DEFAULT_SCHEMA_VERSION
        self._client_factory = client_factory or httpx.AsyncClient

    async def submit(
        self,
        xml_bytes: bytes,
        *,
        integration_enabled: bool,
        data_schema: str = DEFAULT_DATA_SCHEMA,
        submission_label: str | None = None,
    ) -> CtaSubmissionResult:
        """Submit a validated EMS XML document to CTA when explicitly enabled.

        Args:
            xml_bytes: Serialized EMSDataSet XML bytes.
            integration_enabled: Explicit gate that allows real network submission.
            data_schema: CTA request data schema code.
            submission_label: Optional submission label for CTA additionalInfo.

        Returns:
            Structured submission result, including a skipped result when disabled.

        Raises:
            RuntimeError: If live submission is enabled but credentials are missing.
            httpx.HTTPError: If the live HTTP request fails.
        """

        timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        if not integration_enabled:
            return CtaSubmissionResult(
                integration_enabled=False,
                submitted=False,
                request_timestamp_utc=timestamp,
                endpoint=self._endpoint,
                http_status=None,
                response_status="skipped",
                status_code=None,
                request_handle=None,
                message="CTA submission not requested.",
                request_body=None,
                response_body=None,
            )

        if not self._endpoint or not self._username or not self._password:
            return CtaSubmissionResult(
                integration_enabled=True,
                submitted=False,
                request_timestamp_utc=timestamp,
                endpoint=self._endpoint,
                http_status=None,
                response_status="blocked",
                status_code=None,
                request_handle=None,
                message="CTA NETWORK SUBMISSION BLOCKED — MISSING CREDENTIALS",
                request_body=None,
                response_body=None,
            )

        if not self._organization:
            return CtaSubmissionResult(
                integration_enabled=True,
                submitted=False,
                request_timestamp_utc=timestamp,
                endpoint=self._endpoint,
                http_status=None,
                response_status="blocked",
                status_code=None,
                request_handle=None,
                message="CTA NETWORK SUBMISSION BLOCKED — MISSING ORGANIZATION",
                request_body=None,
                response_body=None,
            )

        payload = self._build_submit_envelope(
            username=self._username,
            password=self._password,
            organization=self._organization,
            data_schema=data_schema,
            schema_version=self._schema_version,
            submission_label=submission_label or f"ALLERGY-{timestamp}",
            xml_payload=xml_bytes.decode("utf-8"),
        )
        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": "http://ws.nemsis.org/SubmitData",
        }
        async with self._client_factory(timeout=60.0) as client:
            response = await client.post(self._endpoint, content=payload.encode("utf-8"), headers=headers)
        if response.status_code != 200:
            return CtaSubmissionResult(
                integration_enabled=True,
                submitted=False,
                request_timestamp_utc=timestamp,
                endpoint=self._endpoint,
                http_status=response.status_code,
                response_status="http_error",
                status_code=str(response.status_code),
                request_handle=None,
                message=f"CTA endpoint returned HTTP {response.status_code}",
                request_body=payload,
                response_body=response.text,
            )

        request_handle = self._extract_text(response.text, "requestHandle")
        status_code = self._extract_text(response.text, "statusCode")
        server_error = self._extract_text(response.text, "serverErrorMessage")
        response_status = self._extract_text(response.text, "status") or ("accepted" if status_code == "1" else "unknown")
        if status_code == "1":
            message = self._extract_text(response.text, "message") or self._extract_text(response.text, "statusMessage")
            return CtaSubmissionResult(
                integration_enabled=True,
                submitted=True,
                request_timestamp_utc=timestamp,
                endpoint=self._endpoint,
                http_status=response.status_code,
                response_status=response_status,
                status_code=status_code,
                request_handle=request_handle,
                message=message,
                request_body=payload,
                response_body=response.text,
            )

        return CtaSubmissionResult(
            integration_enabled=True,
            submitted=False,
            request_timestamp_utc=timestamp,
            endpoint=self._endpoint,
            http_status=response.status_code,
            response_status=response_status,
            status_code=status_code,
            request_handle=request_handle,
            message=server_error or self._extract_text(response.text, "message") or self._extract_text(response.text, "statusMessage"),
            request_body=payload,
            response_body=response.text,
        )

    @staticmethod
    def _build_submit_envelope(
        *,
        username: str,
        password: str,
        organization: str,
        data_schema: str,
        schema_version: str,
        submission_label: str,
        xml_payload: str,
    ) -> str:
        """Build the SOAP envelope expected by the CTA EMS submit endpoint.

        Args:
            username: CTA account username.
            password: CTA account password.
            organization: CTA vendor organization.
            data_schema: CTA request data schema code.
            schema_version: NEMSIS schema version.
            submission_label: Human label for CTA additionalInfo.
            xml_payload: XML payload string.

        Returns:
            SOAP envelope XML string.
        """
        payload_xml = re.sub(r'<\?xml[^?]*\?>\s*', "", xml_payload, count=1)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"'
            ' xmlns:ws="http://ws.nemsis.org/">'
            '<soapenv:Header/>'
            '<soapenv:Body>'
            '<ws:SubmitDataRequest>'
            f'<ws:username>{username}</ws:username>'
            f'<ws:password>{password}</ws:password>'
            f'<ws:organization>{organization}</ws:organization>'
            '<ws:requestType>SubmitData</ws:requestType>'
            '<ws:submitPayload>'
            '<ws:payloadOfXmlElement>'
            + payload_xml
            + '</ws:payloadOfXmlElement>'
            '</ws:submitPayload>'
            f'<ws:requestDataSchema>{data_schema}</ws:requestDataSchema>'
            f'<ws:schemaVersion>{schema_version}</ws:schemaVersion>'
            f'<ws:additionalInfo>{submission_label}</ws:additionalInfo>'
            '</ws:SubmitDataRequest>'
            '</soapenv:Body>'
            '</soapenv:Envelope>'
        )

    @staticmethod
    def _extract_text(xml_text: str, tag_name: str) -> str | None:
        """Extract a tag value from the SOAP response body.

        Args:
            xml_text: SOAP response XML text.
            tag_name: Local tag name to extract.

        Returns:
            The stripped text value if present, otherwise `None`.
        """

        try:
            root = ET.fromstring(xml_text)
            for element in root.iter():
                if element.tag.endswith(tag_name):
                    text = (element.text or "").strip()
                    return text or None
        except ET.ParseError:
            match = re.search(fr"<{tag_name}>(.*?)</{tag_name}>", xml_text, re.IGNORECASE | re.DOTALL)
            if match:
                return match.group(1).strip()
        return None
