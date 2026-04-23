"""NEMSIS 3.5.1 gravity-level resource pack management API.

Authoritative control plane for:
- pack lifecycle (strict state machine)
- file ingestion with integrity enforcement
- validation gating before activation
- immutability after activation
- audit-safe transitions

All transitions are enforced at the API boundary.
"""

from __future__ import annotations

import hashlib
import logging
from enum import Enum
from typing import Any

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.nemsis_pack_manager import PackManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/epcr/nemsis/packs", tags=["nemsis-packs"])


# -------------------------
# Lifecycle
# -------------------------

class PackLifecycleStatus(str, Enum):
    DRAFT = "draft"
    STAGED = "staged"
    VALIDATION_FAILED = "validation_failed"
    READY = "ready"
    ACTIVE = "active"
    ARCHIVED = "archived"


_ALLOWED_TRANSITIONS = {
    PackLifecycleStatus.DRAFT: {PackLifecycleStatus.STAGED},
    PackLifecycleStatus.STAGED: {
        PackLifecycleStatus.READY,
        PackLifecycleStatus.VALIDATION_FAILED,
    },
    PackLifecycleStatus.VALIDATION_FAILED: {PackLifecycleStatus.STAGED},
    PackLifecycleStatus.READY: {PackLifecycleStatus.ACTIVE},
    PackLifecycleStatus.ACTIVE: {PackLifecycleStatus.ARCHIVED},
}


def _enforce_transition(current: str, target: PackLifecycleStatus) -> None:
    try:
        current_enum = PackLifecycleStatus(current)
    except Exception:
        raise HTTPException(status_code=500, detail="Invalid current pack state")

    if target not in _ALLOWED_TRANSITIONS.get(current_enum, set()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Illegal state transition {current_enum.value} -> {target.value}",
        )


# -------------------------
# Models
# -------------------------

class CreatePackRequest(BaseModel):
    name: str
    pack_type: str
    nemsis_version: str = "3.5.1"


# -------------------------
# Helpers
# -------------------------

def _require_non_empty_header(value: str | None, name: str) -> str:
    if not value or not value.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{name} header required",
        )
    return value.strip()


def _value_error_status(exc: ValueError) -> int:
    message = str(exc).lower()
    if "not found" in message:
        return status.HTTP_404_NOT_FOUND
    return status.HTTP_400_BAD_REQUEST


def _validate_file_type(file_name: str) -> None:
    allowed = (".xsd", ".xml", ".sch", ".json")
    if not file_name.lower().endswith(allowed):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file_name}",
        )


# -------------------------
# Routes
# -------------------------

@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_pack(
    body: CreatePackRequest,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    tenant_id = _require_non_empty_header(x_tenant_id, "X-Tenant-ID")
    user_id = _require_non_empty_header(x_user_id, "X-User-ID")

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
        await session.rollback()
        raise HTTPException(_value_error_status(exc), str(exc))
    except Exception:
        await session.rollback()
        raise HTTPException(500, "Pack creation failed")


@router.get("/", status_code=status.HTTP_200_OK)
async def list_packs(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    tenant_id = _require_non_empty_header(x_tenant_id, "X-Tenant-ID")

    manager = PackManager(session)
    return await manager.list_packs(tenant_id=tenant_id)


@router.get("/{pack_id}", status_code=status.HTTP_200_OK)
async def get_pack(
    pack_id: str,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    tenant_id = _require_non_empty_header(x_tenant_id, "X-Tenant-ID")

    manager = PackManager(session)
    return await manager.get_pack(pack_id=pack_id, tenant_id=tenant_id)


@router.post("/{pack_id}/stage", status_code=status.HTTP_200_OK)
async def stage_pack(
    pack_id: str,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    tenant_id = _require_non_empty_header(x_tenant_id, "X-Tenant-ID")
    user_id = _require_non_empty_header(x_user_id, "X-User-ID")

    manager = PackManager(session)
    pack = await manager.get_pack(pack_id, tenant_id)

    _enforce_transition(pack["status"], PackLifecycleStatus.STAGED)

    result = await manager.stage_pack(pack_id, tenant_id, user_id)
    await session.commit()
    return result


@router.post("/{pack_id}/activate", status_code=status.HTTP_200_OK)
async def activate_pack(
    pack_id: str,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    tenant_id = _require_non_empty_header(x_tenant_id, "X-Tenant-ID")
    user_id = _require_non_empty_header(x_user_id, "X-User-ID")

    manager = PackManager(session)
    pack = await manager.get_pack(pack_id, tenant_id)

    _enforce_transition(pack["status"], PackLifecycleStatus.ACTIVE)

    completeness = await manager.get_pack_completeness(pack_id, tenant_id)
    if not completeness.get("is_complete"):
        raise HTTPException(400, "Pack not complete")

    validation = await manager.validate_pack(pack_id, tenant_id)
    if not validation.get("valid"):
        raise HTTPException(400, "Pack validation failed")

    result = await manager.activate_pack(pack_id, tenant_id, user_id)
    await session.commit()
    return result


@router.post("/{pack_id}/archive", status_code=status.HTTP_200_OK)
async def archive_pack(
    pack_id: str,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    tenant_id = _require_non_empty_header(x_tenant_id, "X-Tenant-ID")
    user_id = _require_non_empty_header(x_user_id, "X-User-ID")

    manager = PackManager(session)
    pack = await manager.get_pack(pack_id, tenant_id)

    _enforce_transition(pack["status"], PackLifecycleStatus.ARCHIVED)

    result = await manager.archive_pack(pack_id, tenant_id, user_id)
    await session.commit()
    return result


@router.post("/{pack_id}/files", status_code=status.HTTP_201_CREATED)
async def upload_file(
    pack_id: str,
    file: UploadFile = File(...),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    tenant_id = _require_non_empty_header(x_tenant_id, "X-Tenant-ID")
    _require_non_empty_header(x_user_id, "X-User-ID")

    manager = PackManager(session)
    pack = await manager.get_pack(pack_id, tenant_id)

    if pack["status"] == PackLifecycleStatus.ACTIVE.value:
        raise HTTPException(409, "Cannot modify active pack")

    file_content = await file.read()
    _validate_file_type(file.filename or "")

    checksum = hashlib.sha256(file_content).hexdigest()

    result = await manager.ingest_file(
        pack_id=pack_id,
        tenant_id=tenant_id,
        file_name=file.filename or "unknown",
        file_content=file_content,
        checksum=checksum,
    )

    await session.commit()
    return result


@router.get("/{pack_id}/files", status_code=status.HTTP_200_OK)
async def list_pack_files(
    pack_id: str,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    tenant_id = _require_non_empty_header(x_tenant_id, "X-Tenant-ID")

    manager = PackManager(session)
    return await manager.list_pack_files(pack_id, tenant_id)


@router.get("/{pack_id}/completeness", status_code=status.HTTP_200_OK)
async def get_pack_completeness(
    pack_id: str,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    tenant_id = _require_non_empty_header(x_tenant_id, "X-Tenant-ID")

    manager = PackManager(session)
    return await manager.get_pack_completeness(pack_id, tenant_id)