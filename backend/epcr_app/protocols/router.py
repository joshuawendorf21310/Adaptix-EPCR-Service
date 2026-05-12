from __future__ import annotations

import uuid
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.protocols.models import EPCRProtocol
from epcr_app.protocols.schemas import ProtocolCreate, ProtocolResponse, ProtocolUpdate

router = APIRouter(prefix="/api/v1/epcr/protocols", tags=["protocols"])

_PROTOCOL_ROLES = {"clinical_admin", "medical_director", "admin"}


def _require_protocol_role(current_user: CurrentUser) -> None:
    roles = set(r.strip() for r in (current_user.roles or "").split(","))
    if not roles.intersection(_PROTOCOL_ROLES):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"One of {_PROTOCOL_ROLES} role required",
        )


@router.get("/", response_model=List[ProtocolResponse])
async def list_protocols(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> List[ProtocolResponse]:
    tenant_id = current_user.tenant_id
    result = await db.execute(
        select(EPCRProtocol).where(
            EPCRProtocol.tenant_id == tenant_id,
            EPCRProtocol.status == "active",
        )
    )
    return [ProtocolResponse.model_validate(p) for p in result.scalars().all()]


@router.get("/{protocol_id}", response_model=ProtocolResponse)
async def get_protocol(
    protocol_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> ProtocolResponse:
    result = await db.execute(
        select(EPCRProtocol).where(
            EPCRProtocol.id == protocol_id,
            EPCRProtocol.tenant_id == current_user.tenant_id,
        )
    )
    protocol = result.scalar_one_or_none()
    if protocol is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Protocol not found")
    return ProtocolResponse.model_validate(protocol)


@router.post("/", response_model=ProtocolResponse, status_code=status.HTTP_201_CREATED)
async def create_protocol(
    payload: ProtocolCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> ProtocolResponse:
    _require_protocol_role(current_user)
    protocol = EPCRProtocol(
        id=uuid.uuid4(),
        tenant_id=current_user.tenant_id,
        title=payload.title,
        category=payload.category,
        version=payload.version,
        status=payload.status,
        effective_date=payload.effective_date,
        content=payload.content,
        source_reference=payload.source_reference,
        created_by=current_user.user_id,
        created_at=datetime.utcnow(),
    )
    db.add(protocol)
    await db.commit()
    await db.refresh(protocol)
    return ProtocolResponse.model_validate(protocol)


@router.patch("/{protocol_id}", response_model=ProtocolResponse)
async def update_protocol(
    protocol_id: uuid.UUID,
    payload: ProtocolUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> ProtocolResponse:
    _require_protocol_role(current_user)
    result = await db.execute(
        select(EPCRProtocol).where(
            EPCRProtocol.id == protocol_id,
            EPCRProtocol.tenant_id == current_user.tenant_id,
        )
    )
    protocol = result.scalar_one_or_none()
    if protocol is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Protocol not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(protocol, field, value)
    protocol.updated_by = current_user.user_id
    protocol.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(protocol)
    return ProtocolResponse.model_validate(protocol)


@router.post("/{protocol_id}/retire", response_model=ProtocolResponse)
async def retire_protocol(
    protocol_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> ProtocolResponse:
    _require_protocol_role(current_user)
    result = await db.execute(
        select(EPCRProtocol).where(
            EPCRProtocol.id == protocol_id,
            EPCRProtocol.tenant_id == current_user.tenant_id,
        )
    )
    protocol = result.scalar_one_or_none()
    if protocol is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Protocol not found")
    if protocol.status == "retired":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Protocol already retired")
    protocol.status = "retired"
    protocol.retired_date = datetime.utcnow()
    protocol.updated_by = current_user.user_id
    protocol.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(protocol)
    return ProtocolResponse.model_validate(protocol)
