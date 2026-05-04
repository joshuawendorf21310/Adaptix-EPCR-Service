"""ePCR Refusal Service. Manages patient refusal documentation in ePCR charts."""
from __future__ import annotations
import logging, uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
logger = logging.getLogger(__name__)

class EpcrRefusalService:
    def document_refusal(self, *, chart_id: str, tenant_id: str, actor_id: str, refusal_data: Dict[str, Any]) -> Dict[str, Any]:
        if not chart_id or not refusal_data.get("refusal_type"):
            raise ValueError("chart_id and refusal_type are required")
        return {"refusal_id": str(uuid.uuid4()), "chart_id": chart_id, "refusal_data": refusal_data, "documented_at": datetime.now(timezone.utc).isoformat(), "documented_by": actor_id}
