from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID

from epcr_app.models import Base


class EPCRProtocol(Base):
    __tablename__ = "epcr_protocols"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    title = Column(String, nullable=False)
    category = Column(String, nullable=True)
    version = Column(String, nullable=False, default="1.0")
    status = Column(String, nullable=False, default="active")
    effective_date = Column(DateTime, nullable=True)
    retired_date = Column(DateTime, nullable=True)
    content = Column(Text, nullable=True)
    source_reference = Column(String, nullable=True)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    updated_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True)
