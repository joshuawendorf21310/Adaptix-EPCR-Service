"""NEMSIS state submission lifecycle API routes.

Provides routes for creating, retrying, acknowledging, accepting, and rejecting
NEMSIS state submissions. All state transitions are logged in
nemsis_submission_status_history. XML payloads are uploaded to S3 when
configured. SOAP submission to state endpoint is performed via WSDL when
NEMSIS_STATE_ENDPOINT_URL is configured and credentials are present.

Routes:
- POST  /api/v1/epcr/nemsis/submissions                                  — create submission
- GET   /api/v1/epcr/nemsis/submissions                                  — list submissions
- GET   /api/v1/epcr/nemsis/submissions/{submission_id}                  — get submission
- POST  /api/v1/epcr/nemsis/submissions/{submission_id}/retry            — retry submission
- POST  /api/v1/epcr/nemsis/submissions/{submission_id}/acknowledge      — acknowledge
- POST  /api/v1/epcr/nemsis/submissions/{submission_id}/accept           — accept
- POST  /api/v1/epcr/nemsis/submissions/{submission_id}/reject           — reject
- GET   /api/v1/epcr/nemsis/submissions/{submission_id}/history          — status history
"""
from __future__ import annotations

import hashlib
import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.models_nemsis_core import NemsisSubmissionResult, NemsisSubmissionStatusHistory
from epcr_app.nemsis_exporter import NEMSISExporter

logger = logging.getLogger(__name__)

_STATE_ENDPOINT_URL = os.environ.get("NEMSIS_STATE_ENDPOINT_URL", "")
_SOAP_USERNAME = os.environ.get("NEMSIS_SOAP_USERNAME", "")
_SOAP_PASSWORD = os.environ.get("NEMSIS_SOAP_PASSWORD", "")
_S3_BUCKET = os.environ.get("NEMSIS_SUBMISSION_S3_BUCKET") or os.environ.get(
    "FILES_S3_BUCKET", ""
)
_S3_PREFIX = os.environ.get("NEMSIS_SUBMISSION_S3_PREFIX", "nemsis/submissions")

router = APIRouter(prefix="/api/v1/epcr/nemsis/submissions", tags=["nemsis-submissions"])


class CreateSubmissionRequest(BaseModel):
    """Request body for initiating a NEMSIS state submission."""

    chart_id: str
    export_id: str | None = None
    state_endpoint_url: str | None = None


class RejectSubmissionRequest(BaseModel):
    """Request body for rejecting a NEMSIS state submission."""

    rejection_reason: str


class AcknowledgeSubmissionRequest(BaseModel):
    """Request body for acknowledging a NEMSIS state submission."""

    note: str | None = None


class AcceptSubmissionRequest(BaseModel):
    """Request body for accepting a NEMSIS state submission."""

    note: str | None = None


def _require_header(value: str | None, name: str) -> str:
    """Validate that a required HTTP header is present and non-empty.

    Args:
        value: Raw header value from the request.
        name: Header name used in the error message.

    Returns:
        Stripped header value.

    Raises:
        HTTPException: 400 if the header is absent or blank.
    """
    if not value or not value.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{name} header required",
        )
    return value.strip()


def _require_user_id(value: str | None, name: str) -> str:
    """Validate that a required user identifier header is present and non-empty.

    Args:
        value: Raw header value from the request.
        name: Header name used in the error message.

    Returns:
        Stripped header value.

    Raises:
        HTTPException: 400 if the header is absent or blank.
    """
    if not value or not value.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{name} header required",
        )
    return value.strip()


async def _write_history(
    session: AsyncSession,
    submission_id: str,
    tenant_id: str,
    from_status: str | None,
    to_status: str,
    actor_user_id: str | None,
    note: str | None = None,
) -> None:
    """Append a status transition row to nemsis_submission_status_history.

    Args:
        session: Async SQLAlchemy session.
        submission_id: Owning submission identifier.
        tenant_id: Tenant identifier.
        from_status: Status before the transition, or None for the initial row.
        to_status: Status after the transition.
        actor_user_id: User who caused the transition, or None for system events.
        note: Optional operator note to record with the transition.
    """
    row = NemsisSubmissionStatusHistory(
        id=str(uuid.uuid4()),
        submission_id=submission_id,
        tenant_id=tenant_id,
        from_status=from_status,
        to_status=to_status,
        actor_user_id=actor_user_id,
        note=note,
        transitioned_at=datetime.now(UTC).replace(tzinfo=None),
    )
    session.add(row)


def _upload_xml_to_s3(xml_bytes: bytes, s3_key: str) -> bool:
    """Upload XML bytes to S3. Returns True on success, False on failure.

    If NEMSIS_SUBMISSION_S3_BUCKET or FILES_S3_BUCKET is not configured,
    the upload is skipped and False is returned without raising an error.

    Args:
        xml_bytes: Raw XML content to store.
        s3_key: Full S3 object key for the uploaded file.

    Returns:
        True if the upload succeeded, False otherwise.
    """
    if not _S3_BUCKET:
        return False
    try:
        import boto3

        boto3.client("s3").put_object(Bucket=_S3_BUCKET, Key=s3_key, Body=xml_bytes)
        return True
    except Exception as exc:
        logger.error("S3 upload failed key=%s: %s", s3_key, exc)
        return False


def _submit_via_soap(
    xml_content: str,
    endpoint_url: str,
    username: str,
    password: str,
    submission_number: str,
) -> dict[str, Any]:
    """Attempt SOAP submission to a NEMSIS state endpoint.

    Returns a dict with keys: submitted (bool), message_id (str|None),
    response_code (str|None), error (str|None).

    If credentials or endpoint URL are absent, the function returns
    submitted=False with an explicit error message. It never fakes success.

    Args:
        xml_content: UTF-8 XML string to submit.
        endpoint_url: WSDL URL of the state NEMSIS endpoint.
        username: SOAP WS-Security username.
        password: SOAP WS-Security password.
        submission_number: Unique submission tracking number sent with the payload.

    Returns:
        Dict with submitted, message_id, response_code, and error keys.
    """
    if not endpoint_url or not username or not password:
        return {
            "submitted": False,
            "message_id": None,
            "response_code": None,
            "error": (
                "SOAP submission skipped: NEMSIS_STATE_ENDPOINT_URL, "
                "NEMSIS_SOAP_USERNAME, or NEMSIS_SOAP_PASSWORD not configured"
            ),
        }
    try:
        from zeep import Client
        from zeep.wsse.username import UsernameToken

        client = Client(
            wsdl=endpoint_url,
            wsse=UsernameToken(username, password),
        )
        response = client.service.SubmitData(
            submissionNumber=submission_number,
            xmlData=xml_content,
        )
        logger.info("SOAP SubmitData response: %s", response)
        return {
            "submitted": True,
            "message_id": getattr(response, "messageId", None),
            "response_code": getattr(response, "responseCode", None),
            "error": None,
        }
    except ImportError:
        return {
            "submitted": False,
            "message_id": None,
            "response_code": None,
            "error": "SOAP submission skipped: zeep library not installed",
        }
    except Exception as exc:
        logger.error("SOAP SubmitData failed: %s", exc, exc_info=True)
        return {
            "submitted": False,
            "message_id": None,
            "response_code": None,
            "error": f"SOAP submission failed: {exc}",
        }


def _serialize_submission(s: NemsisSubmissionResult) -> dict[str, Any]:
    """Serialize a NemsisSubmissionResult ORM object to a plain dict.

    Args:
        s: NemsisSubmissionResult ORM instance.

    Returns:
        Dict representation of the submission record.
    """
    return {
        "id": s.id,
        "tenant_id": s.tenant_id,
        "chart_id": s.chart_id,
        "export_id": s.export_id,
        "submission_number": s.submission_number,
        "state_endpoint_url": s.state_endpoint_url,
        "submission_status": s.submission_status,
        "xml_s3_bucket": s.xml_s3_bucket,
        "xml_s3_key": s.xml_s3_key,
        "ack_s3_bucket": s.ack_s3_bucket,
        "ack_s3_key": s.ack_s3_key,
        "response_s3_bucket": s.response_s3_bucket,
        "response_s3_key": s.response_s3_key,
        "payload_sha256": s.payload_sha256,
        "soap_message_id": s.soap_message_id,
        "soap_response_code": s.soap_response_code,
        "rejection_reason": s.rejection_reason,
        "comparison_report_ref": s.comparison_report_ref,
        "submitted_at": s.submitted_at.isoformat() if s.submitted_at else None,
        "acknowledged_at": s.acknowledged_at.isoformat() if s.acknowledged_at else None,
        "resolved_at": s.resolved_at.isoformat() if s.resolved_at else None,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "created_by_user_id": s.created_by_user_id,
    }


def _serialize_history(h: NemsisSubmissionStatusHistory) -> dict[str, Any]:
    """Serialize a NemsisSubmissionStatusHistory ORM object to a plain dict.

    Args:
        h: NemsisSubmissionStatusHistory ORM instance.

    Returns:
        Dict representation of the history row.
    """
    return {
        "id": h.id,
        "submission_id": h.submission_id,
        "tenant_id": h.tenant_id,
        "from_status": h.from_status,
        "to_status": h.to_status,
        "actor_user_id": h.actor_user_id,
        "note": h.note,
        "payload_snapshot_json": h.payload_snapshot_json,
        "transitioned_at": h.transitioned_at.isoformat() if h.transitioned_at else None,
    }


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_submission(
    body: CreateSubmissionRequest,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Create a NEMSIS state submission for a chart.

    Generates chart XML via NEMSISExporter, computes a SHA-256 payload
    digest, uploads the XML to S3 when configured, attempts SOAP submission
    to the state endpoint when credentials are configured, persists the
    NemsisSubmissionResult, and writes the initial status history row.

    Note: Full chart materialization from the database is not yet wired into
    this route. The chart_id is passed to NEMSISExporter as a minimal dict.
    The resulting XML is structurally valid NEMSIS 3.5.1 but contains
    NV_NOT_RECORDED sentinels for fields that require a fully-loaded chart.
    This is logged as a warning; the response truthfully reflects this state.

    Args:
        body: Submission creation parameters.
        x_tenant_id: Tenant identifier from X-Tenant-ID header.
        x_user_id: Acting user identifier from X-User-ID header.
        session: Injected async database session.

    Returns:
        Serialized submission dict including soap_result detail, HTTP 201.

    Raises:
        HTTPException: 400 if headers missing; 500 on unexpected failure.
    """
    tenant_id = _require_header(x_tenant_id, "X-Tenant-ID")
    user_id = _require_user_id(x_user_id, "X-User-ID")

    try:
        submission_number = (
            f"SUB-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
        )
        endpoint_url = body.state_endpoint_url or _STATE_ENDPOINT_URL

        logger.warning(
            "create_submission: full chart materialization not yet wired; "
            "chart_id=%s will export with NV_NOT_RECORDED sentinels for "
            "unresolved fields",
            body.chart_id,
        )
        xml_bytes = NEMSISExporter().export_chart({"id": body.chart_id}, {})
        xml_content = xml_bytes.decode("utf-8", errors="replace")
        payload_sha256 = hashlib.sha256(xml_bytes).hexdigest()

        s3_key = f"{_S3_PREFIX}/{tenant_id}/{submission_number}.xml"
        s3_uploaded = _upload_xml_to_s3(xml_bytes, s3_key)
        if not s3_uploaded:
            logger.warning(
                "create_submission: XML not stored to S3 for submission_number=%s "
                "(bucket unconfigured or upload failed)",
                submission_number,
            )

        soap_result = _submit_via_soap(
            xml_content=xml_content,
            endpoint_url=endpoint_url,
            username=_SOAP_USERNAME,
            password=_SOAP_PASSWORD,
            submission_number=submission_number,
        )

        now = datetime.now(UTC).replace(tzinfo=None)
        initial_status = "submitted" if soap_result["submitted"] else "pending"

        record = NemsisSubmissionResult(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            chart_id=body.chart_id,
            export_id=body.export_id,
            submission_number=submission_number,
            state_endpoint_url=endpoint_url or None,
            submission_status=initial_status,
            xml_s3_bucket=_S3_BUCKET if s3_uploaded else None,
            xml_s3_key=s3_key if s3_uploaded else None,
            payload_sha256=payload_sha256,
            soap_message_id=soap_result.get("message_id"),
            soap_response_code=soap_result.get("response_code"),
            submitted_at=now if soap_result["submitted"] else None,
            created_at=now,
            created_by_user_id=user_id,
        )
        session.add(record)
        await session.flush()

        await _write_history(
            session=session,
            submission_id=record.id,
            tenant_id=tenant_id,
            from_status=None,
            to_status=initial_status,
            actor_user_id=user_id,
            note=soap_result.get("error"),
        )

        await session.commit()
        await session.refresh(record)

        result = _serialize_submission(record)
        result["soap_result"] = soap_result
        logger.info(
            "create_submission: submission_id=%s submission_number=%s status=%s",
            record.id,
            submission_number,
            initial_status,
        )
        return result

    except Exception as exc:
        logger.error(
            "create_submission: unexpected error tenant_id=%s chart_id=%s: %s",
            tenant_id,
            body.chart_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Submission creation failed",
        ) from exc


@router.get("/", status_code=status.HTTP_200_OK)
async def list_submissions(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    chart_id: str | None = Query(default=None, description="Filter by chart identifier"),
    session: AsyncSession = Depends(get_session),
) -> list:
    """List NEMSIS state submissions for the requesting tenant.

    Args:
        x_tenant_id: Tenant identifier from X-Tenant-ID header.
        chart_id: Optional chart identifier to filter results.
        session: Injected async database session.

    Returns:
        List of serialized submission dicts ordered by creation time descending.

    Raises:
        HTTPException: 400 if header missing; 500 on unexpected failure.
    """
    tenant_id = _require_header(x_tenant_id, "X-Tenant-ID")

    try:
        stmt = (
            select(NemsisSubmissionResult)
            .where(NemsisSubmissionResult.tenant_id == tenant_id)
            .order_by(NemsisSubmissionResult.created_at.desc())
        )
        if chart_id:
            stmt = stmt.where(NemsisSubmissionResult.chart_id == chart_id)

        result = await session.execute(stmt)
        return [_serialize_submission(s) for s in result.scalars().all()]

    except Exception as exc:
        logger.error(
            "list_submissions: unexpected error tenant_id=%s: %s",
            tenant_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Submission list retrieval failed",
        ) from exc


@router.get("/{submission_id}", status_code=status.HTTP_200_OK)
async def get_submission(
    submission_id: str,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Return a single NEMSIS state submission by its identifier.

    Args:
        submission_id: Submission identifier from the URL path.
        x_tenant_id: Tenant identifier from X-Tenant-ID header.
        session: Injected async database session.

    Returns:
        Serialized submission dict.

    Raises:
        HTTPException: 400 if header missing; 404 if not found;
                       500 on unexpected failure.
    """
    tenant_id = _require_header(x_tenant_id, "X-Tenant-ID")

    try:
        result = await session.execute(
            select(NemsisSubmissionResult).where(
                NemsisSubmissionResult.id == submission_id,
                NemsisSubmissionResult.tenant_id == tenant_id,
            )
        )
        record = result.scalars().first()
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Submission {submission_id} not found",
            )
        return _serialize_submission(record)

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "get_submission: unexpected error submission_id=%s: %s",
            submission_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Submission retrieval failed",
        ) from exc


@router.post("/{submission_id}/retry", status_code=status.HTTP_200_OK)
async def retry_submission(
    submission_id: str,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Retry a NEMSIS state submission that is in pending or error status.

    Re-attempts SOAP submission using the stored endpoint URL and configured
    credentials. Updates submission_status and writes a history row.

    Args:
        submission_id: Submission identifier from the URL path.
        x_tenant_id: Tenant identifier from X-Tenant-ID header.
        x_user_id: Acting user identifier from X-User-ID header.
        session: Injected async database session.

    Returns:
        Serialized updated submission dict including soap_result detail.

    Raises:
        HTTPException: 400 if headers missing; 404 if not found;
                       422 if status does not allow retry; 500 on failure.
    """
    tenant_id = _require_header(x_tenant_id, "X-Tenant-ID")
    user_id = _require_user_id(x_user_id, "X-User-ID")

    try:
        result = await session.execute(
            select(NemsisSubmissionResult).where(
                NemsisSubmissionResult.id == submission_id,
                NemsisSubmissionResult.tenant_id == tenant_id,
            )
        )
        record = result.scalars().first()
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Submission {submission_id} not found",
            )

        if record.submission_status not in ("pending", "error"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Submission {submission_id} is in status "
                    f"'{record.submission_status}' and cannot be retried; "
                    "only 'pending' or 'error' submissions may be retried"
                ),
            )

        endpoint_url = record.state_endpoint_url or _STATE_ENDPOINT_URL
        soap_result = _submit_via_soap(
            xml_content="",
            endpoint_url=endpoint_url,
            username=_SOAP_USERNAME,
            password=_SOAP_PASSWORD,
            submission_number=record.submission_number,
        )

        previous_status = record.submission_status
        new_status = "submitted" if soap_result["submitted"] else "error"
        now = datetime.now(UTC).replace(tzinfo=None)

        record.submission_status = new_status
        if soap_result["submitted"]:
            record.submitted_at = now
            record.soap_message_id = soap_result.get("message_id")
            record.soap_response_code = soap_result.get("response_code")

        await _write_history(
            session=session,
            submission_id=submission_id,
            tenant_id=tenant_id,
            from_status=previous_status,
            to_status=new_status,
            actor_user_id=user_id,
            note=soap_result.get("error"),
        )

        await session.commit()
        await session.refresh(record)

        serialized = _serialize_submission(record)
        serialized["soap_result"] = soap_result
        logger.info(
            "retry_submission: submission_id=%s new_status=%s actor=%s",
            submission_id,
            new_status,
            user_id,
        )
        return serialized

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "retry_submission: unexpected error submission_id=%s: %s",
            submission_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Submission retry failed",
        ) from exc


@router.post("/{submission_id}/acknowledge", status_code=status.HTTP_200_OK)
async def acknowledge_submission(
    submission_id: str,
    body: AcknowledgeSubmissionRequest,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Acknowledge receipt of a NEMSIS state submission.

    Sets submission_status to 'acknowledged' and records the transition
    timestamp. Only submissions in 'submitted' status may be acknowledged.

    Args:
        submission_id: Submission identifier from the URL path.
        body: Optional operator note to record with the transition.
        x_tenant_id: Tenant identifier from X-Tenant-ID header.
        x_user_id: Acting user identifier from X-User-ID header.
        session: Injected async database session.

    Returns:
        Serialized updated submission dict.

    Raises:
        HTTPException: 400 if headers missing; 404 if not found;
                       422 if status is not 'submitted'; 500 on failure.
    """
    tenant_id = _require_header(x_tenant_id, "X-Tenant-ID")
    user_id = _require_user_id(x_user_id, "X-User-ID")

    try:
        result = await session.execute(
            select(NemsisSubmissionResult).where(
                NemsisSubmissionResult.id == submission_id,
                NemsisSubmissionResult.tenant_id == tenant_id,
            )
        )
        record = result.scalars().first()
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Submission {submission_id} not found",
            )

        if record.submission_status != "submitted":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Submission {submission_id} is in status "
                    f"'{record.submission_status}' and cannot be acknowledged; "
                    "only 'submitted' submissions may be acknowledged"
                ),
            )

        previous_status = record.submission_status
        now = datetime.now(UTC).replace(tzinfo=None)
        record.submission_status = "acknowledged"
        record.acknowledged_at = now

        await _write_history(
            session=session,
            submission_id=submission_id,
            tenant_id=tenant_id,
            from_status=previous_status,
            to_status="acknowledged",
            actor_user_id=user_id,
            note=body.note,
        )

        await session.commit()
        await session.refresh(record)

        logger.info(
            "acknowledge_submission: submission_id=%s actor=%s", submission_id, user_id
        )
        return _serialize_submission(record)

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "acknowledge_submission: unexpected error submission_id=%s: %s",
            submission_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Submission acknowledgment failed",
        ) from exc


@router.post("/{submission_id}/accept", status_code=status.HTTP_200_OK)
async def accept_submission(
    submission_id: str,
    body: AcceptSubmissionRequest,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Accept a NEMSIS state submission, marking it as fully resolved.

    Sets submission_status to 'accepted' and records resolved_at. Only
    submissions in 'acknowledged' status may be accepted.

    Args:
        submission_id: Submission identifier from the URL path.
        body: Optional operator note to record with the transition.
        x_tenant_id: Tenant identifier from X-Tenant-ID header.
        x_user_id: Acting user identifier from X-User-ID header.
        session: Injected async database session.

    Returns:
        Serialized updated submission dict.

    Raises:
        HTTPException: 400 if headers missing; 404 if not found;
                       422 if status is not 'acknowledged'; 500 on failure.
    """
    tenant_id = _require_header(x_tenant_id, "X-Tenant-ID")
    user_id = _require_user_id(x_user_id, "X-User-ID")

    try:
        result = await session.execute(
            select(NemsisSubmissionResult).where(
                NemsisSubmissionResult.id == submission_id,
                NemsisSubmissionResult.tenant_id == tenant_id,
            )
        )
        record = result.scalars().first()
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Submission {submission_id} not found",
            )

        if record.submission_status != "acknowledged":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Submission {submission_id} is in status "
                    f"'{record.submission_status}' and cannot be accepted; "
                    "only 'acknowledged' submissions may be accepted"
                ),
            )

        previous_status = record.submission_status
        now = datetime.now(UTC).replace(tzinfo=None)
        record.submission_status = "accepted"
        record.resolved_at = now

        await _write_history(
            session=session,
            submission_id=submission_id,
            tenant_id=tenant_id,
            from_status=previous_status,
            to_status="accepted",
            actor_user_id=user_id,
            note=body.note,
        )

        await session.commit()
        await session.refresh(record)

        logger.info(
            "accept_submission: submission_id=%s actor=%s", submission_id, user_id
        )
        return _serialize_submission(record)

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "accept_submission: unexpected error submission_id=%s: %s",
            submission_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Submission acceptance failed",
        ) from exc


@router.post("/{submission_id}/reject", status_code=status.HTTP_200_OK)
async def reject_submission(
    submission_id: str,
    body: RejectSubmissionRequest,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Reject a NEMSIS state submission, recording the rejection reason.

    Sets submission_status to 'rejected', records resolved_at, and
    persists the rejection_reason. Only submissions in 'submitted' or
    'acknowledged' status may be rejected.

    Args:
        submission_id: Submission identifier from the URL path.
        body: Rejection reason, required.
        x_tenant_id: Tenant identifier from X-Tenant-ID header.
        x_user_id: Acting user identifier from X-User-ID header.
        session: Injected async database session.

    Returns:
        Serialized updated submission dict.

    Raises:
        HTTPException: 400 if headers missing; 404 if not found;
                       422 if status does not allow rejection; 500 on failure.
    """
    tenant_id = _require_header(x_tenant_id, "X-Tenant-ID")
    user_id = _require_user_id(x_user_id, "X-User-ID")

    try:
        result = await session.execute(
            select(NemsisSubmissionResult).where(
                NemsisSubmissionResult.id == submission_id,
                NemsisSubmissionResult.tenant_id == tenant_id,
            )
        )
        record = result.scalars().first()
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Submission {submission_id} not found",
            )

        if record.submission_status not in ("submitted", "acknowledged"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Submission {submission_id} is in status "
                    f"'{record.submission_status}' and cannot be rejected; "
                    "only 'submitted' or 'acknowledged' submissions may be rejected"
                ),
            )

        previous_status = record.submission_status
        now = datetime.now(UTC).replace(tzinfo=None)
        record.submission_status = "rejected"
        record.resolved_at = now
        record.rejection_reason = body.rejection_reason

        await _write_history(
            session=session,
            submission_id=submission_id,
            tenant_id=tenant_id,
            from_status=previous_status,
            to_status="rejected",
            actor_user_id=user_id,
            note=body.rejection_reason,
        )

        await session.commit()
        await session.refresh(record)

        logger.info(
            "reject_submission: submission_id=%s actor=%s reason=%s",
            submission_id,
            user_id,
            body.rejection_reason,
        )
        return _serialize_submission(record)

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "reject_submission: unexpected error submission_id=%s: %s",
            submission_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Submission rejection failed",
        ) from exc


@router.get("/{submission_id}/history", status_code=status.HTTP_200_OK)
async def get_submission_history(
    submission_id: str,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    session: AsyncSession = Depends(get_session),
) -> list:
    """Return the status transition history for a NEMSIS state submission.

    Verifies the submission exists for the tenant, then returns all history
    rows ordered by transitioned_at ascending.

    Args:
        submission_id: Submission identifier from the URL path.
        x_tenant_id: Tenant identifier from X-Tenant-ID header.
        session: Injected async database session.

    Returns:
        List of serialized history dicts ordered by transitioned_at ascending.

    Raises:
        HTTPException: 400 if header missing; 404 if submission not found;
                       500 on unexpected failure.
    """
    tenant_id = _require_header(x_tenant_id, "X-Tenant-ID")

    try:
        sub_result = await session.execute(
            select(NemsisSubmissionResult).where(
                NemsisSubmissionResult.id == submission_id,
                NemsisSubmissionResult.tenant_id == tenant_id,
            )
        )
        if not sub_result.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Submission {submission_id} not found",
            )

        hist_result = await session.execute(
            select(NemsisSubmissionStatusHistory)
            .where(NemsisSubmissionStatusHistory.submission_id == submission_id)
            .order_by(NemsisSubmissionStatusHistory.transitioned_at.asc())
        )
        return [_serialize_history(h) for h in hist_result.scalars().all()]

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "get_submission_history: unexpected error submission_id=%s: %s",
            submission_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Submission history retrieval failed",
        ) from exc
