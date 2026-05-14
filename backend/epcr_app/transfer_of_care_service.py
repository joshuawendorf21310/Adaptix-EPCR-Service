"""ePCR Transfer of Care Service. Manages transfer of care documentation."""
from __future__ import annotations
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
logger = logging.getLogger(__name__)

class EpcrTransferOfCareService:
    def document_transfer(self, *, chart_id: str, tenant_id: str, actor_id: str, receiving_facility: str, receiving_clinician: Optional[str] = None) -> Dict[str, Any]:
        if not chart_id or not receiving_facility:
            raise ValueError("chart_id and receiving_facility are required")
        return {"transfer_id": str(uuid.uuid4()), "chart_id": chart_id, "receiving_facility": receiving_facility, "receiving_clinician": receiving_clinician, "transferred_at": datetime.now(timezone.utc).isoformat(), "transferred_by": actor_id}
