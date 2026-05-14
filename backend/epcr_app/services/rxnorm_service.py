"""RxNorm normalization for ePCR medication administrations.

This module owns the RxNormMedicationService pillar:

- :class:`RxNavClient` — a thin async wrapper around the public RxNav HTTP
  API (``https://rxnav.nlm.nih.gov/REST`` by default). The client is
  OPTIONAL. If the ``RXNAV_URL`` environment variable is unset the
  service operates in read-only-cache mode: prior matches stored in
  :class:`~epcr_app.models.EpcrRxNormMedicationMatch` are still served,
  but new lookups return an honest "unavailable" status. The service
  NEVER fabricates an ``rxcui``.

- :class:`RxNormService` — the persistence + orchestration surface used
  by the chart workspace and the API layer. The match table doubles as
  the local cache: ``normalize_for_chart`` skips medication
  administrations that already have a non-superseded match for the
  current ``(tenant_id, medication_admin_id)``.

Provider override path: :meth:`RxNormService.confirm` accepts a
provider-supplied ``normalized_name`` / ``rxcui`` for a specific match
row, marks it ``provider_confirmed = True``, and sets ``source`` to
``provider_confirmed``. This always wins over an automatic match.

Transaction discipline: this service NEVER calls ``session.commit()``;
callers compose normalization into their own transaction boundaries.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import uuid4

import httpx
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models import (
    EpcrRxNormMedicationMatch,
    MedicationAdministration,
)

logger = logging.getLogger(__name__)


RXNAV_URL_ENV = "RXNAV_URL"
DEFAULT_RXNAV_URL = "https://rxnav.nlm.nih.gov/REST"

SOURCE_RXNAV = "rxnav_api"
SOURCE_CACHE = "local_cache"
SOURCE_PROVIDER = "provider_confirmed"

VALID_TTY = frozenset({"IN", "BN", "SCD", "SBD"})


# --------------------------------------------------------------------------- #
# RxNav HTTP client                                                           #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RxNavLookup:
    """Result of a successful name->rxcui lookup."""

    rxcui: str
    normalized_name: str
    tty: Optional[str]
    dose_form: Optional[str]
    strength: Optional[str]
    confidence: Decimal


class RxNavClient:
    """Async RxNav REST client.

    The client wraps ``httpx.AsyncClient``. To support deterministic
    testing without hitting the real network, callers may pass a custom
    ``transport`` (typically :class:`httpx.MockTransport`) — this stays
    on the real httpx code path, only the wire transport is replaced.
    """

    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 5.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            transport=transport,
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "RxNavClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def get_rxcui_by_name(self, name: str) -> Optional[RxNavLookup]:
        """Best-effort name -> rxcui lookup.

        Returns ``None`` if RxNav has no match. NEVER fabricates an
        rxcui. Raises ``httpx.HTTPError`` on transport-level failures so
        the caller can degrade to cache-only behavior.
        """
        if not name or not name.strip():
            return None
        params = {"name": name.strip(), "search": "1"}
        resp = await self._client.get("/rxcui.json", params=params)
        resp.raise_for_status()
        payload = resp.json() or {}
        id_group = (payload.get("idGroup") or {})
        rxnorm_ids = id_group.get("rxnormId") or []
        if not rxnorm_ids:
            return None
        rxcui = str(rxnorm_ids[0]).strip()
        if not rxcui:
            return None

        related = await self.get_related_concepts(rxcui)
        # ``related`` may carry preferred TTY/form/strength; fall back to
        # the raw name as the normalized_name when not provided.
        normalized_name = related.get("normalized_name") or name.strip()
        tty = related.get("tty")
        if tty is not None and tty not in VALID_TTY:
            tty = None
        # The id_group search field is 0 for an exact match, 1 for an
        # approximate match. Map that to a confidence band.
        search_grade = id_group.get("name")  # echoed input
        confidence = Decimal("0.95") if search_grade else Decimal("0.80")

        return RxNavLookup(
            rxcui=rxcui,
            normalized_name=normalized_name,
            tty=tty,
            dose_form=related.get("dose_form"),
            strength=related.get("strength"),
            confidence=confidence,
        )

    async def get_related_concepts(self, rxcui: str) -> dict[str, Any]:
        """Fetch related-concept metadata for an rxcui.

        Returns a dict with optional keys ``normalized_name``, ``tty``,
        ``dose_form``, ``strength``. Missing keys are simply absent —
        callers must not assume any of them are present.
        """
        if not rxcui:
            return {}
        resp = await self._client.get(
            f"/rxcui/{rxcui}/allrelated.json",
        )
        resp.raise_for_status()
        payload = resp.json() or {}
        out: dict[str, Any] = {}
        groups = (
            ((payload.get("allRelatedGroup") or {}).get("conceptGroup")) or []
        )
        # Pick the IN (ingredient) name as normalized_name when present,
        # otherwise the first concept name we find.
        chosen_tty: Optional[str] = None
        chosen_name: Optional[str] = None
        dose_form: Optional[str] = None
        strength: Optional[str] = None
        for group in groups:
            tty = group.get("tty")
            props = group.get("conceptProperties") or []
            if not props:
                continue
            first = props[0]
            name = first.get("name")
            if tty == "IN" and not chosen_name:
                chosen_name = name
                chosen_tty = "IN"
            elif tty in VALID_TTY and not chosen_name:
                chosen_name = name
                chosen_tty = tty
            if tty == "DF" and not dose_form:
                dose_form = name
            if tty in {"SCD", "SBD"} and not strength:
                # strength is encoded inside the SCD/SBD concept name
                strength = name
        if chosen_name:
            out["normalized_name"] = chosen_name
        if chosen_tty:
            out["tty"] = chosen_tty
        if dose_form:
            out["dose_form"] = dose_form
        if strength:
            out["strength"] = strength
        return out


# --------------------------------------------------------------------------- #
# Service                                                                     #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class NormalizationOutcome:
    """Per-medication outcome returned by ``normalize_for_chart``.

    ``capability`` is one of:
        - ``"live_match"``       : fresh RxNav match persisted
        - ``"cache_hit"``        : prior match reused, no API call
        - ``"unavailable"``      : RXNAV_URL not set and no cached match
        - ``"no_match"``         : RxNav returned no result
    """

    medication_admin_id: str
    capability: str
    match_id: Optional[str]
    rxcui: Optional[str]
    reason: Optional[str] = None


class RxNormService:
    """RxNorm normalization service (persistence + cache + provider override)."""

    # ----------------------------------------------------------------- #
    # Capability reporting                                              #
    # ----------------------------------------------------------------- #

    @staticmethod
    def capability() -> dict[str, str]:
        """Capability dict suitable for the workspace ``capabilities`` map."""
        if os.environ.get(RXNAV_URL_ENV):
            return {"capability": "live", "source": "rxnorm_service"}
        return {
            "capability": "read_only_cache",
            "reason": "RXNAV_URL not configured",
        }

    # ----------------------------------------------------------------- #
    # Client construction                                               #
    # ----------------------------------------------------------------- #

    @staticmethod
    def build_client(
        *, transport: httpx.AsyncBaseTransport | None = None
    ) -> Optional[RxNavClient]:
        """Construct an RxNav client, or ``None`` if ``RXNAV_URL`` is unset.

        ``transport`` may be passed in for testing (e.g. ``httpx.MockTransport``).
        When ``transport`` is provided AND ``RXNAV_URL`` is unset, the
        client is still NOT constructed — the env var gates capability
        independently of transport, so production paths cannot
        accidentally bypass the gate from a test fixture.
        """
        url = os.environ.get(RXNAV_URL_ENV)
        if not url:
            return None
        return RxNavClient(url, transport=transport)

    # ----------------------------------------------------------------- #
    # Read paths                                                        #
    # ----------------------------------------------------------------- #

    @staticmethod
    async def list_for_chart(
        session: AsyncSession, *, tenant_id: str, chart_id: str
    ) -> list[dict[str, Any]]:
        """Return all persisted matches for a chart, newest first."""
        rows = (
            await session.execute(
                select(EpcrRxNormMedicationMatch)
                .where(
                    and_(
                        EpcrRxNormMedicationMatch.tenant_id == tenant_id,
                        EpcrRxNormMedicationMatch.chart_id == chart_id,
                    )
                )
                .order_by(EpcrRxNormMedicationMatch.created_at.desc())
            )
        ).scalars().all()
        return [RxNormService._serialize(r) for r in rows]

    @staticmethod
    async def _existing_match(
        session: AsyncSession,
        *,
        tenant_id: str,
        medication_admin_id: str,
    ) -> Optional[EpcrRxNormMedicationMatch]:
        return (
            await session.execute(
                select(EpcrRxNormMedicationMatch).where(
                    and_(
                        EpcrRxNormMedicationMatch.tenant_id == tenant_id,
                        EpcrRxNormMedicationMatch.medication_admin_id
                        == medication_admin_id,
                    )
                )
            )
        ).scalars().first()

    # ----------------------------------------------------------------- #
    # Write paths                                                       #
    # ----------------------------------------------------------------- #

    @staticmethod
    async def normalize_for_chart(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        client: Optional[RxNavClient] = None,
    ) -> list[NormalizationOutcome]:
        """Iterate medication administrations and normalize each.

        - Rows that already have a persisted match for the current
          ``(tenant_id, medication_admin_id)`` are reported as
          ``cache_hit`` and skipped (raw text always preserved on the
          source row, regardless).
        - Rows without an existing match are sent to RxNav (if a client
          was provided). On a successful lookup, a row is persisted with
          ``source = 'rxnav_api'``. On no match, ``no_match`` outcome is
          recorded but NO row is persisted (we never store a fabricated
          rxcui).
        - If ``client`` is ``None`` (because ``RXNAV_URL`` is unset) and
          there is no cached match, the outcome is ``unavailable`` and
          NO row is persisted.

        Caller-owned client lifecycle: this method does NOT close
        ``client``. If callers construct one via
        :meth:`build_client`, they own ``await client.aclose()``.
        """
        med_rows = (
            await session.execute(
                select(MedicationAdministration).where(
                    and_(
                        MedicationAdministration.tenant_id == tenant_id,
                        MedicationAdministration.chart_id == chart_id,
                        MedicationAdministration.deleted_at.is_(None),
                    )
                )
            )
        ).scalars().all()

        outcomes: list[NormalizationOutcome] = []
        for med in med_rows:
            existing = await RxNormService._existing_match(
                session,
                tenant_id=tenant_id,
                medication_admin_id=med.id,
            )
            if existing is not None:
                outcomes.append(
                    NormalizationOutcome(
                        medication_admin_id=med.id,
                        capability="cache_hit",
                        match_id=existing.id,
                        rxcui=existing.rxcui,
                    )
                )
                continue

            raw_text = (med.medication_name or "").strip()

            if client is None:
                outcomes.append(
                    NormalizationOutcome(
                        medication_admin_id=med.id,
                        capability="unavailable",
                        match_id=None,
                        rxcui=None,
                        reason="RXNAV_URL not configured",
                    )
                )
                continue

            try:
                lookup = await client.get_rxcui_by_name(raw_text)
            except httpx.HTTPError as exc:
                logger.warning(
                    "rxnorm.lookup_failed med=%s err=%s", med.id, exc
                )
                outcomes.append(
                    NormalizationOutcome(
                        medication_admin_id=med.id,
                        capability="unavailable",
                        match_id=None,
                        rxcui=None,
                        reason="rxnav_transport_error",
                    )
                )
                continue

            if lookup is None:
                outcomes.append(
                    NormalizationOutcome(
                        medication_admin_id=med.id,
                        capability="no_match",
                        match_id=None,
                        rxcui=None,
                    )
                )
                continue

            now = datetime.now(UTC)
            row = EpcrRxNormMedicationMatch(
                id=str(uuid4()),
                tenant_id=tenant_id,
                chart_id=chart_id,
                medication_admin_id=med.id,
                raw_text=raw_text,
                normalized_name=lookup.normalized_name,
                rxcui=lookup.rxcui,
                tty=lookup.tty,
                dose_form=lookup.dose_form,
                strength=lookup.strength,
                confidence=lookup.confidence,
                source=SOURCE_RXNAV,
                provider_confirmed=False,
                provider_id=None,
                confirmed_at=None,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            await session.flush()
            outcomes.append(
                NormalizationOutcome(
                    medication_admin_id=med.id,
                    capability="live_match",
                    match_id=row.id,
                    rxcui=row.rxcui,
                )
            )
        return outcomes

    @staticmethod
    async def confirm(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        match_id: str,
        normalized_name: str,
        rxcui: str,
        provider_id: str,
        tty: Optional[str] = None,
        dose_form: Optional[str] = None,
        strength: Optional[str] = None,
    ) -> EpcrRxNormMedicationMatch:
        """Provider override: confirm or correct a match.

        This always wins over an automatic match. The row's ``source``
        becomes ``provider_confirmed`` and ``provider_confirmed`` is set
        to ``True`` with ``provider_id`` + ``confirmed_at`` populated.
        """
        if not rxcui or not rxcui.strip():
            raise ValueError("rxcui required for confirmation")
        if not normalized_name or not normalized_name.strip():
            raise ValueError("normalized_name required for confirmation")
        if tty is not None and tty not in VALID_TTY:
            raise ValueError(f"invalid tty: {tty}")

        row = (
            await session.execute(
                select(EpcrRxNormMedicationMatch).where(
                    and_(
                        EpcrRxNormMedicationMatch.id == match_id,
                        EpcrRxNormMedicationMatch.tenant_id == tenant_id,
                        EpcrRxNormMedicationMatch.chart_id == chart_id,
                    )
                )
            )
        ).scalars().first()
        if row is None:
            raise LookupError(
                f"rxnorm match not found for id={match_id} tenant={tenant_id}"
            )

        now = datetime.now(UTC)
        row.normalized_name = normalized_name.strip()
        row.rxcui = rxcui.strip()
        if tty is not None:
            row.tty = tty
        if dose_form is not None:
            row.dose_form = dose_form
        if strength is not None:
            row.strength = strength
        row.confidence = Decimal("1.00")
        row.source = SOURCE_PROVIDER
        row.provider_confirmed = True
        row.provider_id = provider_id
        row.confirmed_at = now
        row.updated_at = now
        await session.flush()
        return row

    # ----------------------------------------------------------------- #
    # Serialization                                                     #
    # ----------------------------------------------------------------- #

    @staticmethod
    def _serialize(row: EpcrRxNormMedicationMatch) -> dict[str, Any]:
        return {
            "id": row.id,
            "tenantId": row.tenant_id,
            "chartId": row.chart_id,
            "medicationAdminId": row.medication_admin_id,
            "rawText": row.raw_text,
            "normalizedName": row.normalized_name,
            "rxcui": row.rxcui,
            "tty": row.tty,
            "doseForm": row.dose_form,
            "strength": row.strength,
            "confidence": (
                float(row.confidence) if row.confidence is not None else None
            ),
            "source": row.source,
            "providerConfirmed": bool(row.provider_confirmed),
            "providerId": row.provider_id,
            "confirmedAt": (
                row.confirmed_at.isoformat() if row.confirmed_at else None
            ),
            "createdAt": row.created_at.isoformat() if row.created_at else None,
            "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
        }
