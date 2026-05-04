"""ePCR Medication Service. Manages medications administered in ePCR charts."""
from __future__ import annotations
import logging, uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
logger = logging.getLogger(__name__)

class EpcrMedicationService:
    def add_medication(self, *, chart_id: str, tenant_id: str, actor_id: str, medication_data: Dict[str, Any]) -> Dict[str, Any]:
        if not chart_id or not medication_data.get("medication_name"):
            raise ValueError("chart_id and medication_name are required")
        return {"medication_id": str(uuid.uuid4()), "chart_id": chart_id, "medication_data": medication_data, "recorded_at": datetime.now(timezone.utc).isoformat(), "recorded_by": actor_id}
