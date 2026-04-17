"""NEMSIS resource pack management API routes.

Provides routes for creating, uploading files to, activating, staging,
archiving, and querying NEMSIS resource packs. All state transitions are
persisted. S3 upload occurs on file ingest when configured.

Routes:
- POST   /api/v1/epcr/nemsis/packs                     — create pack
- GET    /api/v1/epcr/nemsis/packs                     — list packs
- GET    /api/v1/epcr/nemsis/packs/{pack_id}           — get pack
- POST   /api/v1/epcr/nemsis/packs/{pack_id}/activate  — activate pack
- POST   /api/v1/epcr/nemsis/packs/{pack_id}/archive   — archive pack
- POST   /api/v1/epcr/nemsis/packs/{pack_id}/stage     — stage pack
- POST   /api/v1/epcr/nemsis/packs/{pack_id}/files     — upload file to pack
- GET    /api/v1/epcr/nemsis/packs/{pack_id}/files     — list pack files
- GET    /api/v1/epcr/nemsis/packs/{pack_id}/completeness — completeness check
"""
import logging

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.nemsis_pack_manager import PackManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/epcr/nemsis/packs", tags=["nemsis-packs"])


class CreatePackRequest(BaseModel):
    """Request body for creating a new NEMSIS resource pack."""

    name: str
    pack_type: str
    nemsis_version: str = "3.5.1"


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


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_pack(
    body: CreatePackRequest,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Create a new NEMSIS resource pack in pending status.

    Args:
        body: Pack creation parameters including name, type, and NEMSIS version.
        x_tenant_id: Tenant identifier from X-Tenant-ID header.
        x_user_id: Acting user identifier from X-User-ID header.
        session: Injected async database session.

    Returns:
        Serialized pack dict with HTTP 201.

    Raises:
        HTTPException: 400 if headers missing or pack_type invalid;
                       500 on unexpected failure.
    """
    tenant_id = _require_header(x_tenant_id, "X-Tenant-ID")
    user_id = _require_user_id(x_user_id, "X-User-ID")

    try:
        manager = PackManager(session)
        pack = await manager.create_pack(
            tenant_id=tenant_id,
            name=body.name,
            pack_type=body.pack_type,
            nemsis_version=body.nemsis_version,
            created_by_user_id=user_id,
        )
        await session.commit()
        return pack
    except ValueError as exc:
        logger.warning(
            "create_pack: validation error tenant_id=%s: %s", tenant_id, exc
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.error(
            "create_pack: unexpected error tenant_id=%s: %s", tenant_id, exc, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Pack creation failed",
        ) from exc


@router.get("/", status_code=status.HTTP_200_OK)
async def list_packs(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    session: AsyncSession = Depends(get_session),
) -> list:
    """List all NEMSIS resource packs for the requesting tenant.

    Args:
        x_tenant_id: Tenant identifier from X-Tenant-ID header.
        session: Injected async database session.

    Returns:
        List of serialized pack dicts ordered by creation time descending.

    Raises:
        HTTPException: 400 if header missing; 500 on unexpected failure.
    """
    tenant_id = _require_header(x_tenant_id, "X-Tenant-ID")

    try:
        manager = PackManager(session)
        return await manager.list_packs(tenant_id=tenant_id)
    except Exception as exc:
        logger.error(
            "list_packs: unexpected error tenant_id=%s: %s", tenant_id, exc, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Pack list retrieval failed",
        ) from exc


@router.get("/{pack_id}", status_code=status.HTTP_200_OK)
async def get_pack(
    pack_id: str,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Return a single NEMSIS resource pack by its identifier.

    Args:
        pack_id: Pack identifier from the URL path.
        x_tenant_id: Tenant identifier from X-Tenant-ID header.
        session: Injected async database session.

    Returns:
        Serialized pack dict.

    Raises:
        HTTPException: 400 if header missing; 404 if pack not found;
                       500 on unexpected failure.
    """
    tenant_id = _require_header(x_tenant_id, "X-Tenant-ID")

    try:
        manager = PackManager(session)
        return await manager.get_pack(pack_id=pack_id, tenant_id=tenant_id)
    except ValueError as exc:
        logger.warning(
            "get_pack: not found pack_id=%s tenant_id=%s: %s", pack_id, tenant_id, exc
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.error(
            "get_pack: unexpected error pack_id=%s: %s", pack_id, exc, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Pack retrieval failed",
        ) from exc


@router.post("/{pack_id}/activate", status_code=status.HTTP_200_OK)
async def activate_pack(
    pack_id: str,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Activate a NEMSIS resource pack, archiving any existing active pack of the same type.

    Args:
        pack_id: Pack identifier from the URL path.
        x_tenant_id: Tenant identifier from X-Tenant-ID header.
        x_user_id: Acting user identifier from X-User-ID header.
        session: Injected async database session.

    Returns:
        Serialized updated pack dict.

    Raises:
        HTTPException: 400 if headers missing or transition invalid;
                       404 if pack not found; 500 on unexpected failure.
    """
    tenant_id = _require_header(x_tenant_id, "X-Tenant-ID")
    user_id = _require_user_id(x_user_id, "X-User-ID")

    try:
        manager = PackManager(session)
        pack = await manager.activate_pack(
            pack_id=pack_id,
            tenant_id=tenant_id,
            actor_user_id=user_id,
        )
        await session.commit()
        return pack
    except ValueError as exc:
        msg = str(exc)
        logger.warning(
            "activate_pack: error pack_id=%s tenant_id=%s: %s", pack_id, tenant_id, msg
        )
        http_status = (
            status.HTTP_404_NOT_FOUND
            if "not found" in msg.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=http_status, detail=msg) from exc
    except Exception as exc:
        logger.error(
            "activate_pack: unexpected error pack_id=%s: %s", pack_id, exc, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Pack activation failed",
        ) from exc


@router.post("/{pack_id}/stage", status_code=status.HTTP_200_OK)
async def stage_pack(
    pack_id: str,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Stage a NEMSIS resource pack for review before activation.

    Args:
        pack_id: Pack identifier from the URL path.
        x_tenant_id: Tenant identifier from X-Tenant-ID header.
        x_user_id: Acting user identifier from X-User-ID header.
        session: Injected async database session.

    Returns:
        Serialized updated pack dict.

    Raises:
        HTTPException: 400 if headers missing or transition invalid;
                       500 on unexpected failure.
    """
    tenant_id = _require_header(x_tenant_id, "X-Tenant-ID")
    user_id = _require_user_id(x_user_id, "X-User-ID")

    try:
        manager = PackManager(session)
        pack = await manager.stage_pack(
            pack_id=pack_id,
            tenant_id=tenant_id,
            actor_user_id=user_id,
        )
        await session.commit()
        return pack
    except ValueError as exc:
        logger.warning(
            "stage_pack: error pack_id=%s tenant_id=%s: %s", pack_id, tenant_id, exc
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.error(
            "stage_pack: unexpected error pack_id=%s: %s", pack_id, exc, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Pack staging failed",
        ) from exc


@router.post("/{pack_id}/archive", status_code=status.HTTP_200_OK)
async def archive_pack(
    pack_id: str,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Archive a NEMSIS resource pack, preventing further use.

    Args:
        pack_id: Pack identifier from the URL path.
        x_tenant_id: Tenant identifier from X-Tenant-ID header.
        x_user_id: Acting user identifier from X-User-ID header.
        session: Injected async database session.

    Returns:
        Serialized updated pack dict.

    Raises:
        HTTPException: 400 if headers missing or pack not found;
                       500 on unexpected failure.
    """
    tenant_id = _require_header(x_tenant_id, "X-Tenant-ID")
    user_id = _require_user_id(x_user_id, "X-User-ID")

    try:
        manager = PackManager(session)
        pack = await manager.archive_pack(
            pack_id=pack_id,
            tenant_id=tenant_id,
            actor_user_id=user_id,
        )
        await session.commit()
        return pack
    except ValueError as exc:
        logger.warning(
            "archive_pack: error pack_id=%s tenant_id=%s: %s", pack_id, tenant_id, exc
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.error(
            "archive_pack: unexpected error pack_id=%s: %s", pack_id, exc, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Pack archival failed",
        ) from exc


@router.post("/{pack_id}/files", status_code=status.HTTP_201_CREATED)
async def upload_file(
    pack_id: str,
    file: UploadFile = File(...),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Upload a file into a NEMSIS resource pack.

    Reads the uploaded file bytes, detects the file role from its extension,
    computes a SHA-256 digest, stores metadata in the database, and uploads
    to S3 when configured.

    Args:
        pack_id: Pack identifier from the URL path.
        file: Uploaded file from multipart form data.
        x_tenant_id: Tenant identifier from X-Tenant-ID header.
        x_user_id: Acting user identifier from X-User-ID header.
        session: Injected async database session.

    Returns:
        Serialized pack file dict with HTTP 201.

    Raises:
        HTTPException: 400 if headers missing or validation fails;
                       404 if pack not found; 500 on unexpected failure.
    """
    tenant_id = _require_header(x_tenant_id, "X-Tenant-ID")
    user_id = _require_user_id(x_user_id, "X-User-ID")

    try:
        file_content = await file.read()
        manager = PackManager(session)
        pack_file = await manager.ingest_file(
            pack_id=pack_id,
            tenant_id=tenant_id,
            file_name=file.filename or "unknown",
            file_content=file_content,
        )
        await session.commit()
        logger.info(
            "upload_file: pack_id=%s file=%s actor=%s",
            pack_id,
            file.filename,
            user_id,
        )
        return pack_file
    except ValueError as exc:
        msg = str(exc)
        logger.warning(
            "upload_file: error pack_id=%s tenant_id=%s: %s", pack_id, tenant_id, msg
        )
        http_status = (
            status.HTTP_404_NOT_FOUND
            if "not found" in msg.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=http_status, detail=msg) from exc
    except Exception as exc:
        logger.error(
            "upload_file: unexpected error pack_id=%s: %s", pack_id, exc, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="File upload failed",
        ) from exc


@router.get("/{pack_id}/files", status_code=status.HTTP_200_OK)
async def list_pack_files(
    pack_id: str,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    session: AsyncSession = Depends(get_session),
) -> list:
    """List all files attached to a NEMSIS resource pack.

    Args:
        pack_id: Pack identifier from the URL path.
        x_tenant_id: Tenant identifier from X-Tenant-ID header.
        session: Injected async database session.

    Returns:
        List of serialized pack file dicts.

    Raises:
        HTTPException: 400 if header missing; 404 if pack not found;
                       500 on unexpected failure.
    """
    tenant_id = _require_header(x_tenant_id, "X-Tenant-ID")

    try:
        manager = PackManager(session)
        return await manager.list_pack_files(pack_id=pack_id, tenant_id=tenant_id)
    except ValueError as exc:
        logger.warning(
            "list_pack_files: not found pack_id=%s tenant_id=%s: %s",
            pack_id, tenant_id, exc,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.error(
            "list_pack_files: unexpected error pack_id=%s: %s", pack_id, exc, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="File list retrieval failed",
        ) from exc


@router.get("/{pack_id}/completeness", status_code=status.HTTP_200_OK)
async def get_pack_completeness(
    pack_id: str,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Return a completeness analysis for a NEMSIS resource pack.

    Evaluates which required file roles are present based on the pack type
    and reports which roles are missing.

    Args:
        pack_id: Pack identifier from the URL path.
        x_tenant_id: Tenant identifier from X-Tenant-ID header.
        session: Injected async database session.

    Returns:
        Dict with file_count, files_by_role, required_roles, missing_roles,
        and is_complete boolean.

    Raises:
        HTTPException: 400 if header missing; 404 if pack not found;
                       500 on unexpected failure.
    """
    tenant_id = _require_header(x_tenant_id, "X-Tenant-ID")

    try:
        manager = PackManager(session)
        return await manager.get_pack_completeness(pack_id=pack_id, tenant_id=tenant_id)
    except ValueError as exc:
        logger.warning(
            "get_pack_completeness: not found pack_id=%s tenant_id=%s: %s",
            pack_id, tenant_id, exc,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.error(
            "get_pack_completeness: unexpected error pack_id=%s: %s",
            pack_id, exc, exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Completeness check failed",
        ) from exc
