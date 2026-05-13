"""Service for Multi-Patient Incident linkage (MCI / multi-victim events).

Owns the lifecycle of :class:`EpcrMultiPatientIncident` (parent scene
record) and :class:`EpcrMultiPatientLink` (per-patient chart link).

Responsibilities:

- ``create_incident``: persist the parent incident row, emitting an
  ``multi_patient.incident_created`` audit entry against each
  caller-supplied seed chart (or a generic non-chart audit row if no
  seed chart is given).
- ``attach_chart``: bind a chart to an incident via a new link row
  ('A', 'B', 'C', ... or ``unknown_N``), emitting
  ``multi_patient.chart_attached``.
- ``detach_chart``: soft-delete a link row (``removed_at``) and emit
  ``multi_patient.chart_detached``.
- ``list_for_chart``: return the incident this chart belongs to and
  the sibling chart links so the workspace renderer can show
  patient-context cards without leaking cross-chart PHI.
- ``merge_incidents`` / ``split_incident``: helpers for combining two
  parent incidents into one or breaking an incident apart. The
  cross-chart copy of *clinical* values still requires explicit
  provider confirmation (this service only re-points links, never
  copies chart data).

This module never calls ``session.commit()``; the caller controls the
transaction boundary so multiple writes can be staged atomically.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models import (
    EpcrAuditLog,
    EpcrMultiPatientIncident,
    EpcrMultiPatientLink,
)

logger = logging.getLogger(__name__)


_VALID_TRIAGE = {"green", "yellow", "red", "black"}


class MultiPatientServiceError(ValueError):
    """Raised on invalid payloads or workflow violations."""


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _serialize_incident(row: EpcrMultiPatientIncident) -> dict[str, Any]:
    """Serialize a parent incident to camelCase frontend contract."""
    scene_address: Any = None
    if row.scene_address_json:
        try:
            scene_address = json.loads(row.scene_address_json)
        except (TypeError, ValueError):
            scene_address = None
    return {
        "id": row.id,
        "tenantId": row.tenant_id,
        "parentIncidentNumber": row.parent_incident_number,
        "sceneAddress": scene_address,
        "mciFlag": bool(row.mci_flag),
        "patientCount": int(row.patient_count or 0),
        "mechanism": row.mechanism,
        "hazardsText": row.hazards_text,
        "createdAt": _iso(row.created_at),
        "updatedAt": _iso(row.updated_at),
    }


def _serialize_link(row: EpcrMultiPatientLink) -> dict[str, Any]:
    """Serialize a per-patient link row."""
    return {
        "id": row.id,
        "tenantId": row.tenant_id,
        "multiIncidentId": row.multi_incident_id,
        "chartId": row.chart_id,
        "patientLabel": row.patient_label,
        "triageCategory": row.triage_category,
        "acuity": row.acuity,
        "transportPriority": row.transport_priority,
        "destinationId": row.destination_id,
        "createdAt": _iso(row.created_at),
        "updatedAt": _iso(row.updated_at),
        "removedAt": _iso(row.removed_at),
    }


def _validate_triage(value: str | None) -> str | None:
    if value is None:
        return None
    norm = str(value).strip().lower()
    if norm == "":
        return None
    if norm not in _VALID_TRIAGE:
        raise MultiPatientServiceError(
            f"triage_category must be one of {sorted(_VALID_TRIAGE)} or null"
        )
    return norm


def _validate_label(value: Any) -> str:
    if value is None:
        raise MultiPatientServiceError("patient_label is required")
    norm = str(value).strip()
    if norm == "":
        raise MultiPatientServiceError("patient_label cannot be empty")
    if len(norm) > 32:
        raise MultiPatientServiceError("patient_label exceeds 32 characters")
    return norm


class MultiPatientService:
    """Static service over multi-patient incident + link rows."""

    # --------------------------- serialization --------------------------- #

    serialize_incident = staticmethod(_serialize_incident)
    serialize_link = staticmethod(_serialize_link)

    # --------------------------- create incident --------------------------- #

    @staticmethod
    async def create_incident(
        session: AsyncSession,
        tenant_id: str,
        user_id: str,
        payload: dict[str, Any],
        *,
        seed_chart_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new multi-patient incident parent row.

        ``payload`` keys (camelCase or snake_case both accepted):
            parentIncidentNumber / parent_incident_number  (required)
            sceneAddress / scene_address                   (dict | None)
            mciFlag / mci_flag                             (bool, default False)
            patientCount / patient_count                   (int >= 0, default 0)
            mechanism                                      (str | None)
            hazardsText / hazards_text                     (str | None)

        ``seed_chart_id`` is optional. When provided, the audit row is
        scoped to that chart; otherwise no audit row is written (a
        chart-less incident has no chart key for :class:`EpcrAuditLog`).
        """
        if not isinstance(payload, dict):
            raise MultiPatientServiceError("payload must be a dict")

        def _get(*keys: str) -> Any:
            for k in keys:
                if k in payload:
                    return payload[k]
            return None

        parent_incident_number = _get(
            "parentIncidentNumber", "parent_incident_number"
        )
        if not parent_incident_number or not str(parent_incident_number).strip():
            raise MultiPatientServiceError(
                "parent_incident_number is required"
            )
        scene_address = _get("sceneAddress", "scene_address")
        scene_address_json: str | None = None
        if scene_address is not None:
            if not isinstance(scene_address, (dict, list)):
                raise MultiPatientServiceError(
                    "scene_address must be an object or list"
                )
            scene_address_json = json.dumps(scene_address, default=str)

        mci_flag = bool(_get("mciFlag", "mci_flag") or False)
        patient_count_raw = _get("patientCount", "patient_count")
        if patient_count_raw is None:
            patient_count = 0
        else:
            try:
                patient_count = int(patient_count_raw)
            except (TypeError, ValueError) as exc:
                raise MultiPatientServiceError(
                    "patient_count must be an integer"
                ) from exc
            if patient_count < 0:
                raise MultiPatientServiceError(
                    "patient_count must be >= 0"
                )

        mechanism = _get("mechanism")
        hazards_text = _get("hazardsText", "hazards_text")

        now = datetime.now(UTC)
        row = EpcrMultiPatientIncident(
            id=str(uuid4()),
            tenant_id=tenant_id,
            parent_incident_number=str(parent_incident_number).strip(),
            scene_address_json=scene_address_json,
            mci_flag=mci_flag,
            patient_count=patient_count,
            mechanism=mechanism,
            hazards_text=hazards_text,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        await session.flush()

        if seed_chart_id:
            MultiPatientService._audit(
                session,
                tenant_id=tenant_id,
                chart_id=seed_chart_id,
                user_id=user_id,
                action="multi_patient.incident_created",
                detail={
                    "incident_id": row.id,
                    "parent_incident_number": row.parent_incident_number,
                    "mci_flag": mci_flag,
                    "patient_count": patient_count,
                },
                performed_at=now,
            )
            await session.flush()

        return _serialize_incident(row)

    # --------------------------- attach chart --------------------------- #

    @staticmethod
    async def attach_chart(
        session: AsyncSession,
        tenant_id: str,
        user_id: str,
        incident_id: str,
        chart_id: str,
        patient_label: str,
        *,
        triage_category: str | None = None,
        acuity: str | None = None,
        transport_priority: str | None = None,
        destination_id: str | None = None,
    ) -> dict[str, Any]:
        """Attach a chart to the incident via a new link row."""
        label = _validate_label(patient_label)
        triage = _validate_triage(triage_category)

        # Ensure incident exists and belongs to tenant.
        incident = (
            await session.execute(
                select(EpcrMultiPatientIncident).where(
                    and_(
                        EpcrMultiPatientIncident.id == incident_id,
                        EpcrMultiPatientIncident.tenant_id == tenant_id,
                    )
                )
            )
        ).scalar_one_or_none()
        if incident is None:
            raise MultiPatientServiceError(
                f"multi_patient_incident {incident_id!r} not found for tenant"
            )

        # Prevent duplicate live link for the same (incident, chart).
        existing = (
            await session.execute(
                select(EpcrMultiPatientLink).where(
                    and_(
                        EpcrMultiPatientLink.tenant_id == tenant_id,
                        EpcrMultiPatientLink.multi_incident_id == incident_id,
                        EpcrMultiPatientLink.chart_id == chart_id,
                        EpcrMultiPatientLink.removed_at.is_(None),
                    )
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise MultiPatientServiceError(
                f"chart {chart_id!r} already attached to incident {incident_id!r}"
            )

        now = datetime.now(UTC)
        link = EpcrMultiPatientLink(
            id=str(uuid4()),
            tenant_id=tenant_id,
            multi_incident_id=incident_id,
            chart_id=chart_id,
            patient_label=label,
            triage_category=triage,
            acuity=acuity,
            transport_priority=transport_priority,
            destination_id=destination_id,
            created_at=now,
            updated_at=now,
        )
        session.add(link)
        await session.flush()

        MultiPatientService._audit(
            session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            user_id=user_id,
            action="multi_patient.chart_attached",
            detail={
                "link_id": link.id,
                "incident_id": incident_id,
                "patient_label": label,
                "triage_category": triage,
                "acuity": acuity,
                "transport_priority": transport_priority,
                "destination_id": destination_id,
            },
            performed_at=now,
        )
        await session.flush()
        return _serialize_link(link)

    # --------------------------- detach chart --------------------------- #

    @staticmethod
    async def detach_chart(
        session: AsyncSession,
        tenant_id: str,
        user_id: str,
        link_id: str,
    ) -> dict[str, Any]:
        """Soft-delete a multi-patient link row."""
        link = (
            await session.execute(
                select(EpcrMultiPatientLink).where(
                    and_(
                        EpcrMultiPatientLink.id == link_id,
                        EpcrMultiPatientLink.tenant_id == tenant_id,
                    )
                )
            )
        ).scalar_one_or_none()
        if link is None:
            raise MultiPatientServiceError(
                f"multi_patient_link {link_id!r} not found for tenant"
            )
        if link.removed_at is not None:
            return _serialize_link(link)

        now = datetime.now(UTC)
        link.removed_at = now
        link.updated_at = now

        MultiPatientService._audit(
            session,
            tenant_id=tenant_id,
            chart_id=link.chart_id,
            user_id=user_id,
            action="multi_patient.chart_detached",
            detail={
                "link_id": link.id,
                "incident_id": link.multi_incident_id,
                "patient_label": link.patient_label,
            },
            performed_at=now,
        )
        await session.flush()
        return _serialize_link(link)

    # --------------------------- read --------------------------- #

    @staticmethod
    async def list_for_chart(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
    ) -> dict[str, Any]:
        """Return the incident + sibling links for the given chart.

        Returns a dict shaped:

            {
                "incident": <incident dict | None>,
                "self": <link dict | None>,
                "siblings": [<link dict>, ...],
            }

        ``siblings`` excludes the row representing this chart. Soft-deleted
        link rows are omitted. If the chart is not attached to any live
        incident, returns ``{"incident": None, "self": None, "siblings": []}``.
        """
        my_link = (
            await session.execute(
                select(EpcrMultiPatientLink)
                .where(
                    and_(
                        EpcrMultiPatientLink.tenant_id == tenant_id,
                        EpcrMultiPatientLink.chart_id == chart_id,
                        EpcrMultiPatientLink.removed_at.is_(None),
                    )
                )
                .order_by(EpcrMultiPatientLink.created_at)
            )
        ).scalars().first()

        if my_link is None:
            return {"incident": None, "self": None, "siblings": []}

        incident = (
            await session.execute(
                select(EpcrMultiPatientIncident).where(
                    and_(
                        EpcrMultiPatientIncident.id
                        == my_link.multi_incident_id,
                        EpcrMultiPatientIncident.tenant_id == tenant_id,
                    )
                )
            )
        ).scalar_one_or_none()

        sibling_rows = (
            await session.execute(
                select(EpcrMultiPatientLink)
                .where(
                    and_(
                        EpcrMultiPatientLink.tenant_id == tenant_id,
                        EpcrMultiPatientLink.multi_incident_id
                        == my_link.multi_incident_id,
                        EpcrMultiPatientLink.removed_at.is_(None),
                        EpcrMultiPatientLink.id != my_link.id,
                    )
                )
                .order_by(
                    EpcrMultiPatientLink.patient_label,
                    EpcrMultiPatientLink.created_at,
                )
            )
        ).scalars().all()

        return {
            "incident": (
                _serialize_incident(incident) if incident is not None else None
            ),
            "self": _serialize_link(my_link),
            "siblings": [_serialize_link(s) for s in sibling_rows],
        }

    # --------------------------- merge / split --------------------------- #

    @staticmethod
    async def merge_incidents(
        session: AsyncSession,
        tenant_id: str,
        user_id: str,
        source_incident_id: str,
        target_incident_id: str,
    ) -> dict[str, Any]:
        """Re-point all live links from ``source`` to ``target``.

        Does NOT copy any clinical chart data across charts; any
        cross-chart clinical value carry-forward requires explicit
        provider confirmation handled by the chart-workspace service.
        The source incident row is preserved (soft-history) so the
        audit trail remains intact.
        """
        if source_incident_id == target_incident_id:
            raise MultiPatientServiceError(
                "source and target incident_id must differ"
            )

        # Validate both incidents are tenant-scoped.
        for incident_id in (source_incident_id, target_incident_id):
            ok = (
                await session.execute(
                    select(EpcrMultiPatientIncident.id).where(
                        and_(
                            EpcrMultiPatientIncident.id == incident_id,
                            EpcrMultiPatientIncident.tenant_id == tenant_id,
                        )
                    )
                )
            ).scalar_one_or_none()
            if ok is None:
                raise MultiPatientServiceError(
                    f"multi_patient_incident {incident_id!r} not found for tenant"
                )

        rows = (
            await session.execute(
                select(EpcrMultiPatientLink).where(
                    and_(
                        EpcrMultiPatientLink.tenant_id == tenant_id,
                        EpcrMultiPatientLink.multi_incident_id
                        == source_incident_id,
                        EpcrMultiPatientLink.removed_at.is_(None),
                    )
                )
            )
        ).scalars().all()

        now = datetime.now(UTC)
        moved = 0
        for link in rows:
            link.multi_incident_id = target_incident_id
            link.updated_at = now
            MultiPatientService._audit(
                session,
                tenant_id=tenant_id,
                chart_id=link.chart_id,
                user_id=user_id,
                action="multi_patient.link_merged",
                detail={
                    "link_id": link.id,
                    "from_incident_id": source_incident_id,
                    "to_incident_id": target_incident_id,
                },
                performed_at=now,
            )
            moved += 1
        await session.flush()
        return {
            "moved": moved,
            "from_incident_id": source_incident_id,
            "to_incident_id": target_incident_id,
        }

    @staticmethod
    async def split_incident(
        session: AsyncSession,
        tenant_id: str,
        user_id: str,
        source_incident_id: str,
        link_ids: list[str],
        new_incident_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Move a subset of links to a newly-created incident.

        Creates a new incident from ``new_incident_payload`` (same shape
        as :meth:`create_incident`) and re-points the named links to it.
        No clinical chart data is copied.
        """
        if not link_ids:
            raise MultiPatientServiceError("link_ids must be non-empty")

        # Validate source.
        src = (
            await session.execute(
                select(EpcrMultiPatientIncident).where(
                    and_(
                        EpcrMultiPatientIncident.id == source_incident_id,
                        EpcrMultiPatientIncident.tenant_id == tenant_id,
                    )
                )
            )
        ).scalar_one_or_none()
        if src is None:
            raise MultiPatientServiceError(
                f"multi_patient_incident {source_incident_id!r} not found for tenant"
            )

        new_incident = await MultiPatientService.create_incident(
            session, tenant_id, user_id, new_incident_payload
        )
        new_incident_id = new_incident["id"]

        rows = (
            await session.execute(
                select(EpcrMultiPatientLink).where(
                    and_(
                        EpcrMultiPatientLink.tenant_id == tenant_id,
                        EpcrMultiPatientLink.id.in_(link_ids),
                        EpcrMultiPatientLink.multi_incident_id
                        == source_incident_id,
                        EpcrMultiPatientLink.removed_at.is_(None),
                    )
                )
            )
        ).scalars().all()

        if len(rows) != len(set(link_ids)):
            raise MultiPatientServiceError(
                "one or more link_ids not found in source incident"
            )

        now = datetime.now(UTC)
        for link in rows:
            link.multi_incident_id = new_incident_id
            link.updated_at = now
            MultiPatientService._audit(
                session,
                tenant_id=tenant_id,
                chart_id=link.chart_id,
                user_id=user_id,
                action="multi_patient.link_split",
                detail={
                    "link_id": link.id,
                    "from_incident_id": source_incident_id,
                    "to_incident_id": new_incident_id,
                },
                performed_at=now,
            )
        await session.flush()
        return {
            "new_incident": new_incident,
            "moved_link_ids": [link.id for link in rows],
        }

    # --------------------------- audit --------------------------- #

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


__all__ = ["MultiPatientService", "MultiPatientServiceError"]
