"""ePCR Signature Service. Manages signatures in ePCR charts. ePCR owns signature workflow."""
from __future__ import annotations
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
logger = logging.getLogger(__name__)

class EpcrSignatureService:
    def capture_signature(self, *, chart_id: str, tenant_id: str, actor_id: str, signature_type: str, signer_name: str, signature_data: Optional[str] = None) -> Dict[str, Any]:
        if not chart_id or not signature_type or not signer_name:
            raise ValueError("chart_id, signature_type, and signer_name are required")
        return {"signature_id": str(uuid.uuid4()), "chart_id": chart_id, "signature_type": signature_type, "signer_name": signer_name, "captured_at": datetime.now(timezone.utc).isoformat(), "captured_by": actor_id}
