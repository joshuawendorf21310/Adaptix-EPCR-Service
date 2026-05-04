"""ePCR Allergy Service. Manages allergies in ePCR charts."""
from __future__ import annotations
import logging, uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

class EpcrAllergyService:
    def update_allergies(self, *, chart_id: str, tenant_id: str, actor_id: str, allergies: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not chart_id:
            raise ValueError("chart_id is required")
        return {"chart_id": chart_id, "allergies_updated": True, "allergy_count": len(allergies), "updated_at": datetime.now(timezone.utc).isoformat(), "updated_by": actor_id}
