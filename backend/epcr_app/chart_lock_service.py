"""ePCR Chart Lock Service. Manages chart lock/unlock/amendment lifecycle."""
from __future__ import annotations
import logging, uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
logger = logging.getLogger(__name__)

class ChartLockService:
    def lock_chart(self, *, chart_id: str, tenant_id: str, actor_id: str) -> Dict[str, Any]:
        if not chart_id:
            raise ValueError("chart_id is required")
        return {"chart_id": chart_id, "status": "locked", "locked_at": datetime.now(timezone.utc).isoformat(), "locked_by": actor_id}

    def unlock_chart(self, *, chart_id: str, tenant_id: str, actor_id: str, reason: str) -> Dict[str, Any]:
        if not chart_id or not reason:
            raise ValueError("chart_id and reason are required")
        return {"chart_id": chart_id, "status": "unlocked", "unlock_reason": reason, "unlocked_at": datetime.now(timezone.utc).isoformat(), "unlocked_by": actor_id}
