"""SentenceEvidenceService — AI-evidence-link pillar.

Wraps (but does not modify) :mod:`epcr_app.ai_narrative_service` to link
each sentence of an AI-generated ePCR narrative to a single piece of
structured chart evidence (field, vital, treatment, medication,
procedure, anatomical finding, prior chart/ECG, OCR snippet, map
waypoint, protocol, or provider note).

The linker is fully **deterministic** and pure-Python: it performs
token-overlap scoring against a structured workspace snapshot. It makes
**no LLM calls** and does not import any LLM client. The
``test_sentence_evidence_no_ai.py`` regression test enforces this rule
by inspecting this module's source for forbidden module-level imports.

Transaction boundaries are owned by the caller: this service never
calls ``session.commit()`` so multiple writes can be staged atomically
alongside other workspace section writes.

Public surface:

* :func:`SentenceEvidenceService.map_sentences` — returns proposed
  :class:`EpcrSentenceEvidence` rows (unpersisted) for a narrative.
* :func:`SentenceEvidenceService.persist` — writes rows + a single
  ``sentence.evidence_added`` audit event.
* :func:`SentenceEvidenceService.confirm` — flips ``provider_confirmed``
  and writes a ``sentence.evidence_added`` audit event with
  ``confirmed: true``.
* :func:`SentenceEvidenceService.unlink` — soft-clears an evidence link
  and writes a ``sentence.evidence_unlinked`` audit event.
* :func:`SentenceEvidenceService.list_for_chart` — read helper used by
  ``_load_workspace`` injection.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Iterable, Sequence
from uuid import uuid4

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models import EpcrAiAuditEvent, EpcrSentenceEvidence

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Canonical value sets
# ---------------------------------------------------------------------------

EVIDENCE_KINDS: frozenset[str] = frozenset(
    {
        "field",
        "vital",
        "treatment",
        "medication",
        "procedure",
        "anatomical_finding",
        "prior_chart",
        "prior_ecg",
        "ocr",
        "map",
        "protocol",
        "provider_note",
    }
)

EVENT_KINDS: frozenset[str] = frozenset(
    {
        "narrative.draft",
        "narrative.accepted",
        "narrative.rejected",
        "sentence.evidence_added",
        "sentence.evidence_unlinked",
        "phrase.inserted",
        "phrase.edited",
        "phrase.removed",
    }
)


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
# Stop-words kept tight: we lean on rich domain tokens (drug names,
# vitals values, anatomical labels) rather than fight English noise.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "the",
        "of",
        "to",
        "for",
        "with",
        "was",
        "were",
        "is",
        "in",
        "on",
        "at",
        "by",
        "patient",
        "pt",
    }
)


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceCandidate:
    """A single piece of structured evidence the linker can attach to.

    The ``tokens`` set is precomputed for cheap Jaccard-style scoring.
    """

    kind: str
    ref_id: str
    label: str
    tokens: frozenset[str]


@dataclass
class ProposedEvidence:
    """A proposed (not-yet-persisted) sentence -> evidence link."""

    sentence_index: int
    sentence_text: str
    evidence_kind: str
    evidence_ref_id: str | None
    confidence: Decimal
    matched_label: str | None = None


# ---------------------------------------------------------------------------
# Tokenisation helpers
# ---------------------------------------------------------------------------


def _tokenise(text: str | None) -> frozenset[str]:
    if not text:
        return frozenset()
    return frozenset(
        t.lower()
        for t in _TOKEN_RE.findall(text)
        if t.lower() not in _STOPWORDS and len(t) > 1
    )


def _split_sentences(narrative_text: str | None) -> list[str]:
    if not narrative_text:
        return []
    cleaned = narrative_text.strip()
    if not cleaned:
        return []
    parts = _SENTENCE_SPLIT_RE.split(cleaned)
    return [p.strip() for p in parts if p.strip()]


def _str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


# ---------------------------------------------------------------------------
# Candidate extraction
# ---------------------------------------------------------------------------


def _candidate_for_vital(row: Any) -> EvidenceCandidate:
    parts: list[str] = []
    if getattr(row, "bp_sys", None) is not None and getattr(row, "bp_dia", None) is not None:
        parts.append(f"bp {row.bp_sys}/{row.bp_dia}")
        parts.append("blood pressure")
    if getattr(row, "hr", None) is not None:
        parts.append(f"hr {row.hr}")
        parts.append("heart rate pulse")
    if getattr(row, "rr", None) is not None:
        parts.append(f"rr {row.rr}")
        parts.append("respiratory rate breathing")
    if getattr(row, "temp_f", None) is not None:
        parts.append(f"temp {row.temp_f}")
        parts.append("temperature")
    if getattr(row, "spo2", None) is not None:
        parts.append(f"spo2 {row.spo2}")
        parts.append("oxygen saturation")
    if getattr(row, "glucose", None) is not None:
        parts.append(f"glucose {row.glucose}")
        parts.append("blood sugar")
    label = " ".join(parts) or "vitals"
    return EvidenceCandidate(
        kind="vital",
        ref_id=_str(row.id),
        label=label,
        tokens=_tokenise(label),
    )


def _candidate_for_medication(row: Any) -> EvidenceCandidate:
    label_parts = [
        _str(getattr(row, "medication_name", None)),
        _str(getattr(row, "dose_value", None)),
        _str(getattr(row, "dose_unit", None)),
        _str(getattr(row, "route", None)),
        _str(getattr(row, "indication", None)),
    ]
    label = " ".join(p for p in label_parts if p)
    return EvidenceCandidate(
        kind="medication",
        ref_id=_str(row.id),
        label=label,
        tokens=_tokenise(label),
    )


def _candidate_for_anatomical(row: Any) -> EvidenceCandidate:
    label_parts = [
        _str(getattr(row, "region_label", None)),
        _str(getattr(row, "finding_type", None)),
        _str(getattr(row, "severity", None)),
        _str(getattr(row, "laterality", None)),
        _str(getattr(row, "notes", None)),
    ]
    label = " ".join(p for p in label_parts if p)
    return EvidenceCandidate(
        kind="anatomical_finding",
        ref_id=_str(row.id),
        label=label,
        tokens=_tokenise(label),
    )


def _candidate_for_field(name: str, value: Any) -> EvidenceCandidate:
    label = f"{name} {_str(value)}".strip()
    return EvidenceCandidate(
        kind="field",
        ref_id=name,
        label=label,
        tokens=_tokenise(label),
    )


def _candidate_for_treatment(row: Any) -> EvidenceCandidate:
    # Treatments / procedures / interventions vary by chart subsystem;
    # we accept any object with a ``name`` or ``procedure_name`` and an
    # ``id``.
    name = (
        _str(getattr(row, "name", None))
        or _str(getattr(row, "procedure_name", None))
        or _str(getattr(row, "intervention_name", None))
    )
    detail = _str(getattr(row, "detail", None)) or _str(
        getattr(row, "notes", None)
    )
    label = f"{name} {detail}".strip()
    kind = _str(getattr(row, "evidence_kind", None)) or "treatment"
    if kind not in EVIDENCE_KINDS:
        kind = "treatment"
    return EvidenceCandidate(
        kind=kind,
        ref_id=_str(row.id),
        label=label,
        tokens=_tokenise(label),
    )


def build_candidates(workspace: dict[str, Any]) -> list[EvidenceCandidate]:
    """Flatten a structured workspace snapshot into evidence candidates.

    ``workspace`` is the same dict shape used by
    :class:`ChartWorkspaceService`; unknown sections are ignored. Each
    candidate carries a precomputed token bag for the linker.
    """
    candidates: list[EvidenceCandidate] = []

    for row in workspace.get("vitals", []) or []:
        candidates.append(_candidate_for_vital(row))

    for row in workspace.get("medications", []) or []:
        candidates.append(_candidate_for_medication(row))

    for row in workspace.get("anatomical_findings", []) or []:
        candidates.append(_candidate_for_anatomical(row))

    for row in workspace.get("treatments", []) or []:
        candidates.append(_candidate_for_treatment(row))

    for row in workspace.get("procedures", []) or []:
        cand = _candidate_for_treatment(row)
        candidates.append(
            EvidenceCandidate(
                kind="procedure",
                ref_id=cand.ref_id,
                label=cand.label,
                tokens=cand.tokens,
            )
        )

    fields = workspace.get("fields", {}) or {}
    if isinstance(fields, dict):
        for name, value in fields.items():
            if value is None or value == "":
                continue
            candidates.append(_candidate_for_field(_str(name), value))

    return candidates


# ---------------------------------------------------------------------------
# Linker
# ---------------------------------------------------------------------------


def _score(sentence_tokens: frozenset[str], cand: EvidenceCandidate) -> float:
    """Token-overlap score in [0, 1].

    Uses a precision-weighted overlap so a candidate with a small but
    fully-covered token bag (e.g. a single drug name) ranks above a
    candidate that merely shares one common token with a noisy label.
    """
    if not sentence_tokens or not cand.tokens:
        return 0.0
    overlap = sentence_tokens & cand.tokens
    if not overlap:
        return 0.0
    coverage = len(overlap) / len(cand.tokens)
    recall = len(overlap) / len(sentence_tokens)
    # Geometric mean — rewards both sides being well-covered.
    return (coverage * recall) ** 0.5


def link_sentence(
    sentence: str,
    candidates: Sequence[EvidenceCandidate],
    *,
    min_confidence: float = 0.15,
) -> tuple[EvidenceCandidate | None, float]:
    """Return the best-scoring candidate for a sentence, or ``(None, 0.0)``.

    A confidence floor avoids spurious links on incidental token
    overlap. The caller decides whether to drop ``(None, 0.0)`` results.
    """
    sentence_tokens = _tokenise(sentence)
    if not sentence_tokens:
        return None, 0.0
    best: EvidenceCandidate | None = None
    best_score = 0.0
    for cand in candidates:
        s = _score(sentence_tokens, cand)
        if s > best_score:
            best = cand
            best_score = s
    if best_score < min_confidence:
        return None, 0.0
    return best, best_score


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class SentenceEvidenceServiceError(Exception):
    """Raised on invariant violations (unknown evidence_kind, missing row)."""


class SentenceEvidenceService:
    """Stateless service. All methods accept an ``AsyncSession``.

    The session is never committed by this service — the caller owns the
    transaction boundary.
    """

    # -- audit ----------------------------------------------------------

    @staticmethod
    def _audit(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        event_kind: str,
        user_id: str | None,
        payload: dict[str, Any] | None,
    ) -> EpcrAiAuditEvent:
        if event_kind not in EVENT_KINDS:
            raise SentenceEvidenceServiceError(
                f"unknown event_kind: {event_kind!r}"
            )
        row = EpcrAiAuditEvent(
            id=str(uuid4()),
            tenant_id=tenant_id,
            chart_id=chart_id,
            event_kind=event_kind,
            user_id=user_id,
            payload_json=json.dumps(payload, sort_keys=True, default=str)
            if payload is not None
            else None,
            performed_at=datetime.now(UTC),
        )
        session.add(row)
        return row

    # -- mapping --------------------------------------------------------

    @classmethod
    def map_sentences(
        cls,
        session: AsyncSession,  # noqa: ARG003 — kept for parity / future reads
        tenant_id: str,
        chart_id: str,
        *,
        narrative_id: str | None,
        narrative_text: str | None,
        workspace: dict[str, Any],
    ) -> list[EpcrSentenceEvidence]:
        """Produce (but do not persist) sentence-evidence rows.

        Wraps the output of :mod:`ai_narrative_service` (caller passes
        the already-generated ``narrative_text``; this service never
        invokes the AI itself). For each detected sentence we attempt
        a deterministic token-overlap match against the structured
        workspace. Sentences with no match are still emitted with
        ``evidence_kind="provider_note"`` and ``evidence_ref_id=None``
        so the UI can render an explicit "unlinked" badge — the
        provider can confirm or unlink either way.
        """
        candidates = build_candidates(workspace)
        sentences = _split_sentences(narrative_text)
        out: list[EpcrSentenceEvidence] = []
        now = datetime.now(UTC)
        for idx, sentence in enumerate(sentences):
            best, score = link_sentence(sentence, candidates)
            if best is None:
                kind = "provider_note"
                ref_id: str | None = None
                confidence = Decimal("0.00")
            else:
                kind = best.kind
                ref_id = best.ref_id
                # Clamp to the column scale (3,2): max 0.99.
                confidence = Decimal(f"{min(score, 0.99):.2f}")
            out.append(
                EpcrSentenceEvidence(
                    id=str(uuid4()),
                    tenant_id=tenant_id,
                    chart_id=chart_id,
                    narrative_id=narrative_id,
                    sentence_index=idx,
                    sentence_text=sentence,
                    evidence_kind=kind,
                    evidence_ref_id=ref_id,
                    confidence=confidence,
                    provider_confirmed=False,
                    created_at=now,
                    updated_at=now,
                )
            )
        return out

    # -- persistence ----------------------------------------------------

    @classmethod
    def persist(
        cls,
        session: AsyncSession,
        evidence_rows: Iterable[EpcrSentenceEvidence],
        *,
        user_id: str | None = None,
    ) -> list[EpcrSentenceEvidence]:
        """Persist proposed rows and emit a single audit event per chart.

        Caller is responsible for the surrounding ``await session.commit()``.
        """
        rows = list(evidence_rows)
        for row in rows:
            if row.evidence_kind not in EVIDENCE_KINDS:
                raise SentenceEvidenceServiceError(
                    f"unknown evidence_kind: {row.evidence_kind!r}"
                )
            session.add(row)

        # One audit event per (tenant, chart) batch keeps the audit log
        # legible; per-sentence detail lives in payload_json.
        grouped: dict[tuple[str, str], list[EpcrSentenceEvidence]] = {}
        for row in rows:
            grouped.setdefault((row.tenant_id, row.chart_id), []).append(row)
        for (tenant_id, chart_id), group in grouped.items():
            cls._audit(
                session,
                tenant_id=tenant_id,
                chart_id=chart_id,
                event_kind="sentence.evidence_added",
                user_id=user_id,
                payload={
                    "count": len(group),
                    "evidence_ids": [r.id for r in group],
                    "narrative_id": group[0].narrative_id,
                },
            )
        return rows

    # -- read helper ----------------------------------------------------

    @classmethod
    async def list_for_chart(
        cls,
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        *,
        narrative_id: str | None = None,
    ) -> list[EpcrSentenceEvidence]:
        """List evidence rows for a chart, optionally filtered by narrative."""
        stmt = select(EpcrSentenceEvidence).where(
            and_(
                EpcrSentenceEvidence.tenant_id == tenant_id,
                EpcrSentenceEvidence.chart_id == chart_id,
            )
        )
        if narrative_id is not None:
            stmt = stmt.where(EpcrSentenceEvidence.narrative_id == narrative_id)
        stmt = stmt.order_by(EpcrSentenceEvidence.sentence_index.asc())
        result = await session.execute(stmt)
        return list(result.scalars().all())

    # -- confirm / unlink ----------------------------------------------

    @classmethod
    async def _load_evidence(
        cls,
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        evidence_id: str,
    ) -> EpcrSentenceEvidence:
        stmt = select(EpcrSentenceEvidence).where(
            and_(
                EpcrSentenceEvidence.id == evidence_id,
                EpcrSentenceEvidence.tenant_id == tenant_id,
                EpcrSentenceEvidence.chart_id == chart_id,
            )
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise SentenceEvidenceServiceError(
                f"sentence_evidence {evidence_id!r} not found for chart {chart_id!r}"
            )
        return row

    @classmethod
    async def confirm(
        cls,
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        user_id: str,
        evidence_id: str,
    ) -> EpcrSentenceEvidence:
        """Mark a link as provider-confirmed and audit the action."""
        row = await cls._load_evidence(session, tenant_id, chart_id, evidence_id)
        row.provider_confirmed = True
        row.updated_at = datetime.now(UTC)
        cls._audit(
            session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            event_kind="sentence.evidence_added",
            user_id=user_id,
            payload={
                "confirmed": True,
                "evidence_id": evidence_id,
                "narrative_id": row.narrative_id,
                "sentence_index": row.sentence_index,
            },
        )
        return row

    @classmethod
    async def unlink(
        cls,
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        user_id: str,
        evidence_id: str,
    ) -> EpcrSentenceEvidence:
        """Soft-clear an evidence link and audit the action.

        The row is preserved (so the sentence still has a slot) but its
        ``evidence_kind`` is downgraded to ``provider_note`` and
        ``evidence_ref_id`` is cleared. ``provider_confirmed`` is reset
        because the link is no longer asserted.
        """
        row = await cls._load_evidence(session, tenant_id, chart_id, evidence_id)
        prior_kind = row.evidence_kind
        prior_ref = row.evidence_ref_id
        row.evidence_kind = "provider_note"
        row.evidence_ref_id = None
        row.provider_confirmed = False
        row.confidence = Decimal("0.00")
        row.updated_at = datetime.now(UTC)
        cls._audit(
            session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            event_kind="sentence.evidence_unlinked",
            user_id=user_id,
            payload={
                "evidence_id": evidence_id,
                "prior_kind": prior_kind,
                "prior_ref_id": prior_ref,
                "narrative_id": row.narrative_id,
                "sentence_index": row.sentence_index,
            },
        )
        return row
