from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ProtocolCreate(BaseModel):
    title: str
    category: Optional[str] = None
    version: str = "1.0"
    status: str = "active"
    effective_date: Optional[datetime] = None
    content: Optional[str] = None
    source_reference: Optional[str] = None


class ProtocolUpdate(BaseModel):
    title: Optional[str] = None
    category: Optional[str] = None
    status: Optional[str] = None
    effective_date: Optional[datetime] = None
    retired_date: Optional[datetime] = None
    content: Optional[str] = None


class ProtocolResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    title: str
    category: Optional[str]
    version: str
    status: str
    effective_date: Optional[datetime]
    retired_date: Optional[datetime]
    source_reference: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}
