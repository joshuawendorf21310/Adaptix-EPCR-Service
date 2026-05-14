"""ePCR Intervention Service. Manages interventions in ePCR charts."""
from __future__ import annotations
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict
logger = logging.getLogger(__name__)

class EpcrInterventionService:
    def add_intervention(self, *, chart_id: str, tenant_id: str, actor_id: str, intervention_data: Dict[str, Any]) -> Dict[str, Any]:
        if not chart_id:
            raise ValueError("chart_id is required")
        return {"intervention_id": str(uuid.uuid4()), "chart_id": chart_id, "intervention_data": intervention_data, "recorded_at": datetime.now(timezone.utc).isoformat(), "recorded_by": actor_id}
