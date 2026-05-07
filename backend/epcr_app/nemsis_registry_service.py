"""Read-only NEMSIS registry service.

Exposes deterministic catalog views over the normalized artifacts produced
by ``nemsis_registry_importer`` and stored in
``nemsis_resources/official/normalized/``.

Critical no-drift rules:
- This service NEVER opens a network socket.
- This service NEVER invokes git.
- This service NEVER mutates input chart-state during evaluation.
- If the normalized files are missing, the service returns an honest
  ``not_configured`` snapshot instead of fabricating data.
- The service never claims ``official_full`` on its own; it only reports
  what the importer wrote into ``registry_snapshot.json``.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Iterable

from epcr_app.nemsis_registry_importer import (
    DEFAULT_OFFICIAL_DIR,
    OFFICIAL_SOURCE_REPO,
    SOURCE_MODE_NOT_CONFIGURED,
    SOURCE_MODE_OFFICIAL_PARTIAL,
)

REGISTRY_SOURCE_URL = "https://git.nemsis.org/scm/nep/nemsis_public.git"


class NemsisRegistryService:
    """Reads normalized NEMSIS registry artifacts. Pure read-only."""

    def __init__(self, official_dir: Path | None = None) -> None:
        self._official_dir = (official_dir or DEFAULT_OFFICIAL_DIR).resolve()
        self._normalized_dir = self._official_dir / "normalized"
        self._cache: dict[str, Any] = {}

    # -- low-level loaders ------------------------------------------------- #

    def _load_json(self, name: str, default: Any) -> Any:
        if name in self._cache:
            return self._cache[name]
        path = self._normalized_dir / name
        if not path.exists():
            self._cache[name] = default
            return default
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = default
        self._cache[name] = payload
        return payload

    def _load_manifest(self) -> dict[str, Any]:
        if "manifest" in self._cache:
            return self._cache["manifest"]
        path = self._official_dir / "manifest.json"
        if not path.exists():
            payload = {
                "source_family": "NEMSIS Version 3",
                "source_repo": OFFICIAL_SOURCE_REPO,
                "source_commit": "",
                "source_branch": "",
                "target_version": "NEMSIS_V3",
                "retrieved_at": None,
                "artifacts": [],
                "coverage_warnings": ["manifest_missing"],
            }
        else:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {
                    "source_family": "NEMSIS Version 3",
                    "source_repo": OFFICIAL_SOURCE_REPO,
                    "source_commit": "",
                    "artifacts": [],
                    "coverage_warnings": ["manifest_decode_failed"],
                }
        self._cache["manifest"] = payload
        return payload

    # -- public API -------------------------------------------------------- #

    def get_manifest(self) -> dict[str, Any]:
        return copy.deepcopy(self._load_manifest())

    def get_snapshot(self) -> dict[str, Any]:
        snap = self._load_json("registry_snapshot.json", None)
        if snap is None:
            return {
                "source_mode": SOURCE_MODE_NOT_CONFIGURED,
                "source_repo": OFFICIAL_SOURCE_REPO,
                "source_commit": "",
                "target_version": "NEMSIS_V3",
                "dictionary_version": "3.5.1",
                "field_count": 0,
                "baseline_total_expected": 654,
                "baseline_total_actual": 0,
                "baseline_counts_expected": {},
                "baseline_counts_actual": {},
                "baseline_counts_match": False,
                "element_enumeration_count": 0,
                "attribute_enumeration_count": 0,
                "defined_list_count": 0,
                "defined_list_field_count": 0,
                "official_artifact_count": 0,
                "local_seed_fallback_count": 0,
                "coverage_warnings": ["registry_snapshot_missing"],
            }
        return copy.deepcopy(snap)

    def get_version(self) -> dict[str, Any]:
        snapshot = self.get_snapshot()
        manifest = self.get_manifest()
        return {
            "source_repo": manifest.get("source_repo", OFFICIAL_SOURCE_REPO),
            "source_commit": manifest.get("source_commit", ""),
            "source_branch": manifest.get("source_branch"),
            "target_version": manifest.get("target_version") or snapshot.get("target_version"),
            "dictionary_version": snapshot.get("dictionary_version", "3.5.1"),
            "retrieved_at": manifest.get("retrieved_at") or snapshot.get("retrieved_at"),
            "baseline_total_expected": snapshot.get("baseline_total_expected"),
            "baseline_total_actual": snapshot.get("baseline_total_actual"),
            "baseline_counts_expected": snapshot.get("baseline_counts_expected", {}),
            "baseline_counts_actual": snapshot.get("baseline_counts_actual", {}),
            "baseline_counts_match": snapshot.get("baseline_counts_match", False),
            "coverage_warnings": snapshot.get("coverage_warnings", []),
        }

    def list_datasets(self) -> list[str]:
        return sorted({f.get("dataset", "Unknown") for f in self._fields()})

    def list_sections(self, dataset: str | None = None) -> list[str]:
        section_rows = self._load_json("sections.json", [])
        if section_rows:
            return sorted(
                {
                    row.get("section")
                    for row in section_rows
                    if row.get("section") and (not dataset or row.get("dataset") == dataset)
                }
            )
        sections = set()
        for f in self._fields():
            if dataset and f.get("dataset") != dataset:
                continue
            section = f.get("section")
            if section:
                sections.add(section)
        return sorted(sections)

    def list_fields(
        self, dataset: str | None = None, section: str | None = None
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for f in self._fields():
            if dataset and f.get("dataset") != dataset:
                continue
            if section and f.get("section") != section:
                continue
            out.append(copy.deepcopy(f))
        return out

    def get_field(self, field_id: str) -> dict[str, Any] | None:
        for f in self._fields():
            if f.get("field_id") == field_id:
                return copy.deepcopy(f)
        return None

    def list_element_enumerations(
        self, field_id: str | None = None
    ) -> list[dict[str, Any]]:
        rows = self._load_json("element_enumerations.json", [])
        if field_id:
            rows = [r for r in rows if r.get("field_id") == field_id]
        return copy.deepcopy(rows)

    def list_attribute_enumerations(
        self, attribute_name: str | None = None
    ) -> list[dict[str, Any]]:
        rows = self._load_json("attribute_enumerations.json", [])
        if attribute_name:
            rows = [r for r in rows if r.get("attribute_name") == attribute_name]
        return copy.deepcopy(rows)

    def list_defined_lists(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._load_json("defined_lists.json", []))

    def list_code_sets(self, field_id: str | None = None) -> list[dict[str, Any]]:
        rows = self._load_json("code_sets.json", [])
        if field_id:
            rows = [row for row in rows if row.get("field_element_id") == field_id]
        return copy.deepcopy(rows)

    def get_defined_list(self, list_id_or_field_id: str) -> dict[str, Any] | None:
        rows = self._load_json("defined_lists.json", [])
        for r in rows:
            if (
                r.get("list_id") == list_id_or_field_id
                or r.get("field_id") == list_id_or_field_id
            ):
                return copy.deepcopy(r)
        return None

    def evaluate_registry_coverage(
        self, chart_state: dict[str, Any], dataset: str | None = None
    ) -> dict[str, Any]:
        # Read-only: never mutate caller payload, never persist PHI.
        _ = copy.deepcopy(chart_state)
        fields = self.list_fields(dataset=dataset)
        provided_keys = {k for k in chart_state.keys() if isinstance(k, str)}
        covered = [f["field_id"] for f in fields if f["field_id"] in provided_keys]
        return {
            "dataset": dataset,
            "field_count": len(fields),
            "provided_field_count": len(covered),
            "covered_field_ids": covered,
            "completeness": "framework_partial",
            "source_mode": self.get_snapshot().get("source_mode"),
            "source_repo": OFFICIAL_SOURCE_REPO,
        }

    # -- internal --------------------------------------------------------- #

    def _fields(self) -> list[dict[str, Any]]:
        return self._load_json("fields.json", [])


# Module-level singleton for FastAPI DI.
_default_registry_service: NemsisRegistryService | None = None


def get_default_registry_service() -> NemsisRegistryService:
    global _default_registry_service
    if _default_registry_service is None:
        _default_registry_service = NemsisRegistryService()
    return _default_registry_service


__all__ = [
    "NemsisRegistryService",
    "get_default_registry_service",
    "REGISTRY_SOURCE_URL",
    "SOURCE_MODE_OFFICIAL_PARTIAL",
]
