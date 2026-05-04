"""ePCR Procedure Service. Manages procedures performed in ePCR charts."""
from __future__ import annotations
import logging, uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
logger = logging.getLogger(__name__)

class EpcrProcedureService:
    def add_procedure(self, *, chart_id: str, tenant_id: str, actor_id: str, procedure_data: Dict[str, Any]) -> Dict[str, Any]:
        if not chart_id or not procedure_data.get("procedure_type"):
            raise ValueError("chart_id and procedure_type are required")
        return {"procedure_id": str(uuid.uuid4()), "chart_id": chart_id, "procedure_data": procedure_data, "recorded_at": datetime.now(timezone.utc).isoformat(), "recorded_by": actor_id}
