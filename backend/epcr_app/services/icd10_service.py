"""ICD-10 documentation **specificity prompt** service.

This module is the canonical home of the Adaptix ePCR ICD-10
*documentation specificity* pillar. It is intentionally narrow in scope:

- It reads the chief complaint and field/clinical assessment notes for a
  chart.
- It runs deterministic keyword heuristics (no LLM, no network) to
  derive a list of documentation **prompts** -- questions the clinician
  should answer to improve chart specificity (laterality, mechanism,
  encounter context, symptom vs. diagnosis, anatomical region,
  general specificity).
- It optionally surfaces *candidate* ICD-10 codes alongside each prompt
  as informational hints. These are never persisted as the patient's
  diagnosis.

What this service **must never do**:

- Bind, attach, or otherwise persist any ICD-10 code to the chart's
  diagnosis fields on behalf of the provider.
- Do not use the words ``auto-assign``, ``auto-select``, or ``diagnose``
  in any way that would imply the system reaches a clinical conclusion.

The clinician is the only authority that can adopt a candidate code,
and they do so via :func:`acknowledge`, which records the explicit
selection (or rejection, when ``selected_code_or_null`` is ``None``).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any, Iterable, Sequence
from uuid import uuid4

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models import (
    Assessment,
    EpcrAuditLog,
    EpcrIcd10DocumentationSuggestion,
)


# ---------------------------------------------------------------------------
# Canonical prompt-kind vocabulary.
#
# Keep this small and stable -- it is part of the contract surfaced to
# the frontend (src/lib/epcr-clinical.ts) and to the coordinator.
# ---------------------------------------------------------------------------
PROMPT_KIND_LATERALITY = "laterality"
PROMPT_KIND_BODY_REGION = "body_region"
PROMPT_KIND_ENCOUNTER_CONTEXT = "encounter_context"
PROMPT_KIND_MECHANISM = "mechanism"
PROMPT_KIND_SPECIFICITY = "specificity"
PROMPT_KIND_SYMPTOM_VS_DIAGNOSIS = "symptom_vs_diagnosis"

VALID_PROMPT_KINDS = frozenset(
    {
        PROMPT_KIND_LATERALITY,
        PROMPT_KIND_BODY_REGION,
        PROMPT_KIND_ENCOUNTER_CONTEXT,
        PROMPT_KIND_MECHANISM,
        PROMPT_KIND_SPECIFICITY,
        PROMPT_KIND_SYMPTOM_VS_DIAGNOSIS,
    }
)


# ---------------------------------------------------------------------------
# Keyword matchers
# ---------------------------------------------------------------------------
_LATERALITY_WORDS = re.compile(
    r"\b(left|right|bilateral|midline|unilateral)\b", re.IGNORECASE
)
_FALL_WORDS = re.compile(r"\bfall(?:s|en|ing)?\b", re.IGNORECASE)
_MVC_WORDS = re.compile(
    r"\b(mvc|mva|motor\s*vehicle(?:\s*(?:crash|accident|collision))?)\b",
    re.IGNORECASE,
)
_CHEST_PAIN_WORDS = re.compile(r"\bchest\s*pain\b", re.IGNORECASE)
_PAIN_WORDS = re.compile(r"\bpain\b", re.IGNORECASE)
_ABDO_WORDS = re.compile(r"\b(abdo(?:men|minal)?|belly|stomach)\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Prompt construction helpers
# ---------------------------------------------------------------------------
def _candidate(code: str, description: str) -> dict[str, str]:
    return {"code": code, "description": description}


def _build_suggestion(
    *,
    tenant_id: str,
    chart_id: str,
    complaint_text: str | None,
    prompt_kind: str,
    prompt_text: str,
    candidate_codes: Sequence[dict[str, str]] | None,
) -> EpcrIcd10DocumentationSuggestion:
    """Build (do NOT persist) one suggestion row.

    The returned object is detached -- the caller decides whether to
    persist it via :func:`persist_prompts`. We never set
    ``provider_selected_code`` here; the provider alone may set it via
    :func:`acknowledge`.
    """
    if prompt_kind not in VALID_PROMPT_KINDS:
        raise ValueError(f"unknown prompt_kind: {prompt_kind!r}")
    now = datetime.now(UTC)
    return EpcrIcd10DocumentationSuggestion(
        id=str(uuid4()),
        tenant_id=tenant_id,
        chart_id=chart_id,
        complaint_text=complaint_text,
        prompt_kind=prompt_kind,
        prompt_text=prompt_text,
        candidate_codes_json=(
            json.dumps(list(candidate_codes)) if candidate_codes else None
        ),
        provider_acknowledged=False,
        provider_selected_code=None,  # provider chooses; service does not
        provider_selected_at=None,
        created_at=now,
        updated_at=now,
    )


def _has_laterality(text: str) -> bool:
    return bool(_LATERALITY_WORDS.search(text))


# ---------------------------------------------------------------------------
# Heuristic prompt generation
# ---------------------------------------------------------------------------
async def generate_prompts_for_chart(
    session: AsyncSession,
    tenant_id: str,
    chart_id: str,
) -> list[EpcrIcd10DocumentationSuggestion]:
    """Generate (but do **not** persist) documentation prompts for a chart.

    Reads the chief complaint and assessment findings, then applies a
    fixed set of keyword heuristics. The returned objects carry only
    candidate codes for the clinician's reference -- never a
    ``provider_selected_code``.
    """
    assessment = (
        await session.execute(
            select(Assessment).where(
                and_(
                    Assessment.chart_id == chart_id,
                    Assessment.tenant_id == tenant_id,
                )
            )
        )
    ).scalar_one_or_none()

    chief_complaint = (assessment.chief_complaint if assessment else None) or ""
    field_diagnosis = (assessment.field_diagnosis if assessment else None) or ""
    impression_notes = (assessment.impression_notes if assessment else None) or ""
    haystack = " ".join([chief_complaint, field_diagnosis, impression_notes])
    complaint_text = chief_complaint or None

    return _apply_heuristics(
        tenant_id=tenant_id,
        chart_id=chart_id,
        complaint_text=complaint_text,
        haystack=haystack,
    )


def _apply_heuristics(
    *,
    tenant_id: str,
    chart_id: str,
    complaint_text: str | None,
    haystack: str,
) -> list[EpcrIcd10DocumentationSuggestion]:
    """Pure, side-effect-free heuristic application.

    Split out so unit tests can exercise the rule matrix without a DB.
    """
    suggestions: list[EpcrIcd10DocumentationSuggestion] = []
    text = haystack or ""

    chest_pain = bool(_CHEST_PAIN_WORDS.search(text))
    has_pain = bool(_PAIN_WORDS.search(text))
    has_fall = bool(_FALL_WORDS.search(text))
    has_mvc = bool(_MVC_WORDS.search(text))
    has_abdo = bool(_ABDO_WORDS.search(text))
    has_laterality = _has_laterality(text)

    # Chest pain -> specificity + symptom_vs_diagnosis.
    if chest_pain:
        suggestions.append(
            _build_suggestion(
                tenant_id=tenant_id,
                chart_id=chart_id,
                complaint_text=complaint_text,
                prompt_kind=PROMPT_KIND_SPECIFICITY,
                prompt_text=(
                    "Chest pain is documented. Please clarify quality "
                    "(pressure, sharp, pleuritic), radiation, onset, and "
                    "associated symptoms to support a more specific impression."
                ),
                candidate_codes=[
                    _candidate("R07.9", "Chest pain, unspecified"),
                    _candidate("R07.89", "Other chest pain"),
                    _candidate("R07.2", "Precordial pain"),
                ],
            )
        )
        suggestions.append(
            _build_suggestion(
                tenant_id=tenant_id,
                chart_id=chart_id,
                complaint_text=complaint_text,
                prompt_kind=PROMPT_KIND_SYMPTOM_VS_DIAGNOSIS,
                prompt_text=(
                    "Document whether 'chest pain' is a symptom on "
                    "presentation or a working impression (e.g. ACS, "
                    "musculoskeletal). The clinician selects -- this "
                    "service only prompts."
                ),
                candidate_codes=[
                    _candidate("R07.9", "Chest pain, unspecified (symptom)"),
                    _candidate(
                        "I20.9", "Angina pectoris, unspecified (impression)"
                    ),
                ],
            )
        )

    # Generic 'pain' without laterality -> laterality prompt
    if has_pain and not has_laterality:
        suggestions.append(
            _build_suggestion(
                tenant_id=tenant_id,
                chart_id=chart_id,
                complaint_text=complaint_text,
                prompt_kind=PROMPT_KIND_LATERALITY,
                prompt_text=(
                    "Pain is documented without laterality. Please record "
                    "left, right, bilateral, or midline."
                ),
                candidate_codes=None,
            )
        )

    # Fall -> mechanism prompt
    if has_fall:
        suggestions.append(
            _build_suggestion(
                tenant_id=tenant_id,
                chart_id=chart_id,
                complaint_text=complaint_text,
                prompt_kind=PROMPT_KIND_MECHANISM,
                prompt_text=(
                    "Fall mechanism noted. Please record height, surface, "
                    "loss of consciousness, and whether the fall was "
                    "witnessed."
                ),
                candidate_codes=[
                    _candidate("W19.XXXA", "Unspecified fall, initial encounter"),
                    _candidate(
                        "W18.30XA",
                        "Fall on same level, unspecified, initial encounter",
                    ),
                ],
            )
        )

    # MVC -> mechanism + encounter context prompts
    if has_mvc:
        suggestions.append(
            _build_suggestion(
                tenant_id=tenant_id,
                chart_id=chart_id,
                complaint_text=complaint_text,
                prompt_kind=PROMPT_KIND_MECHANISM,
                prompt_text=(
                    "Motor vehicle crash noted. Please record speed, "
                    "occupant position, restraint use, airbag deployment, "
                    "and intrusion."
                ),
                candidate_codes=[
                    _candidate(
                        "V49.9XXA",
                        "Car occupant injured in unspecified traffic accident, initial encounter",
                    ),
                ],
            )
        )
        suggestions.append(
            _build_suggestion(
                tenant_id=tenant_id,
                chart_id=chart_id,
                complaint_text=complaint_text,
                prompt_kind=PROMPT_KIND_ENCOUNTER_CONTEXT,
                prompt_text=(
                    "Document the encounter context (initial, subsequent, "
                    "sequela) for the MVC-related injury so the 7th "
                    "character can be coded correctly."
                ),
                candidate_codes=None,
            )
        )

    # Abdominal complaint -> body_region prompt
    if has_abdo:
        suggestions.append(
            _build_suggestion(
                tenant_id=tenant_id,
                chart_id=chart_id,
                complaint_text=complaint_text,
                prompt_kind=PROMPT_KIND_BODY_REGION,
                prompt_text=(
                    "Abdominal complaint noted. Please record the affected "
                    "quadrant (RUQ, LUQ, RLQ, LLQ, periumbilical, "
                    "generalized)."
                ),
                candidate_codes=[
                    _candidate("R10.9", "Unspecified abdominal pain"),
                    _candidate("R10.84", "Generalized abdominal pain"),
                ],
            )
        )

    return suggestions


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
async def persist_prompts(
    session: AsyncSession,
    prompts: Iterable[EpcrIcd10DocumentationSuggestion],
    *,
    user_id: str | None = None,
) -> list[EpcrIcd10DocumentationSuggestion]:
    """Persist prompts and emit a single ``icd10.prompts_generated`` audit row.

    Caller owns the transaction; we ``flush()`` so generated IDs are
    available but never ``commit()``.
    """
    persisted: list[EpcrIcd10DocumentationSuggestion] = []
    for prompt in prompts:
        # Defensive: the service contract requires that we never set
        # provider_selected_code here. Reject any caller that tried.
        if prompt.provider_selected_code is not None:
            raise ValueError(
                "persist_prompts() refuses rows with provider_selected_code set; "
                "use acknowledge() to record provider selection"
            )
        session.add(prompt)
        persisted.append(prompt)

    if persisted:
        first = persisted[0]
        _audit(
            session,
            tenant_id=first.tenant_id,
            chart_id=first.chart_id,
            user_id=user_id,
            action="icd10.prompts_generated",
            detail={
                "count": len(persisted),
                "prompt_kinds": [p.prompt_kind for p in persisted],
                "suggestion_ids": [p.id for p in persisted],
            },
        )
    await session.flush()
    return persisted


# ---------------------------------------------------------------------------
# Acknowledgement
# ---------------------------------------------------------------------------
async def acknowledge(
    session: AsyncSession,
    tenant_id: str,
    chart_id: str,
    user_id: str,
    suggestion_id: str,
    selected_code_or_null: str | None,
) -> EpcrIcd10DocumentationSuggestion:
    """Record the clinician's explicit response to a prompt.

    ``selected_code_or_null`` semantics:

    - ``None`` -> provider acknowledged the prompt but rejected the
      candidate(s). No code is bound; the chart is unchanged.
    - non-empty string -> provider explicitly chose this code as the
      response to the prompt. The chart's diagnosis fields are still NOT
      touched by this service; binding the chosen code to the chart is
      the clinician's separate explicit action via the chart workspace.
    """
    row = (
        await session.execute(
            select(EpcrIcd10DocumentationSuggestion).where(
                and_(
                    EpcrIcd10DocumentationSuggestion.id == suggestion_id,
                    EpcrIcd10DocumentationSuggestion.tenant_id == tenant_id,
                    EpcrIcd10DocumentationSuggestion.chart_id == chart_id,
                )
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise LookupError(
            f"icd10 suggestion {suggestion_id!r} not found for chart"
        )

    now = datetime.now(UTC)
    row.provider_acknowledged = True
    row.provider_selected_code = selected_code_or_null
    row.provider_selected_at = now
    row.updated_at = now

    _audit(
        session,
        tenant_id=tenant_id,
        chart_id=chart_id,
        user_id=user_id,
        action="icd10.acknowledged",
        detail={
            "suggestion_id": suggestion_id,
            "prompt_kind": row.prompt_kind,
            "selected_code": selected_code_or_null,  # may be None -> rejection
        },
    )
    await session.flush()
    return row


# ---------------------------------------------------------------------------
# Specificity score
# ---------------------------------------------------------------------------
def specificity_score(
    suggestions_for_chart: Sequence[EpcrIcd10DocumentationSuggestion],
) -> float:
    """Return the fraction of suggestions the clinician has acknowledged.

    Returns ``0.0`` when the input is empty.
    """
    if not suggestions_for_chart:
        return 0.0
    ack = sum(1 for s in suggestions_for_chart if s.provider_acknowledged)
    return ack / float(len(suggestions_for_chart))


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------
async def list_for_chart(
    session: AsyncSession, tenant_id: str, chart_id: str
) -> list[EpcrIcd10DocumentationSuggestion]:
    rows = (
        await session.execute(
            select(EpcrIcd10DocumentationSuggestion)
            .where(
                and_(
                    EpcrIcd10DocumentationSuggestion.tenant_id == tenant_id,
                    EpcrIcd10DocumentationSuggestion.chart_id == chart_id,
                )
            )
            .order_by(
                EpcrIcd10DocumentationSuggestion.created_at,
                EpcrIcd10DocumentationSuggestion.id,
            )
        )
    ).scalars().all()
    return list(rows)


def serialize(row: EpcrIcd10DocumentationSuggestion) -> dict[str, Any]:
    """Serialize a row to the camelCase contract shared with the frontend."""
    return {
        "id": row.id,
        "chartId": row.chart_id,
        "complaintText": row.complaint_text,
        "promptKind": row.prompt_kind,
        "promptText": row.prompt_text,
        "candidateCodes": (
            json.loads(row.candidate_codes_json)
            if row.candidate_codes_json
            else []
        ),
        "providerAcknowledged": bool(row.provider_acknowledged),
        "providerSelectedCode": row.provider_selected_code,
        "providerSelectedAt": (
            row.provider_selected_at.isoformat()
            if row.provider_selected_at
            else None
        ),
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
    }


# ---------------------------------------------------------------------------
# Audit helper (local copy: keeps the service self-contained)
# ---------------------------------------------------------------------------
def _audit(
    session: AsyncSession,
    *,
    tenant_id: str,
    chart_id: str,
    user_id: str | None,
    action: str,
    detail: dict[str, Any],
) -> None:
    entry = EpcrAuditLog(
        id=str(uuid4()),
        chart_id=chart_id,
        tenant_id=tenant_id,
        user_id=user_id or "system",
        action=action,
        detail_json=json.dumps(detail, default=str),
        performed_at=datetime.now(UTC),
    )
    session.add(entry)


__all__ = [
    "PROMPT_KIND_LATERALITY",
    "PROMPT_KIND_BODY_REGION",
    "PROMPT_KIND_ENCOUNTER_CONTEXT",
    "PROMPT_KIND_MECHANISM",
    "PROMPT_KIND_SPECIFICITY",
    "PROMPT_KIND_SYMPTOM_VS_DIAGNOSIS",
    "VALID_PROMPT_KINDS",
    "generate_prompts_for_chart",
    "persist_prompts",
    "acknowledge",
    "specificity_score",
    "list_for_chart",
    "serialize",
]
