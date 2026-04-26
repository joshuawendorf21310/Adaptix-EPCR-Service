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

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.models import Chart, NemsisMappingRecord
from epcr_app.models_nemsis_core import NemsisSubmissionResult, NemsisSubmissionStatusHistory
from epcr_app.nemsis_xml_builder import NemsisBuildError, NemsisXmlBuilder
from epcr_app.nemsis_xsd_validator import NemsisXSDValidator

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


async def _write_history(
    session: AsyncSession,
    submission_id: str,
    tenant_id: str,
    from_status: str | None,
    to_status: str,
    actor_user_id: str | None,
    note: str | None = None,
) -> None:
    row = NemsisSubmissionStatusHistory(
        id=str(uuid.uuid4()),
        submission_id=submission_id,
        tenant_id=tenant_id,
        from_status=from_status,
        to_status=to_status,
        actor_user_id=actor_user_id,
        note=note,
        transitioned_at=datetime.now(UTC),
    )
    session.add(row)


def _upload_xml_to_s3(xml_bytes: bytes, s3_key: str) -> bool:
    if not _S3_BUCKET:
        return False
    try:
        import boto3

        boto3.client("s3").put_object(
            Bucket=_S3_BUCKET,
            Key=s3_key,
            Body=xml_bytes,
            ContentType="application/xml",
            ServerSideEncryption="AES256",
        )
        return True
    except Exception as exc:
        logger.error("S3 upload failed key=%s: %s", s3_key, exc, exc_info=True)
        return False


def _submit_via_soap(
    xml_content: str,
    endpoint_url: str,
    username: str,
    password: str,
    submission_number: str,
) -> dict[str, Any]:
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


async def _load_chart_and_mappings(
    session: AsyncSession,
    *,
    tenant_id: str,
    chart_id: str,
) -> tuple[Chart, list[NemsisMappingRecord]]:
    chart_result = await session.execute(
        select(Chart).where(
            Chart.id == chart_id,
            Chart.tenant_id == tenant_id,
            Chart.deleted_at.is_(None),
        )
    )
    chart = chart_result.scalars().first()
    if not chart:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Chart {chart_id} not found",
        )

    mapping_result = await session.execute(
        select(NemsisMappingRecord).where(
            NemsisMappingRecord.chart_id == chart_id,
        )
    )
    mappings = list(mapping_result.scalars().all())
    return chart, mappings


async def _build_validated_xml(
    session: AsyncSession,
    *,
    tenant_id: str,
    chart_id: str,
) -> tuple[bytes, list[str], dict[str, Any]]:
    chart, mappings = await _load_chart_and_mappings(
        session,
        tenant_id=tenant_id,
        chart_id=chart_id,
    )

    try:
        builder = NemsisXmlBuilder(chart=chart, mapping_records=mappings)
        xml_bytes, warnings = builder.build()
    except NemsisBuildError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"NEMSIS XML build failed: {exc}",
        ) from exc

    validator = NemsisXSDValidator()
    validation = validator.validate_xml(xml_bytes)

    if validation.get("validation_skipped", False):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "NEMSIS validation did not run",
                "blocking_reason": validation.get("blocking_reason"),
                "xsd_errors": validation.get("xsd_errors", []),
                "schematron_errors": validation.get("schematron_errors", []),
                "schematron_warnings": validation.get("schematron_warnings", []),
            },
        )

    if not validation.get("valid", False):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "NEMSIS validation failed",
                "xsd_errors": validation.get("xsd_errors", []),
                "schematron_errors": validation.get("schematron_errors", []),
                "schematron_warnings": validation.get("schematron_warnings", []),
                "cardinality_errors": validation.get("cardinality_errors", []),
            },
        )

    return xml_bytes, warnings, validation


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_submission(
    body: CreateSubmissionRequest,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    tenant_id = str(current_user.tenant_id)
    user_id = str(current_user.user_id)

    try:
        submission_number = (
            f"SUB-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
        )
        endpoint_url = body.state_endpoint_url or _STATE_ENDPOINT_URL

        xml_bytes, warnings, validation = await _build_validated_xml(
            session,
            tenant_id=tenant_id,
            chart_id=body.chart_id,
        )

        xml_content = xml_bytes.decode("utf-8", errors="strict")
        payload_sha256 = hashlib.sha256(xml_bytes).hexdigest()

        s3_key = f"{_S3_PREFIX}/{tenant_id}/{submission_number}.xml"
        s3_uploaded = _upload_xml_to_s3(xml_bytes, s3_key)
        if not s3_uploaded:
            logger.warning(
                "create_submission: XML not stored to S3 for submission_number=%s",
                submission_number,
            )

        soap_result = _submit_via_soap(
            xml_content=xml_content,
            endpoint_url=endpoint_url,
            username=_SOAP_USERNAME,
            password=_SOAP_PASSWORD,
            submission_number=submission_number,
        )

        now = datetime.now(UTC)
        initial_status = "submitted" if soap_result["submitted"] else "error"

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
        result["validation"] = validation
        result["warnings"] = warnings
        logger.info(
            "create_submission: submission_id=%s submission_number=%s status=%s",
            record.id,
            submission_number,
            initial_status,
        )
        return result

    except HTTPException:
        await session.rollback()
        raise
    except Exception as exc:
        await session.rollback()
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
    current_user: CurrentUser = Depends(get_current_user),
    chart_id: str | None = Query(default=None, description="Filter by chart identifier"),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    tenant_id = str(current_user.tenant_id)

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
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    tenant_id = str(current_user.tenant_id)

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
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    tenant_id = str(current_user.tenant_id)
    user_id = str(current_user.user_id)

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

        xml_bytes, warnings, validation = await _build_validated_xml(
            session,
            tenant_id=tenant_id,
            chart_id=record.chart_id,
        )
        xml_content = xml_bytes.decode("utf-8", errors="strict")
        payload_sha256 = hashlib.sha256(xml_bytes).hexdigest()

        s3_key = record.xml_s3_key or f"{_S3_PREFIX}/{tenant_id}/{record.submission_number}.xml"
        s3_uploaded = _upload_xml_to_s3(xml_bytes, s3_key)

        endpoint_url = record.state_endpoint_url or _STATE_ENDPOINT_URL
        soap_result = _submit_via_soap(
            xml_content=xml_content,
            endpoint_url=endpoint_url,
            username=_SOAP_USERNAME,
            password=_SOAP_PASSWORD,
            submission_number=record.submission_number,
        )

        previous_status = record.submission_status
        new_status = "submitted" if soap_result["submitted"] else "error"
        now = datetime.now(UTC)

        record.submission_status = new_status
        record.payload_sha256 = payload_sha256
        record.xml_s3_bucket = _S3_BUCKET if s3_uploaded else record.xml_s3_bucket
        record.xml_s3_key = s3_key if s3_uploaded else record.xml_s3_key
        record.state_endpoint_url = endpoint_url or None
        record.soap_message_id = soap_result.get("message_id")
        record.soap_response_code = soap_result.get("response_code")
        record.rejection_reason = None
        if soap_result["submitted"]:
            record.submitted_at = now

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
        serialized["validation"] = validation
        serialized["warnings"] = warnings
        logger.info(
            "retry_submission: submission_id=%s new_status=%s actor=%s",
            submission_id,
            new_status,
            user_id,
        )
        return serialized

    except HTTPException:
        await session.rollback()
        raise
    except Exception as exc:
        await session.rollback()
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
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    tenant_id = str(current_user.tenant_id)
    user_id = str(current_user.user_id)

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
        now = datetime.now(UTC)
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
            "acknowledge_submission: submission_id=%s actor=%s",
            submission_id,
            user_id,
        )
        return _serialize_submission(record)

    except HTTPException:
        await session.rollback()
        raise
    except Exception as exc:
        await session.rollback()
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
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    tenant_id = str(current_user.tenant_id)
    user_id = str(current_user.user_id)

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
        now = datetime.now(UTC)
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
            "accept_submission: submission_id=%s actor=%s",
            submission_id,
            user_id,
        )
        return _serialize_submission(record)

    except HTTPException:
        await session.rollback()
        raise
    except Exception as exc:
        await session.rollback()
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
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    tenant_id = str(current_user.tenant_id)
    user_id = str(current_user.user_id)

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
        now = datetime.now(UTC)
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
        await session.rollback()
        raise
    except Exception as exc:
        await session.rollback()
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
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    tenant_id = str(current_user.tenant_id)

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