"""Mapbox-backed ePCR location pillar service.

Persists per-chart geospatial context (scene, destination, staging,
breadcrumb captures) into :class:`EpcrMapLocationContext` and, when a
``MAPBOX_TOKEN`` environment variable is configured, optionally enriches
rows with a reverse-geocoded ``address_text`` and computes Mapbox
Directions route metrics between two coordinate pairs.

Honesty contract
----------------
The service never fabricates location data:

- If ``MAPBOX_TOKEN`` is unset (or empty) at write time,
  :meth:`record_location` records the row with
  ``reverse_geocoded=False`` and ``address_text=None``.
- :meth:`compute_route` returns
  ``{"available": False, "reason": "MAPBOX_TOKEN not configured"}``
  when the token is absent, rather than emitting stub distances.
- ``facility_type`` is set only from a real classifier (the caller may
  pass a classified value; the service does not infer one from text).

HTTP boundary
-------------
All outbound HTTP is performed through :class:`httpx.AsyncClient`. Tests
that need to assert behavior across the network boundary inject an
``httpx.MockTransport`` via :meth:`build_client`, which keeps the
production code path under test rather than monkey-patching service
internals.

Transaction discipline
----------------------
The service never calls ``session.commit()``; the caller (typically the
chart workspace API) controls the transaction boundary.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models import EpcrAuditLog, EpcrMapLocationContext

logger = logging.getLogger(__name__)


ALLOWED_KINDS: frozenset[str] = frozenset(
    {"scene", "destination", "staging", "breadcrumb"}
)
ALLOWED_FACILITY_TYPES: frozenset[str] = frozenset(
    {
        "stroke_center",
        "stemi_center",
        "trauma_center",
        "pediatric",
        "burn",
        "behavioral_health",
    }
)


MAPBOX_GEOCODE_URL = (
    "https://api.mapbox.com/geocoding/v5/mapbox.places/{lng},{lat}.json"
)
MAPBOX_DIRECTIONS_URL = (
    "https://api.mapbox.com/directions/v5/mapbox/driving/"
    "{slng},{slat};{dlng},{dlat}"
)


def _token() -> str | None:
    tok = os.environ.get("MAPBOX_TOKEN")
    if tok is None:
        return None
    tok = tok.strip()
    return tok or None


def _num(val: Any) -> Any:
    if isinstance(val, Decimal):
        return float(val)
    return val


def _iso(dt: Any) -> str | None:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(dt, str):
        return dt
    return None


def _coerce_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed
    raise ValueError("captured_at must be datetime or ISO string")


def build_client(
    transport: httpx.AsyncBaseTransport | None = None,
    timeout: float = 5.0,
) -> httpx.AsyncClient:
    """Construct the AsyncClient used for Mapbox calls.

    Exposed for tests so they can inject an ``httpx.MockTransport``
    without monkey-patching the production code path.
    """
    if transport is not None:
        return httpx.AsyncClient(transport=transport, timeout=timeout)
    return httpx.AsyncClient(timeout=timeout)


class MapLocationService:
    """Static service over :class:`EpcrMapLocationContext`."""

    # --------------------------- serialization --------------------------- #

    @staticmethod
    def serialize(row: EpcrMapLocationContext) -> dict[str, Any]:
        return {
            "id": row.id,
            "tenantId": row.tenant_id,
            "chartId": row.chart_id,
            "kind": row.kind,
            "addressText": row.address_text,
            "latitude": _num(row.latitude),
            "longitude": _num(row.longitude),
            "accuracyMeters": _num(row.accuracy_meters),
            "reverseGeocoded": bool(row.reverse_geocoded),
            "facilityType": row.facility_type,
            "distanceMeters": _num(row.distance_meters),
            "capturedAt": _iso(row.captured_at),
            "createdAt": _iso(row.created_at),
            "updatedAt": _iso(row.updated_at),
        }

    # --------------------------- read --------------------------- #

    @staticmethod
    async def list_for_chart(
        session: AsyncSession, tenant_id: str, chart_id: str
    ) -> list[dict[str, Any]]:
        rows = (
            await session.execute(
                select(EpcrMapLocationContext)
                .where(
                    and_(
                        EpcrMapLocationContext.tenant_id == tenant_id,
                        EpcrMapLocationContext.chart_id == chart_id,
                    )
                )
                .order_by(
                    EpcrMapLocationContext.captured_at,
                    EpcrMapLocationContext.id,
                )
            )
        ).scalars().all()
        return [MapLocationService.serialize(r) for r in rows]

    # --------------------------- write --------------------------- #

    @staticmethod
    async def record_location(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        kind: str,
        lat: float | Decimal,
        lng: float | Decimal,
        accuracy: float | Decimal | None,
        captured_at: datetime | str,
        user_id: str | None = None,
        facility_type: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """Persist a single location capture and (optionally) reverse-geocode.

        If ``MAPBOX_TOKEN`` is set the service attempts a Mapbox reverse
        geocode and, on success, marks ``reverse_geocoded=True`` with the
        returned ``address_text``. Any HTTP failure leaves the row with
        ``reverse_geocoded=False`` and ``address_text=None`` and is
        logged but not raised — the location capture itself remains
        durable.
        """
        if kind not in ALLOWED_KINDS:
            raise ValueError(
                f"kind must be one of {sorted(ALLOWED_KINDS)}, got {kind!r}"
            )
        if facility_type is not None and facility_type not in ALLOWED_FACILITY_TYPES:
            raise ValueError(
                "facility_type must be one of "
                f"{sorted(ALLOWED_FACILITY_TYPES)} or None, "
                f"got {facility_type!r}"
            )

        captured_dt = _coerce_dt(captured_at)
        now = datetime.now(UTC)

        address_text: str | None = None
        reverse_geocoded = False
        token = _token()
        if token:
            try:
                address_text = await MapLocationService._reverse_geocode(
                    lat=float(lat),
                    lng=float(lng),
                    token=token,
                    client=http_client,
                )
                reverse_geocoded = address_text is not None
            except Exception:  # noqa: BLE001 - never fail the write on a network hiccup
                logger.warning(
                    "Mapbox reverse-geocode failed; recording row honestly "
                    "without address_text",
                    exc_info=True,
                )
                address_text = None
                reverse_geocoded = False

        row = EpcrMapLocationContext(
            id=str(uuid4()),
            tenant_id=tenant_id,
            chart_id=chart_id,
            kind=kind,
            address_text=address_text,
            latitude=Decimal(str(lat)),
            longitude=Decimal(str(lng)),
            accuracy_meters=(
                Decimal(str(accuracy)) if accuracy is not None else None
            ),
            reverse_geocoded=reverse_geocoded,
            facility_type=facility_type,
            distance_meters=None,
            captured_at=captured_dt,
            created_at=now,
            updated_at=now,
        )
        session.add(row)

        audit = EpcrAuditLog(
            id=str(uuid4()),
            chart_id=chart_id,
            tenant_id=tenant_id,
            user_id=user_id or "system",
            action="map_location.recorded",
            detail_json=json.dumps(
                {
                    "kind": kind,
                    "latitude": float(lat),
                    "longitude": float(lng),
                    "accuracy_meters": (
                        float(accuracy) if accuracy is not None else None
                    ),
                    "reverse_geocoded": reverse_geocoded,
                    "address_text": address_text,
                    "facility_type": facility_type,
                    "captured_at": _iso(captured_dt),
                },
                default=str,
            ),
            performed_at=now,
        )
        session.add(audit)

        await session.flush()
        return MapLocationService.serialize(row)

    # --------------------------- route --------------------------- #

    @staticmethod
    async def compute_route(
        scene: dict[str, Any],
        destination: dict[str, Any],
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """Compute driving route between scene and destination via Mapbox.

        Returns either::

            {"available": True, "distance_meters": float,
             "duration_seconds": float, "source": "mapbox_directions"}

        when ``MAPBOX_TOKEN`` is configured and the API call succeeds, or::

            {"available": False, "reason": "MAPBOX_TOKEN not configured"}

        when the token is unset. On HTTP failure with a configured token,
        returns ``{"available": False, "reason": "mapbox_directions_error",
        "detail": "..."}`` rather than fabricating distances.
        """
        token = _token()
        if not token:
            return {
                "available": False,
                "reason": "MAPBOX_TOKEN not configured",
            }

        try:
            slat = float(scene["latitude"])
            slng = float(scene["longitude"])
            dlat = float(destination["latitude"])
            dlng = float(destination["longitude"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                "scene/destination must contain numeric latitude/longitude"
            ) from exc

        url = MAPBOX_DIRECTIONS_URL.format(
            slng=slng, slat=slat, dlng=dlng, dlat=dlat
        )
        params = {"access_token": token, "overview": "false"}

        own_client = http_client is None
        client = http_client or build_client()
        try:
            try:
                resp = await client.get(url, params=params)
            except httpx.HTTPError as exc:
                return {
                    "available": False,
                    "reason": "mapbox_directions_error",
                    "detail": str(exc),
                }
            if resp.status_code != 200:
                return {
                    "available": False,
                    "reason": "mapbox_directions_error",
                    "detail": f"HTTP {resp.status_code}",
                }
            payload = resp.json()
            routes = payload.get("routes") or []
            if not routes:
                return {
                    "available": False,
                    "reason": "mapbox_directions_no_route",
                }
            route0 = routes[0]
            distance = route0.get("distance")
            duration = route0.get("duration")
            if distance is None or duration is None:
                return {
                    "available": False,
                    "reason": "mapbox_directions_malformed",
                }
            return {
                "available": True,
                "distance_meters": float(distance),
                "duration_seconds": float(duration),
                "source": "mapbox_directions",
            }
        finally:
            if own_client:
                await client.aclose()

    # --------------------------- internal --------------------------- #

    @staticmethod
    async def _reverse_geocode(
        *,
        lat: float,
        lng: float,
        token: str,
        client: httpx.AsyncClient | None,
    ) -> str | None:
        url = MAPBOX_GEOCODE_URL.format(lng=lng, lat=lat)
        params = {"access_token": token, "limit": 1}
        own_client = client is None
        c = client or build_client()
        try:
            resp = await c.get(url, params=params)
            if resp.status_code != 200:
                return None
            payload = resp.json()
            features = payload.get("features") or []
            if not features:
                return None
            place = features[0].get("place_name")
            if isinstance(place, str) and place.strip():
                return place
            return None
        finally:
            if own_client:
                await c.aclose()


__all__ = [
    "ALLOWED_FACILITY_TYPES",
    "ALLOWED_KINDS",
    "MapLocationService",
    "build_client",
]
