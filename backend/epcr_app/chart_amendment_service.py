"""ePCR Chart Amendment Service. Manages chart amendments with audit trail."""
from __future__ import annotations
import logging, uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
logger = logging.getLogger(__name__)

class ChartAmendmentService:
    def create_amendment(self, *, chart_id: str, tenant_id: str, actor_id: str, field: str, old_value: Any, new_value: Any, reason: str) -> Dict[str, Any]:
        if not chart_id or not field or not reason:
            raise ValueError("chart_id, field, and reason are required")
        return {"amendment_id": str(uuid.uuid4()), "chart_id": chart_id, "field": field, "old_value": old_value, "new_value": new_value, "reason": reason, "amended_at": datetime.now(timezone.utc).isoformat(), "amended_by": actor_id}
