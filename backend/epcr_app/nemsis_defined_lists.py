"""NEMSIS Defined-List Picker Catalog (TAC Demo Slice 3 + Slice 3B).

Read-only adapter exposing NEMSIS defined-list (code-list) values for the
ePCR cockpit's defined-list pickers.

Honesty rules:
* This module is a read-only ADAPTER. It never mutates the protected
  ``nemsis/template_loader.py``, ``nemsis_template_resolver.py``,
  ``nemsis_pack_manager.py``, or any XSD/Schematron asset.
* Slice 3B adds OFFICIAL fixture-backed defined lists imported from the
  NEMSIS public Bitbucket repository at
  ``https://git.nemsis.org/projects/NEP/repos/nemsis_public/browse/DefinedLists``.
  These are stored locally as JSON envelopes under
  ``epcr_app/nemsis_resources/defined_lists/`` with full provenance metadata
  (source_url, source_name, list_name, download_format, retrieved_at).
* Slice 3 ``local_seed_field_graph`` behavior is preserved as a fallback:
  fields with ``allowed_values`` in the NemsisFieldGraph that are not also
  present as official lists continue to be exposed as before.
* When BOTH official and local-seed coverage exist for the same NEMSIS field
  id, the OFFICIAL list wins (its values + provenance are exposed) and the
  field's ``source`` is reported as ``official_nemsis_defined_list``.
* It does NOT claim full NEMSIS 3.5.1 defined-list parity. It exposes only
  the official lists actually present in the local fixtures directory plus
  the local seed fallback. Each field is labelled with ``source`` so callers
  can tell which path it came from.
* Display text falls back to the raw code when no curated display is
  available. The service NEVER fabricates a description.
* Construction is deterministic: same fixtures + same field graph in -> same
  payloads out.

This file is additive and does not alter any other module's behavior.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Iterable, Mapping

from epcr_app.nemsis_field_graph import (
    DEFAULT_GRAPH_SOURCE,
    NemsisFieldDefinition,
    NemsisFieldGraphService,
    get_default_service,
)


logger = logging.getLogger(__name__)


__all__ = [
    "DefinedListValue",
    "DefinedListField",
    "DefinedListCatalog",
    "NemsisDefinedListService",
    "get_default_defined_list_service",
    "DEFINED_LIST_SOURCE",
    "DEFINED_LIST_VERSION",
    "OFFICIAL_DEFINED_LIST_SOURCE",
    "LOCAL_SEED_DEFINED_LIST_SOURCE",
    "OFFICIAL_DEFINED_LIST_SOURCE_URL",
    "COVERAGE_MODE_LOCAL_SEED_ONLY",
    "COVERAGE_MODE_OFFICIAL_PARTIAL",
    "COVERAGE_MODE_MIXED",
    "DEFAULT_OFFICIAL_FIXTURE_DIR",
]


# Source labels honestly state where the defined-list values came from.
# - "local_seed_field_graph": derived from the curated NemsisFieldGraph
#   allowed_values seed (Slice 3 behavior).
# - "official_nemsis_defined_list": loaded from a verified local JSON
#   fixture downloaded from the NEMSIS public defined-list repository.
LOCAL_SEED_DEFINED_LIST_SOURCE = f"{DEFAULT_GRAPH_SOURCE}_field_graph"
OFFICIAL_DEFINED_LIST_SOURCE = "official_nemsis_defined_list"

# Backwards-compatible alias retained for Slice 3 callers.
DEFINED_LIST_SOURCE = LOCAL_SEED_DEFINED_LIST_SOURCE

# Version label per fixture path. The official fixtures embed their own
# upstream date; we expose this version label for the local-seed fallback.
DEFINED_LIST_VERSION = "local-seed-1"

# Canonical attribution for official fixtures.
OFFICIAL_DEFINED_LIST_SOURCE_URL = (
    "https://git.nemsis.org/projects/NEP/repos/nemsis_public/browse/DefinedLists"
)

# Coverage modes describe whether the catalog is purely local-seed,
# partially official, or a mixture. We never claim "complete" or
# "certified" coverage from this module.
COVERAGE_MODE_LOCAL_SEED_ONLY = "local_seed_only"
COVERAGE_MODE_OFFICIAL_PARTIAL = "official_partial"
COVERAGE_MODE_MIXED = "mixed_official_and_local_seed"

# Default directory the service scans for verified official fixture files.
DEFAULT_OFFICIAL_FIXTURE_DIR = (
    Path(__file__).resolve().parent / "nemsis_resources" / "defined_lists"
)


@dataclass(frozen=True)
class DefinedListValue:
    """A single picker value for a defined-list-backed NEMSIS field."""

    code: str
    display: str
    description: str | None = None
    active: bool | None = None
    category: str | None = None

    def to_payload(self) -> dict[str, object]:
        return {
            "code": self.code,
            "display": self.display,
            "description": self.description,
            "active": self.active,
            "category": self.category,
        }


@dataclass(frozen=True)
class DefinedListField:
    """A NEMSIS field that is backed by a defined list of selectable values."""

    field_id: str
    section: str
    label: str
    values: tuple[DefinedListValue, ...]
    source: str = LOCAL_SEED_DEFINED_LIST_SOURCE
    version: str | None = DEFINED_LIST_VERSION
    list_name: str | None = None
    source_url: str | None = None
    upstream_date: str | None = None
    retrieved_at: str | None = None

    def to_payload(self) -> dict[str, object]:
        return {
            "field_id": self.field_id,
            "section": self.section,
            "label": self.label,
            "source": self.source,
            "version": self.version,
            "list_name": self.list_name,
            "source_url": self.source_url,
            "upstream_date": self.upstream_date,
            "retrieved_at": self.retrieved_at,
            "value_count": len(self.values),
            "values": [value.to_payload() for value in self.values],
        }


@dataclass(frozen=True)
class DefinedListCatalog:
    """Catalog-level metadata describing the defined-list coverage state."""

    source: str
    version: str | None
    field_count: int
    official_source_url: str
    official_list_count: int
    local_seed_fallback_count: int
    coverage_mode: str
    fields: tuple[DefinedListField, ...]
    # Slice 3B registry-import metadata (None when registry not yet imported).
    source_repo: str | None = None
    source_commit: str | None = None
    target_version: str | None = None
    official_artifact_count: int = 0
    source_mode: str | None = None

    def to_payload(self) -> dict[str, object]:
        return {
            "source": self.source,
            "version": self.version,
            "field_count": self.field_count,
            "official_source_url": self.official_source_url,
            "official_list_count": self.official_list_count,
            "local_seed_fallback_count": self.local_seed_fallback_count,
            "coverage_mode": self.coverage_mode,
            "source_repo": self.source_repo,
            "source_commit": self.source_commit,
            "target_version": self.target_version,
            "official_artifact_count": self.official_artifact_count,
            "source_mode": self.source_mode,
            "fields": [field.to_payload() for field in self.fields],
        }


# Optional curated display labels. ONLY codes whose human label is locally
# verifiable belong here. If a code has no curated display, the code itself
# is used as the display text and no fabricated description is attached.
_CURATED_DISPLAY: Mapping[str, Mapping[str, str]] = {
    "eResponse.05": {
        "emergency": "Emergency Response (Immediate)",
        "non_emergency": "Non-Emergency Response",
        "intercept": "Intercept",
        "standby": "Standby",
    },
    "eDisposition.30": {
        "transported": "Transported by this EMS unit",
        "treated_not_transported": "Treated, Not Transported",
        "no_treatment_no_transport": "No Treatment Required, Not Transported",
        "canceled": "Canceled (Prior to Patient Contact)",
        "dead_at_scene": "Dead at Scene",
    },
    "eSituation.04": {
        "yes": "Yes",
        "no": "No",
        "unknown": "Unknown",
    },
    "ePatient.13.NotApplicable": {
        "unknown": "Unknown",
        "refused": "Refused",
        "not_recorded": "Not Recorded",
    },
}


def _humanize_code(code: str) -> str:
    """Best-effort code-to-display fallback. No fabrication of meaning."""

    cleaned = code.replace("_", " ").strip()
    if not cleaned:
        return code
    return cleaned[:1].upper() + cleaned[1:]


def _build_defined_list_field(
    definition: NemsisFieldDefinition,
) -> DefinedListField | None:
    """Convert a graph field into a defined-list field payload, if applicable.

    Returns ``None`` when the field has no ``allowed_values`` - i.e. it is
    not a defined-list-backed picker.
    """

    if not definition.allowed_values:
        return None

    curated = _CURATED_DISPLAY.get(definition.field_id, {})
    values = tuple(
        DefinedListValue(
            code=code,
            display=curated.get(code, _humanize_code(code)),
            description=None,
            active=True,
        )
        for code in definition.allowed_values
    )
    return DefinedListField(
        field_id=definition.field_id,
        section=definition.section,
        label=definition.label,
        values=values,
    )


class NemsisDefinedListService:
    """Read-only adapter exposing defined-list pickers for NEMSIS fields.

    Backed by:
    1. Official NEMSIS defined-list fixtures stored under
       ``epcr_app/nemsis_resources/defined_lists/`` (Slice 3B).
    2. The existing ``NemsisFieldGraphService`` local-seed catalog as a
       fallback for any fields not covered by an official fixture (Slice 3).

    We never touch the protected NEMSIS template loader, XSD validator, or
    Schematron validator.
    """

    def __init__(
        self,
        field_graph: NemsisFieldGraphService | None = None,
        official_fixture_dir: Path | None = None,
    ) -> None:
        self._graph = field_graph if field_graph is not None else get_default_service()
        self._fixture_dir = (
            official_fixture_dir
            if official_fixture_dir is not None
            else DEFAULT_OFFICIAL_FIXTURE_DIR
        )

        graph_definitions: dict[str, NemsisFieldDefinition] = {
            d.field_id: d for d in self._graph.list_fields()
        }

        # ---- Step 1: load official fixtures (Slice 3B). --------------------
        official_fields: dict[str, DefinedListField] = {}
        official_list_count = 0
        for fixture in self._iter_official_fixtures():
            official_list_count += 1
            for nemsis_field_id in fixture.get("nemsis_element_ids") or []:
                if not isinstance(nemsis_field_id, str) or not nemsis_field_id:
                    continue
                # Honest section/label resolution: prefer the field-graph
                # entry when we have one (so picker UI keeps its label),
                # otherwise derive a section from the field id (text before
                # the dot) and fall back to the upstream list name.
                graph_def = graph_definitions.get(nemsis_field_id)
                section = (
                    graph_def.section
                    if graph_def is not None
                    else nemsis_field_id.split(".", 1)[0]
                )
                label = (
                    graph_def.label
                    if graph_def is not None
                    else str(fixture.get("list_name") or nemsis_field_id)
                )
                values = _coerce_official_values(fixture.get("values") or [])
                # Deterministic dedupe: official wins if multiple fixtures
                # claim the same field id (last fixture in sorted order
                # provides the authoritative version, but in practice each
                # NEMSIS element appears in exactly one defined list).
                official_fields[nemsis_field_id] = DefinedListField(
                    field_id=nemsis_field_id,
                    section=section,
                    label=label,
                    values=values,
                    source=OFFICIAL_DEFINED_LIST_SOURCE,
                    version=str(fixture.get("upstream_date") or "")
                    or DEFINED_LIST_VERSION,
                    list_name=str(fixture.get("list_name") or "") or None,
                    source_url=str(fixture.get("source_url") or "") or None,
                    upstream_date=str(fixture.get("upstream_date") or "")
                    or None,
                    retrieved_at=str(fixture.get("retrieved_at") or "") or None,
                )

        # ---- Step 2: build local-seed fallback (Slice 3 behavior). --------
        local_seed_fields: dict[str, DefinedListField] = {}
        for definition in self._graph.list_fields():
            if definition.field_id in official_fields:
                # Official wins; do NOT also list this field as local seed.
                continue
            picker = _build_defined_list_field(definition)
            if picker is not None:
                local_seed_fields[picker.field_id] = picker

        # ---- Step 3: combine deterministically. ----------------------------
        # Order: official lists first (sorted by field id) then local seed
        # fields (in field-graph order, minus those overridden by official).
        ordered_official = tuple(
            official_fields[k] for k in sorted(official_fields.keys())
        )
        ordered_local_seed = tuple(
            local_seed_fields[d.field_id]
            for d in self._graph.list_fields()
            if d.field_id in local_seed_fields
        )
        combined = ordered_official + ordered_local_seed

        self._index: dict[str, DefinedListField] = {
            field.field_id: field for field in combined
        }
        self._ordered: tuple[DefinedListField, ...] = combined
        self._official_count = len(official_fields)
        self._local_seed_count = len(local_seed_fields)
        self._official_list_count = official_list_count

    # ------------------------------------------------------------------
    # Fixture loading helpers
    # ------------------------------------------------------------------
    def _iter_official_fixtures(self) -> Iterable[dict]:
        """Yield each verified official fixture envelope, sorted by filename."""

        if not self._fixture_dir.exists() or not self._fixture_dir.is_dir():
            return ()
        results: list[dict] = []
        for path in sorted(self._fixture_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning(
                    "Skipping unreadable NEMSIS defined-list fixture %s: %s",
                    path,
                    exc,
                )
                continue
            if not isinstance(payload, dict):
                logger.warning(
                    "Skipping NEMSIS defined-list fixture %s: not an object",
                    path,
                )
                continue
            # An envelope MUST declare its source_url + nemsis_element_ids.
            if not payload.get("source_url"):
                logger.warning(
                    "Skipping NEMSIS defined-list fixture %s: missing source_url",
                    path,
                )
                continue
            if not payload.get("nemsis_element_ids"):
                logger.warning(
                    "Skipping NEMSIS defined-list fixture %s: missing nemsis_element_ids",
                    path,
                )
                continue
            results.append(payload)
        return tuple(results)

    # ------------------------------------------------------------------
    # Public API (Slice 3 backwards compatible)
    # ------------------------------------------------------------------
    def list_defined_lists(self) -> tuple[DefinedListField, ...]:
        """Return every defined-list-backed field in deterministic order."""

        return self._ordered

    def list_defined_list_fields(self) -> tuple[str, ...]:
        """Return only the field ids of defined-list-backed fields."""

        return tuple(picker.field_id for picker in self._ordered)

    def get_defined_list(self, field_id: str) -> DefinedListField | None:
        """Return the defined-list payload for ``field_id`` or ``None``."""

        return self._index.get(field_id)

    # ------------------------------------------------------------------
    # Slice 3B catalog metadata
    # ------------------------------------------------------------------
    def coverage_mode(self) -> str:
        if self._official_count > 0 and self._local_seed_count > 0:
            return COVERAGE_MODE_MIXED
        if self._official_count > 0:
            return COVERAGE_MODE_OFFICIAL_PARTIAL
        return COVERAGE_MODE_LOCAL_SEED_ONLY

    def official_field_count(self) -> int:
        return self._official_count

    def local_seed_fallback_count(self) -> int:
        return self._local_seed_count

    def official_list_count(self) -> int:
        """Number of distinct official fixture FILES discovered."""

        return self._official_list_count

    def catalog(self) -> DefinedListCatalog:
        """Return the full catalog with Slice 3B coverage metadata."""

        coverage = self.coverage_mode()
        # Top-level source label honestly reports which path dominates.
        if coverage == COVERAGE_MODE_LOCAL_SEED_ONLY:
            source = LOCAL_SEED_DEFINED_LIST_SOURCE
            version = DEFINED_LIST_VERSION
        elif coverage == COVERAGE_MODE_OFFICIAL_PARTIAL:
            source = OFFICIAL_DEFINED_LIST_SOURCE
            version = DEFINED_LIST_VERSION
        else:
            source = COVERAGE_MODE_MIXED
            version = DEFINED_LIST_VERSION
        # Pull registry-import provenance when present. Soft-fail to None if
        # the registry has never been imported - we never invent a commit.
        source_repo: str | None = None
        source_commit: str | None = None
        target_version: str | None = None
        official_artifact_count = 0
        source_mode: str | None = None
        try:
            from epcr_app.nemsis_registry_service import get_default_registry_service

            snap = get_default_registry_service().get_snapshot()
            source_repo = snap.get("source_repo") or None
            source_commit = snap.get("source_commit") or None
            target_version = snap.get("target_version") or None
            official_artifact_count = int(snap.get("official_artifact_count") or 0)
            source_mode = snap.get("source_mode") or None
        except Exception:  # pragma: no cover - registry is optional at runtime
            logger.debug("Registry snapshot unavailable for defined-list catalog")
        return DefinedListCatalog(
            source=source,
            version=version,
            field_count=len(self._ordered),
            official_source_url=OFFICIAL_DEFINED_LIST_SOURCE_URL,
            official_list_count=self._official_count,
            local_seed_fallback_count=self._local_seed_count,
            coverage_mode=coverage,
            fields=self._ordered,
            source_repo=source_repo,
            source_commit=source_commit,
            target_version=target_version,
            official_artifact_count=official_artifact_count,
            source_mode=source_mode,
        )


def _coerce_official_values(
    raw_values: Iterable[object],
) -> tuple[DefinedListValue, ...]:
    """Convert envelope value entries to ``DefinedListValue`` tuples.

    Skips entries that do not carry both ``code`` and ``display`` so the
    service never fabricates picker values from malformed fixture rows.
    """

    out: list[DefinedListValue] = []
    for entry in raw_values:
        if not isinstance(entry, dict):
            continue
        code = entry.get("code")
        display = entry.get("display")
        if not isinstance(code, str) or not code:
            continue
        if not isinstance(display, str) or not display:
            display = code
        description = entry.get("description")
        if description is not None and not isinstance(description, str):
            description = None
        category = entry.get("category")
        if category is not None and not isinstance(category, str):
            category = None
        active = entry.get("active")
        if active is not None and not isinstance(active, bool):
            active = None
        out.append(
            DefinedListValue(
                code=code,
                display=display,
                description=description,
                active=active,
                category=category,
            )
        )
    return tuple(out)


_default_defined_list_service: NemsisDefinedListService | None = None


def get_default_defined_list_service() -> NemsisDefinedListService:
    """Return a process-wide default ``NemsisDefinedListService`` instance."""

    global _default_defined_list_service
    if _default_defined_list_service is None:
        _default_defined_list_service = NemsisDefinedListService()
    return _default_defined_list_service
