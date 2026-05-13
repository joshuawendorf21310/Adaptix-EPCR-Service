"""Service for the RepeatPatientService pillar.

Owns repeat-patient match discovery, the provider review workflow, prior
chart listing, and the carry-forward operation that copies values from a
matched profile onto the active chart's :class:`PatientProfile`.

Hard rule: carry-forward NEVER overwrites a value on the active chart
without an explicit, reviewed match whose ``carry_forward_allowed`` flag
has been set to ``True`` by a provider. Calling
:meth:`RepeatPatientService.carry_forward` on an un-reviewed match raises
:class:`RepeatPatientReviewRequiredError`.

This module never calls ``session.commit()``; the caller (typically the
chart workspace endpoint) is responsible for transaction boundaries.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models import (
    Chart,
    EpcrAuditLog,
    EpcrPriorChartReference,
    EpcrRepeatPatientMatch,
    PatientProfile,
)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------- #


class RepeatPatientError(Exception):
    """Base error for the RepeatPatientService."""


class RepeatPatientReviewRequiredError(RepeatPatientError):
    """Raised when carry_forward is invoked on a match that has not been
    explicitly reviewed and approved by a provider."""


class RepeatPatientMatchNotFoundError(RepeatPatientError):
    """Raised when a referenced match id does not exist for the tenant/chart."""


# --------------------------------------------------------------------- #
# Confidence math
# --------------------------------------------------------------------- #


# Field weights for the match confidence score. Weights sum to 1.00 so
# the resulting confidence is always in [0, 1]; the DB CHECK constraint
# enforces the same invariant.
_FIELD_WEIGHTS: dict[str, float] = {
    "date_of_birth": 0.45,
    "last_name": 0.35,
    "phone_last4": 0.20,
}


def _phone_last4(phone: str | None) -> str | None:
    if not phone:
        return None
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) < 4:
        return None
    return digits[-4:]


def _norm(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().lower()
    return cleaned or None


@dataclass(frozen=True)
class _MatchScore:
    confidence: Decimal
    reasons: list[dict[str, Any]]


def _score(current: dict[str, Any], candidate: PatientProfile) -> _MatchScore:
    reasons: list[dict[str, Any]] = []
    score = 0.0

    cur_dob = _norm(current.get("date_of_birth"))
    cand_dob = _norm(candidate.date_of_birth)
    if cur_dob and cand_dob and cur_dob == cand_dob:
        score += _FIELD_WEIGHTS["date_of_birth"]
        reasons.append({"field": "date_of_birth", "equality": "exact"})

    cur_last = _norm(current.get("last_name"))
    cand_last = _norm(candidate.last_name)
    if cur_last and cand_last and cur_last == cand_last:
        score += _FIELD_WEIGHTS["last_name"]
        reasons.append({"field": "last_name", "equality": "case_insensitive"})

    cur_tail = _phone_last4(current.get("phone_number"))
    cand_tail = _phone_last4(candidate.phone_number)
    if cur_tail and cand_tail and cur_tail == cand_tail:
        score += _FIELD_WEIGHTS["phone_last4"]
        reasons.append({"field": "phone_last4", "equality": "exact"})

    # Quantize to numeric(3,2) range.
    quantized = Decimal(f"{score:.2f}")
    if quantized > Decimal("1.00"):
        quantized = Decimal("1.00")
    if quantized < Decimal("0.00"):
        quantized = Decimal("0.00")
    return _MatchScore(confidence=quantized, reasons=reasons)


# --------------------------------------------------------------------- #
# Carry-forward field map
# --------------------------------------------------------------------- #


# Active-chart PatientProfile field set that may be populated from a
# reviewed match. Names are the snake_case ORM attributes on
# :class:`PatientProfile`.
_CARRY_FORWARD_FIELDS: frozenset[str] = frozenset(
    {
        "first_name",
        "middle_name",
        "last_name",
        "date_of_birth",
        "age_years",
        "sex",
        "phone_number",
        "weight_kg",
        "allergies_json",
    }
)


# --------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------- #


class RepeatPatientService:
    """Static service for repeat-patient discovery and provider workflow."""

    # ----------------------------- audit ----------------------------- #

    @staticmethod
    def _audit(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        user_id: str,
        action: str,
        detail: dict[str, Any],
        performed_at: datetime,
    ) -> None:
        entry = EpcrAuditLog(
            id=str(uuid4()),
            chart_id=chart_id,
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            detail_json=json.dumps(detail, default=str),
            performed_at=performed_at,
        )
        session.add(entry)

    # -------------------------- find matches ------------------------- #

    @staticmethod
    async def find_matches(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        current_patient: dict[str, Any],
    ) -> list[EpcrRepeatPatientMatch]:
        """Discover candidate matches by DOB + last name + phone tail.

        Strategy:
        - Fetch tenant-scoped :class:`PatientProfile` rows excluding the
          active chart's own profile.
        - Score each candidate via :func:`_score`. Persist rows whose
          confidence is strictly greater than 0 (i.e. at least one field
          matched).
        - Additionally write :class:`EpcrPriorChartReference` snapshots
          for each unique matched chart.

        Returns the freshly-persisted match rows in descending confidence
        order.
        """
        if not isinstance(current_patient, dict):
            raise TypeError("current_patient must be a dict")

        # Pull tenant-scoped candidate profiles. We exclude the active
        # chart's own profile by chart_id.
        candidates_rows = (
            await session.execute(
                select(PatientProfile).where(
                    and_(
                        PatientProfile.tenant_id == tenant_id,
                        PatientProfile.chart_id != chart_id,
                        PatientProfile.deleted_at.is_(None),
                    )
                )
            )
        ).scalars().all()

        now = datetime.now(UTC)
        persisted: list[EpcrRepeatPatientMatch] = []
        seen_chart_ids: set[str] = set()

        for candidate in candidates_rows:
            scored = _score(current_patient, candidate)
            if scored.confidence <= Decimal("0.00"):
                continue
            match = EpcrRepeatPatientMatch(
                id=str(uuid4()),
                tenant_id=tenant_id,
                chart_id=chart_id,
                matched_profile_id=candidate.id,
                confidence=scored.confidence,
                match_reason_json=json.dumps(scored.reasons),
                reviewed=False,
                carry_forward_allowed=False,
                created_at=now,
                updated_at=now,
            )
            session.add(match)
            persisted.append(match)

            # Record a prior chart reference for the matched chart so
            # the UI can render disposition + chief complaint quickly.
            if candidate.chart_id and candidate.chart_id not in seen_chart_ids:
                seen_chart_ids.add(candidate.chart_id)
                prior_chart = (
                    await session.execute(
                        select(Chart).where(Chart.id == candidate.chart_id)
                    )
                ).scalar_one_or_none()
                ref = EpcrPriorChartReference(
                    id=str(uuid4()),
                    tenant_id=tenant_id,
                    chart_id=chart_id,
                    prior_chart_id=candidate.chart_id,
                    encounter_at=getattr(prior_chart, "created_at", None)
                    if prior_chart is not None
                    else None,
                    chief_complaint=getattr(
                        prior_chart, "chief_complaint", None
                    )
                    if prior_chart is not None
                    else None,
                    disposition=getattr(prior_chart, "disposition", None)
                    if prior_chart is not None
                    else None,
                    created_at=now,
                )
                session.add(ref)

        await session.flush()

        # Stable order: highest confidence first, then by id.
        persisted.sort(key=lambda m: (-float(m.confidence), m.id))
        return persisted

    # ----------------------------- review ---------------------------- #

    @staticmethod
    async def review(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        user_id: str,
        match_id: str,
        carry_forward_allowed: bool,
    ) -> EpcrRepeatPatientMatch:
        """Record provider review of a candidate match.

        Transitions ``reviewed`` -> ``True`` and stamps
        ``reviewed_by`` / ``reviewed_at``. The provider's explicit
        ``carry_forward_allowed`` flag controls whether a subsequent
        :meth:`carry_forward` call may run.
        """
        row = await RepeatPatientService._load_match(
            session, tenant_id, chart_id, match_id
        )
        now = datetime.now(UTC)
        before = {
            "reviewed": bool(row.reviewed),
            "carry_forward_allowed": bool(row.carry_forward_allowed),
        }
        row.reviewed = True
        row.reviewed_by = user_id
        row.reviewed_at = now
        row.carry_forward_allowed = bool(carry_forward_allowed)
        row.updated_at = now

        RepeatPatientService._audit(
            session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            user_id=user_id,
            action="repeat_patient.reviewed",
            detail={
                "match_id": match_id,
                "before": before,
                "after": {
                    "reviewed": True,
                    "carry_forward_allowed": bool(carry_forward_allowed),
                },
            },
            performed_at=now,
        )
        await session.flush()
        return row

    # ------------------------ list prior charts ---------------------- #

    @staticmethod
    async def list_prior_charts(
        session: AsyncSession,
        tenant_id: str,
        matched_profile_id: str,
    ) -> list[EpcrPriorChartReference]:
        """Return prior chart references for the patient profile.

        Looks up the matched profile's home chart, then returns every
        :class:`EpcrPriorChartReference` row (tenant-scoped) whose
        ``prior_chart_id`` matches that chart. This gives the caller the
        snapshot rows describing the chart that produced this profile.
        """
        profile = (
            await session.execute(
                select(PatientProfile).where(
                    and_(
                        PatientProfile.tenant_id == tenant_id,
                        PatientProfile.id == matched_profile_id,
                    )
                )
            )
        ).scalar_one_or_none()
        if profile is None:
            return []

        rows = (
            await session.execute(
                select(EpcrPriorChartReference)
                .where(
                    and_(
                        EpcrPriorChartReference.tenant_id == tenant_id,
                        EpcrPriorChartReference.prior_chart_id
                        == profile.chart_id,
                    )
                )
                .order_by(
                    EpcrPriorChartReference.encounter_at.desc(),
                    EpcrPriorChartReference.id,
                )
            )
        ).scalars().all()
        return list(rows)

    # ------------------------- carry forward ------------------------- #

    @staticmethod
    async def carry_forward(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        user_id: str,
        source_field: str,
        target_field: str,
        *,
        match_id: str | None = None,
    ) -> dict[str, Any]:
        """Copy ``source_field`` from a reviewed match onto the active chart.

        Provider confirmation is REQUIRED: the match referenced by
        ``match_id`` (or, if omitted, the single match for this chart)
        must have ``reviewed=True`` AND ``carry_forward_allowed=True``.
        Any other state raises :class:`RepeatPatientReviewRequiredError`
        and mutates nothing.

        Args:
            source_field: ORM attribute on the matched
                :class:`PatientProfile` to read.
            target_field: ORM attribute on the active chart's
                :class:`PatientProfile` to write.
            match_id: Specific match to apply. If omitted, there must be
                exactly one match for the chart or the call raises.
        """
        if source_field not in _CARRY_FORWARD_FIELDS:
            raise ValueError(
                f"source_field {source_field!r} is not carry-forward eligible"
            )
        if target_field not in _CARRY_FORWARD_FIELDS:
            raise ValueError(
                f"target_field {target_field!r} is not carry-forward eligible"
            )

        match = await RepeatPatientService._resolve_match(
            session, tenant_id, chart_id, match_id
        )

        if not match.reviewed or not match.carry_forward_allowed:
            raise RepeatPatientReviewRequiredError(
                "carry_forward refused: match has not been reviewed and "
                "explicitly approved for carry-forward by a provider"
            )

        source_profile = (
            await session.execute(
                select(PatientProfile).where(
                    and_(
                        PatientProfile.tenant_id == tenant_id,
                        PatientProfile.id == match.matched_profile_id,
                    )
                )
            )
        ).scalar_one_or_none()
        if source_profile is None:
            raise RepeatPatientMatchNotFoundError(
                "matched patient profile no longer exists"
            )

        target_profile = (
            await session.execute(
                select(PatientProfile).where(
                    and_(
                        PatientProfile.tenant_id == tenant_id,
                        PatientProfile.chart_id == chart_id,
                    )
                )
            )
        ).scalar_one_or_none()
        if target_profile is None:
            raise RepeatPatientMatchNotFoundError(
                "active chart patient profile not found"
            )

        new_value = getattr(source_profile, source_field)
        before_value = getattr(target_profile, target_field)
        setattr(target_profile, target_field, new_value)
        now = datetime.now(UTC)
        target_profile.updated_at = now

        RepeatPatientService._audit(
            session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            user_id=user_id,
            action="repeat_patient.carry_forward",
            detail={
                "match_id": match.id,
                "source_profile_id": source_profile.id,
                "source_field": source_field,
                "target_field": target_field,
                "before": before_value,
                "after": new_value,
            },
            performed_at=now,
        )
        await session.flush()
        return {
            "match_id": match.id,
            "source_field": source_field,
            "target_field": target_field,
            "value": new_value,
        }

    # ----------------------------- private --------------------------- #

    @staticmethod
    async def _load_match(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        match_id: str,
    ) -> EpcrRepeatPatientMatch:
        row = (
            await session.execute(
                select(EpcrRepeatPatientMatch).where(
                    and_(
                        EpcrRepeatPatientMatch.tenant_id == tenant_id,
                        EpcrRepeatPatientMatch.chart_id == chart_id,
                        EpcrRepeatPatientMatch.id == match_id,
                    )
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise RepeatPatientMatchNotFoundError(
                f"repeat patient match {match_id!r} not found for chart "
                f"{chart_id!r}"
            )
        return row

    @staticmethod
    async def _resolve_match(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        match_id: str | None,
    ) -> EpcrRepeatPatientMatch:
        if match_id is not None:
            return await RepeatPatientService._load_match(
                session, tenant_id, chart_id, match_id
            )
        rows = (
            await session.execute(
                select(EpcrRepeatPatientMatch).where(
                    and_(
                        EpcrRepeatPatientMatch.tenant_id == tenant_id,
                        EpcrRepeatPatientMatch.chart_id == chart_id,
                    )
                )
            )
        ).scalars().all()
        if len(rows) != 1:
            raise RepeatPatientMatchNotFoundError(
                "match_id must be provided when chart has 0 or >1 matches"
            )
        return rows[0]


__all__ = [
    "RepeatPatientService",
    "RepeatPatientError",
    "RepeatPatientReviewRequiredError",
    "RepeatPatientMatchNotFoundError",
]
