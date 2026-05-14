"""ePCR Attachment Service. Manages attachments in ePCR charts."""
from __future__ import annotations
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict
logger = logging.getLogger(__name__)

class EpcrAttachmentService:
    def add_attachment(self, *, chart_id: str, tenant_id: str, actor_id: str, attachment_type: str, file_reference: str) -> Dict[str, Any]:
        if not chart_id or not attachment_type or not file_reference:
            raise ValueError("chart_id, attachment_type, and file_reference are required")
        return {"attachment_id": str(uuid.uuid4()), "chart_id": chart_id, "attachment_type": attachment_type, "file_reference": file_reference, "added_at": datetime.now(timezone.utc).isoformat(), "added_by": actor_id}
