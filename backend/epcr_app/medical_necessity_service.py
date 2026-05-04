"""ePCR Medical Necessity Service. Validates medical necessity for ePCR billing readiness. Human review required."""
from __future__ import annotations
import logging, uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

class EpcrMedicalNecessityService:
    def assess(self, *, chart_id: str, tenant_id: str, actor_id: str, chart_data: Dict[str, Any]) -> Dict[str, Any]:
        if not chart_id:
            raise ValueError("chart_id is required")
        missing = []
        if not chart_data.get("chief_complaint"):
            missing.append("chief_complaint")
        if not chart_data.get("transport_reason"):
            missing.append("transport_reason")
        return {"assessment_id": str(uuid.uuid4()), "chart_id": chart_id, "qualifies": len(missing) == 0, "missing_fields": missing, "human_review_required": True, "assessed_at": datetime.now(timezone.utc).isoformat()}
