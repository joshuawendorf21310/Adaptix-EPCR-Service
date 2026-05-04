"""ePCR Sync Conflict Service. Manages offline sync conflicts for Android ePCR charting."""
from __future__ import annotations
import logging, uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

class EpcrSyncConflictService:
    def detect_conflicts(self, *, chart_id: str, tenant_id: str, local_version: int, server_version: int) -> Dict[str, Any]:
        has_conflict = local_version != server_version
        return {"chart_id": chart_id, "has_conflict": has_conflict, "local_version": local_version, "server_version": server_version, "resolution_required": has_conflict, "checked_at": datetime.now(timezone.utc).isoformat()}

    def resolve_conflict(self, *, chart_id: str, tenant_id: str, actor_id: str, resolution: str, reason: str) -> Dict[str, Any]:
        if not resolution or not reason:
            raise ValueError("resolution and reason are required")
        return {"resolution_id": str(uuid.uuid4()), "chart_id": chart_id, "resolution": resolution, "reason": reason, "resolved_at": datetime.now(timezone.utc).isoformat(), "resolved_by": actor_id}
