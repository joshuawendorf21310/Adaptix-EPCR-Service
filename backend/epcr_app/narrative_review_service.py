from __future__ import annotations
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid

logger = logging.getLogger(__name__)


class NarrativeReviewAction(str, Enum):
    GENERATED = 'generated'
    ACCEPTED = 'accepted'
    EDITED = 'edited'
    REJECTED = 'rejected'
    REGENERATED = 'regenerated'


@dataclass
class NarrativeReviewRecord:
    review_id: str
    chart_id: str
    generation_id: str
    tenant_id: str
    actor_id: str
    action: NarrativeReviewAction
    original_text: Optional[str]
    final_text: Optional[str]
    edit_summary: Optional[str]
    occurred_at: datetime
    phi_logged: bool = False
    prompt_logged: bool = False
    completion_logged: bool = False
    chart_auto_locked: bool = False


class NarrativeReviewService:
    def record_action(self, chart_id, generation_id, tenant_id, actor_id, action, original_text=None, final_text=None, edit_summary=None):
        return NarrativeReviewRecord(
            review_id=str(uuid.uuid4()),
            chart_id=chart_id,
            generation_id=generation_id,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action=action,
            original_text=original_text,
            final_text=final_text,
            edit_summary=edit_summary,
            occurred_at=datetime.now(timezone.utc),
            phi_logged=False,
            prompt_logged=False,
            completion_logged=False,
            chart_auto_locked=False,
        )
