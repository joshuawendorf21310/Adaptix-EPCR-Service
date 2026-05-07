"""NEMSIS official public-source registry importer.

Reads pinned artifacts cloned from
``https://git.nemsis.org/scm/nep/nemsis_public.git`` and produces deterministic
normalized JSON files under ``nemsis_resources/official/normalized/``.

This module is invoked by a developer or CI step. The runtime EPCR service
never calls into this importer at request time, never opens a network socket
to git.nemsis.org, and never invents fields or codes.

CLI usage:

    python -m epcr_app.nemsis_registry_importer \
        --source-clone <path-to-nemsis_public-clone> \
        --source-commit <sha> \
        [--source-branch master] \
        [--retrieved-at YYYY-MM-DD]

If ``--source-clone`` is omitted the importer falls back to the bundled
``raw/`` directory under ``nemsis_resources/official``.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

OFFICIAL_SOURCE_REPO = "https://git.nemsis.org/scm/nep/nemsis_public.git"
SOURCE_FAMILY = "NEMSIS Version 3"

SOURCE_MODE_OFFICIAL_FULL = "official_full"
SOURCE_MODE_OFFICIAL_PARTIAL = "official_partial"
SOURCE_MODE_MIXED = "mixed_official_and_local_seed"
SOURCE_MODE_LOCAL_SEED_ONLY = "local_seed_only"
SOURCE_MODE_NOT_CONFIGURED = "not_configured"

ARTIFACT_TYPE_XSD = "xsd"
ARTIFACT_TYPE_SCHEMATRON = "schematron"
ARTIFACT_TYPE_DATA_DICTIONARY = "data_dictionary"
ARTIFACT_TYPE_DEFINED_LIST = "defined_list"
ARTIFACT_TYPE_USAGE_GUIDE = "usage_guide"
ARTIFACT_TYPE_SAMPLE_CUSTOM_ELEMENT = "sample_custom_element"
ARTIFACT_TYPE_OTHER = "other"

DATASET_DEM = "DEMDataSet"
DATASET_EMS = "EMSDataSet"
DATASET_STATE = "StateDataSet"
DATASET_DEFINED_LIST = "DefinedList"
DATASET_CUSTOM_ELEMENT = "CustomElement"
DATASET_SHARED = "Shared"
DATASET_UNKNOWN = "Unknown"

DICTIONARY_VERSION_351 = "3.5.1"
# Machine-derived from published NEMSIS 3.5.1 section index (HTTP 200, May 2026).
# ePayment.47 (Ambulance Conditions Indicator) and dAgency.27 (Licensed Agency)
# are both present in the published 3.5.1 site with national=No / state=No / Optional.
# The correct published 3.5.1 total is 654 = 450 EMS + 157 DEM + 47 State.
EXPECTED_BASELINE_COUNTS = {
    DATASET_EMS: 450,
    DATASET_DEM: 157,
    DATASET_STATE: 47,
}
EXPECTED_BASELINE_TOTAL = sum(EXPECTED_BASELINE_COUNTS.values())

DEFAULT_OFFICIAL_DIR = Path(__file__).resolve().parent / "nemsis_resources" / "official"

_FIELD_ID_RE = re.compile(r"^[de][A-Za-z]+\.[0-9]{2,3}$|^s[A-Za-z]+\.[0-9]{2,3}$")
_PIPE_DELIMITER = "|"


# --------------------------------------------------------------------------- #
# Dataclasses
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class NemsisRegistryArtifact:
    name: str
    artifact_type: str
    dataset: str
    source_repo_path: str
    local_path: str
    sha256: str
    source_commit: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "artifact_type": self.artifact_type,
            "dataset": self.dataset,
            "source_repo_path": self.source_repo_path,
            "local_path": self.local_path,
            "sha256": self.sha256,
            "source_commit": self.source_commit,
        }


@dataclass
class NemsisRegistryImportResult:
    manifest: dict[str, Any]
    fields: list[dict[str, Any]]
    code_sets: list[dict[str, Any]]
    sections: list[dict[str, Any]]
    validation_rules: dict[str, Any]
    element_enumerations: list[dict[str, Any]]
    attribute_enumerations: list[dict[str, Any]]
    defined_lists: list[dict[str, Any]]
    required_elements: list[dict[str, Any]]
    snapshot: dict[str, Any]
    coverage_warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _section_from_field_id(field_id: str) -> str:
    if "." not in field_id:
        return field_id
    return field_id.split(".", 1)[0]


def _canonical_dataset_for_field_id(field_id: str, dataset_name: str | None = None) -> str:
    if field_id.startswith("d"):
        return DATASET_DEM
    if field_id.startswith("e"):
        return DATASET_EMS
    if field_id.startswith("s"):
        return DATASET_STATE
    return dataset_name or DATASET_UNKNOWN


def _parse_pipe_table(path: Path) -> list[dict[str, str]]:
    """Parse a NEMSIS pipe-delimited dictionary file.

    Format example::

        'DatasetName'|'DatasetType'|'ElementNumber'| ...
        'EMSDataSet'|'element'|'dAgency.01'| ...

    Returns list of dicts keyed by header (quotes stripped).
    """
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    rows: list[dict[str, str]] = []
    if not lines:
        return rows
    header_cells = [c.strip().strip("'") for c in lines[0].split(_PIPE_DELIMITER)]
    # Drop empty trailing column from trailing pipe.
    if header_cells and header_cells[-1] == "":
        header_cells = header_cells[:-1]
    for raw in lines[1:]:
        if not raw.strip():
            continue
        cells = [c.strip().strip("'") for c in raw.split(_PIPE_DELIMITER)]
        if cells and cells[-1] == "":
            cells = cells[:-1]
        # Pad short rows; truncate long rows.
        if len(cells) < len(header_cells):
            cells = cells + [""] * (len(header_cells) - len(cells))
        elif len(cells) > len(header_cells):
            cells = cells[: len(header_cells)]
        rows.append(dict(zip(header_cells, cells)))
    return rows


def _value_or_none(s: str) -> str | None:
    s = (s or "").strip()
    if not s or s.lower() == "null":
        return None
    return s


# --------------------------------------------------------------------------- #
# Normalizer
# --------------------------------------------------------------------------- #


class NemsisRegistryNormalizer:
    """Reads pinned NEMSIS public artifacts and emits normalized JSON."""

    def __init__(
        self,
        official_dir: Path | None = None,
        source_clone: Path | None = None,
        source_commit: str = "",
        source_branch: str = "",
        retrieved_at: str | None = None,
    ) -> None:
        self.official_dir = (official_dir or DEFAULT_OFFICIAL_DIR).resolve()
        self.raw_dir = self.official_dir / "raw"
        self.normalized_dir = self.official_dir / "normalized"
        self.source_clone = source_clone.resolve() if source_clone else None
        self.source_commit = source_commit
        self.source_branch = source_branch
        self.retrieved_at = retrieved_at or _dt.date.today().isoformat()
        self.coverage_warnings: list[str] = []

    # -- artifact discovery ------------------------------------------------- #

    def _artifact_root(self) -> Path:
        if self.source_clone and self.source_clone.exists():
            return self.source_clone
        return self.raw_dir

    def load_manifest(self, artifacts: Iterable[NemsisRegistryArtifact]) -> dict[str, Any]:
        return {
            "source_family": SOURCE_FAMILY,
            "source_repo": OFFICIAL_SOURCE_REPO,
            "source_commit": self.source_commit,
            "source_branch": self.source_branch,
            "target_version": self._detect_target_version(),
            "retrieved_at": self.retrieved_at,
            "artifacts": [a.to_payload() for a in artifacts],
            "coverage_warnings": list(self.coverage_warnings),
        }

    def _detect_target_version(self) -> str:
        # Best-effort: look at commonTypes_v3.xsd / DEM XSD comments. The NEMSIS
        # public repo encodes version in folder names like "v3.5.1.251001CP2"
        # only in DIFF_FILES; we do not invent an exact patch level.
        return "NEMSIS_V3"

    def load_xsd_artifacts(self) -> list[NemsisRegistryArtifact]:
        artifacts: list[NemsisRegistryArtifact] = []
        for label, dataset in (
            ("xsd_ems", DATASET_EMS),
            ("xsd_dem", DATASET_DEM),
            ("xsd_state", DATASET_STATE),
        ):
            d = self.raw_dir / label
            if not d.exists():
                self.coverage_warnings.append(f"missing_raw_dir:{label}")
                continue
            for p in sorted(d.glob("*.xsd")):
                artifacts.append(self._artifact_from_path(p, ARTIFACT_TYPE_XSD, dataset))
        return artifacts

    def _artifact_from_path(
        self, path: Path, artifact_type: str, dataset: str
    ) -> NemsisRegistryArtifact:
        rel_local = path.relative_to(self.official_dir).as_posix()
        rel_repo = self._guess_repo_path(path, artifact_type)
        return NemsisRegistryArtifact(
            name=path.name,
            artifact_type=artifact_type,
            dataset=dataset,
            source_repo_path=rel_repo,
            local_path=rel_local,
            sha256=_sha256_file(path),
            source_commit=self.source_commit,
        )

    def _guess_repo_path(self, path: Path, artifact_type: str) -> str:
        name = path.name
        if artifact_type == ARTIFACT_TYPE_XSD:
            parent = path.parent.name
            mapping = {
                "xsd_ems": "XSDs/NEMSIS_EMS_XSDs",
                "xsd_dem": "XSDs/NEMSIS_DEM_XSDs",
                "xsd_state": "XSDs/NEMSIS_State_XSDs",
            }
            return f"{mapping.get(parent, 'XSDs')}/{name}"
        if artifact_type == ARTIFACT_TYPE_SCHEMATRON:
            return f"Schematron/DevelopmentKit/Schematron/rules/{name}"
        if artifact_type == ARTIFACT_TYPE_DATA_DICTIONARY:
            if name.startswith("StateDataSet_"):
                return f"DataDictionary/Ancillary/STATE/{name}"
            return f"DataDictionary/Ancillary/DEMEMS/{name}"
        if artifact_type == ARTIFACT_TYPE_SAMPLE_CUSTOM_ELEMENT:
            return f"SampleData/CustomElements/{name}"
        if artifact_type == ARTIFACT_TYPE_DEFINED_LIST:
            return f"DefinedLists/{name}"
        return name

    def load_other_artifacts(self) -> list[NemsisRegistryArtifact]:
        artifacts: list[NemsisRegistryArtifact] = []
        sch_dir = self.raw_dir / "schematron"
        if sch_dir.exists():
            for p in sorted(sch_dir.glob("*.sch")):
                ds = (
                    DATASET_EMS if "EMS" in p.name else DATASET_DEM if "DEM" in p.name else DATASET_SHARED
                )
                artifacts.append(self._artifact_from_path(p, ARTIFACT_TYPE_SCHEMATRON, ds))
        else:
            self.coverage_warnings.append("missing_raw_dir:schematron")
        dd_dir = self.raw_dir / "data_dictionary"
        if dd_dir.exists():
            for p in sorted(dd_dir.glob("*.txt")):
                ds = DATASET_STATE if p.name.startswith("StateDataSet_") else DATASET_SHARED
                artifacts.append(self._artifact_from_path(p, ARTIFACT_TYPE_DATA_DICTIONARY, ds))
        else:
            self.coverage_warnings.append("missing_raw_dir:data_dictionary")
        sample_dir = self.raw_dir / "sample_custom_elements"
        if sample_dir.exists():
            for p in sorted(sample_dir.iterdir()):
                if p.is_file():
                    artifacts.append(
                        self._artifact_from_path(
                            p, ARTIFACT_TYPE_SAMPLE_CUSTOM_ELEMENT, DATASET_CUSTOM_ELEMENT
                        )
                    )
        # Defined-list envelopes (Slice 3B fixtures).
        dl_dir = self.official_dir.parent / "defined_lists"
        if dl_dir.exists():
            for p in sorted(dl_dir.glob("*.json")):
                rel_local = p.relative_to(self.official_dir.parent.parent).as_posix()
                artifacts.append(
                    NemsisRegistryArtifact(
                        name=p.name,
                        artifact_type=ARTIFACT_TYPE_DEFINED_LIST,
                        dataset=DATASET_DEFINED_LIST,
                        source_repo_path=f"DefinedLists/{p.stem}/{p.stem}.json",
                        local_path=rel_local,
                        sha256=_sha256_file(p),
                        source_commit=self.source_commit,
                    )
                )
        return artifacts

    # -- normalized outputs ------------------------------------------------- #

    def normalize_fields_from_data_dictionary(self) -> list[dict[str, Any]]:
        fields_by_id: dict[str, dict[str, Any]] = {}
        sources = [
            (self.raw_dir / "data_dictionary" / "Combined_ElementDetails.txt", None),
            (
                self.raw_dir / "data_dictionary" / "StateDataSet_ElementDetails.txt",
                DATASET_STATE,
            ),
        ]
        for path, dataset_override in sources:
            if not path.exists():
                self.coverage_warnings.append(f"missing_artifact:{path.name}")
                continue
            for row in _parse_pipe_table(path):
                if (_value_or_none(row.get("DatasetType", "")) or "element") != "element":
                    continue
                element_number = _value_or_none(row.get("ElementNumber", ""))
                if not element_number:
                    continue
                source_dataset = (
                    dataset_override
                    or _value_or_none(row.get("DatasetName", ""))
                    or DATASET_UNKNOWN
                )
                canonical_dataset = _canonical_dataset_for_field_id(
                    element_number,
                    source_dataset,
                )
                min_occurs = _value_or_none(row.get("MinOccurs", ""))
                max_occurs = _value_or_none(row.get("MaxOccurs", ""))
                constraints = {
                    "min_length": _value_or_none(row.get("minLength", "")),
                    "max_length": _value_or_none(row.get("maxLength", "")),
                    "length": _value_or_none(row.get("length", "")),
                    "min_inclusive": _value_or_none(row.get("minInclusive", "")),
                    "max_inclusive": _value_or_none(row.get("maxInclusive", "")),
                    "min_exclusive": _value_or_none(row.get("minExclusive", "")),
                    "total_digits": _value_or_none(row.get("totalDigits", "")),
                    "fraction_digits": _value_or_none(row.get("fractionDigits", "")),
                    "pattern": _value_or_none(row.get("pattern", "")),
                }
                payload = fields_by_id.setdefault(
                    element_number,
                    {
                        "field_id": element_number,
                        "element_id": element_number,
                        "dataset": canonical_dataset,
                        "section": _section_from_field_id(element_number),
                        "name": element_number,
                        "label": _value_or_none(row.get("ElementName", "")) or element_number,
                        "official_name": _value_or_none(row.get("ElementName", "")) or element_number,
                        "definition": None,
                        "data_type": _value_or_none(row.get("DataType", "")),
                        "usage": _value_or_none(row.get("Usage", "")),
                        "required_level": _value_or_none(row.get("Usage", "")),
                        "national_element": _value_or_none(row.get("National", "")),
                        "state_element": _value_or_none(row.get("State", "")),
                        "recurrence": f"{min_occurs or '0'}:{max_occurs or '1'}",
                        "min_occurs": min_occurs,
                        "max_occurs": max_occurs,
                        "nillable": _value_or_none(row.get("IsNillable", "")),
                        "not_value_allowed": _value_or_none(row.get("NV", "")),
                        "pertinent_negative_allowed": _value_or_none(row.get("PN", "")),
                        "required_if": None,
                        "defined_list_ref": None,
                        "enumeration_ref": None,
                        "attributes": [],
                        "version_2_element": _value_or_none(row.get("V2Number", "")),
                        "min_length": constraints["min_length"],
                        "max_length": constraints["max_length"],
                        "pattern": constraints["pattern"],
                        "constraints": constraints,
                        "code_system": None,
                        "code_type_attribute": None,
                        "allowed_values": [],
                        "element_comments": None,
                        "deprecated": False,
                        "dictionary_version": DICTIONARY_VERSION_351,
                        "dictionary_source": self._guess_repo_path(
                            path, ARTIFACT_TYPE_DATA_DICTIONARY
                        ),
                        "source_artifact": path.name,
                        "source_repo_path": self._guess_repo_path(
                            path, ARTIFACT_TYPE_DATA_DICTIONARY
                        ),
                        "source_commit": self.source_commit,
                        "source_version": self._detect_target_version(),
                        "source_datasets": [source_dataset],
                    },
                )
                if source_dataset not in payload["source_datasets"]:
                    payload["source_datasets"].append(source_dataset)
                if payload.get("dataset") != canonical_dataset:
                    payload["dataset"] = canonical_dataset
                if payload.get("label") == element_number:
                    payload["label"] = _value_or_none(row.get("ElementName", "")) or element_number
                    payload["official_name"] = payload["label"]
                for key, value in constraints.items():
                    target_key = key if key != "pattern" else "pattern"
                    if payload.get(target_key) in (None, "") and value not in (None, ""):
                        payload[target_key] = value
                        payload["constraints"][key] = value
        # Stable ordering: dataset then field_id.
        fields = list(fields_by_id.values())
        fields.sort(key=lambda f: (f["dataset"], f["field_id"]))
        return fields

    def normalize_element_enumerations(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for fname, dataset_override in (
            ("Combined_ElementEnumerations.txt", None),
            ("StateDataSet_ElementEnumerations.txt", DATASET_STATE),
        ):
            path = self.raw_dir / "data_dictionary" / fname
            if not path.exists():
                self.coverage_warnings.append(f"missing_artifact:{fname}")
                continue
            for row in _parse_pipe_table(path):
                field_id = _value_or_none(row.get("ElementNumber", ""))
                code = _value_or_none(row.get("Code", ""))
                if not field_id or not code:
                    continue
                out.append(
                    {
                        "field_id": field_id,
                        "code": code,
                        "display": _value_or_none(row.get("CodeDescription", "")) or code,
                        "description": None,
                        "active": True,
                        "dataset": dataset_override
                        or _value_or_none(row.get("DatasetName", ""))
                        or DATASET_UNKNOWN,
                        "source_artifact": fname,
                        "source_repo_path": self._guess_repo_path(
                            path, ARTIFACT_TYPE_DATA_DICTIONARY
                        ),
                        "source_commit": self.source_commit,
                        "source_version": self._detect_target_version(),
                    }
                )
        out.sort(key=lambda r: (r["field_id"], r["code"]))
        return out

    def normalize_attribute_enumerations(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for fname in ("Combined_AttributeEnumerations.txt",):
            path = self.raw_dir / "data_dictionary" / fname
            if not path.exists():
                continue
            for row in _parse_pipe_table(path):
                attr = _value_or_none(row.get("null", "")) or _value_or_none(
                    row.get("AttributeName", "")
                )
                code = _value_or_none(row.get("Code", ""))
                if not attr or not code:
                    continue
                out.append(
                    {
                        "attribute_name": attr,
                        "code": code,
                        "display": _value_or_none(row.get("CodeDescription", "")) or code,
                        "source_artifact": fname,
                        "source_repo_path": self._guess_repo_path(
                            path, ARTIFACT_TYPE_DATA_DICTIONARY
                        ),
                        "source_commit": self.source_commit,
                        "source_version": self._detect_target_version(),
                    }
                )
        out.sort(key=lambda r: (r["attribute_name"], r["code"]))
        return out

    def normalize_defined_lists(self) -> list[dict[str, Any]]:
        dl_dir = self.official_dir.parent / "defined_lists"
        out: list[dict[str, Any]] = []
        if not dl_dir.exists():
            self.coverage_warnings.append("missing_defined_lists_dir")
            return out
        for p in sorted(dl_dir.glob("*.json")):
            try:
                envelope = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self.coverage_warnings.append(f"defined_list_decode_failed:{p.name}")
                continue
            element_ids = envelope.get("nemsis_element_ids") or []
            for element_id in element_ids:
                out.append(
                    {
                        "list_id": p.stem,
                        "list_name": envelope.get("list_name"),
                        "field_id": element_id,
                        "values": envelope.get("values", []),
                        "value_count": envelope.get("value_count", len(envelope.get("values", []))),
                        "source_artifact": p.name,
                        "source_repo_path": f"DefinedLists/{p.stem}/{p.stem}.json",
                        "source_url": envelope.get("source_url"),
                        "upstream_date": envelope.get("upstream_date"),
                        "retrieved_at": envelope.get("retrieved_at"),
                        "source_commit": self.source_commit,
                        "source_version": self._detect_target_version(),
                    }
                )
        out.sort(key=lambda r: (r["field_id"], r["list_id"]))
        return out

    def normalize_required_elements(self, fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for f in fields:
            level = (f.get("required_level") or "").lower()
            if level in {"mandatory", "required"}:
                out.append(
                    {
                        "field_id": f["field_id"],
                        "dataset": f["dataset"],
                        "national_element": f.get("national_element"),
                        "state_element": f.get("state_element"),
                        "required_level": f.get("required_level"),
                    }
                )
        return out

    def build_code_sets(
        self,
        *,
        fields: list[dict[str, Any]],
        element_enumerations: list[dict[str, Any]],
        defined_lists: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        field_index = {field["field_id"]: field for field in fields}
        for row in element_enumerations:
            field = field_index.get(row["field_id"], {})
            rows.append(
                {
                    "field_element_id": row["field_id"],
                    "code": row["code"],
                    "label": row.get("display") or row["code"],
                    "description": row.get("description"),
                    "code_system": "NEMSIS_NATIVE_CODE_LIST",
                    "code_type": field.get("data_type"),
                    "source": row.get("source_artifact"),
                    "source_version": row.get("source_version") or DICTIONARY_VERSION_351,
                    "effective_date": None,
                    "deprecated": False,
                }
            )
        for defined_list in defined_lists:
            field = field_index.get(defined_list["field_id"], {})
            for raw_value in defined_list.get("values", []):
                if isinstance(raw_value, dict):
                    code = raw_value.get("code") or raw_value.get("value") or raw_value.get("id")
                    label = raw_value.get("display") or raw_value.get("label") or code
                    description = raw_value.get("description")
                    deprecated = bool(raw_value.get("deprecated", False))
                    effective_date = raw_value.get("effective_date")
                else:
                    code = raw_value
                    label = raw_value
                    description = None
                    deprecated = False
                    effective_date = None
                if code in (None, ""):
                    continue
                rows.append(
                    {
                        "field_element_id": defined_list["field_id"],
                        "code": str(code),
                        "label": str(label),
                        "description": description,
                        "code_system": "NEMSIS_DEFINED_LIST",
                        "code_type": field.get("data_type"),
                        "source": defined_list.get("source_artifact"),
                        "source_version": defined_list.get("source_version") or DICTIONARY_VERSION_351,
                        "effective_date": effective_date,
                        "deprecated": deprecated,
                    }
                )
        rows.sort(key=lambda row: (row["field_element_id"], row["code"]))
        return rows

    def build_sections(self, fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sections: dict[tuple[str, str], list[str]] = {}
        for field in fields:
            key = (field["dataset"], field["section"])
            sections.setdefault(key, []).append(field["field_id"])
        payload: list[dict[str, Any]] = []
        for (dataset, section), field_ids in sorted(sections.items()):
            payload.append(
                {
                    "dataset": dataset,
                    "section": section,
                    "field_count": len(field_ids),
                    "field_ids": sorted(field_ids),
                }
            )
        return payload

    def build_validation_rules(self) -> dict[str, Any]:
        return {
            "status": "not_generated",
            "dictionary_version": DICTIONARY_VERSION_351,
            "source": "schematron_parse_not_implemented_in_phase1",
            "field_rule_map": {},
        }

    def normalize_sample_custom_element_awareness(
        self, artifacts: list[NemsisRegistryArtifact]
    ) -> list[dict[str, Any]]:
        return [
            {
                "name": a.name,
                "source_repo_path": a.source_repo_path,
                "sha256": a.sha256,
                "note": (
                    "Sample custom-element fixture only. NOT a configured eCustom field. "
                    "Slice 4 NemsisCustomElementService remains not_configured by design."
                ),
            }
            for a in artifacts
            if a.artifact_type == ARTIFACT_TYPE_SAMPLE_CUSTOM_ELEMENT
        ]

    # -- snapshot ----------------------------------------------------------- #

    def build_registry_snapshot(
        self,
        *,
        fields: list[dict[str, Any]],
        element_enumerations: list[dict[str, Any]],
        attribute_enumerations: list[dict[str, Any]],
        defined_lists: list[dict[str, Any]],
        artifacts: list[NemsisRegistryArtifact],
        local_seed_fallback_count: int,
    ) -> dict[str, Any]:
        # Honest source-mode determination.
        if not artifacts:
            mode = SOURCE_MODE_NOT_CONFIGURED
        elif fields and defined_lists:
            mode = (
                SOURCE_MODE_MIXED
                if local_seed_fallback_count > 0
                else SOURCE_MODE_OFFICIAL_PARTIAL
            )
        else:
            mode = SOURCE_MODE_OFFICIAL_PARTIAL
        actual_counts = {
            DATASET_EMS: len([f for f in fields if f.get("dataset") == DATASET_EMS]),
            DATASET_DEM: len([f for f in fields if f.get("dataset") == DATASET_DEM]),
            DATASET_STATE: len([f for f in fields if f.get("dataset") == DATASET_STATE]),
        }
        baseline_counts_match = actual_counts == EXPECTED_BASELINE_COUNTS
        if not baseline_counts_match and mode != SOURCE_MODE_NOT_CONFIGURED:
            detail = (
                f"NEMSIS 3.5.1 baseline count mismatch: "
                f"expected={EXPECTED_BASELINE_COUNTS} (total={EXPECTED_BASELINE_TOTAL}) "
                f"actual={actual_counts} (total={sum(actual_counts.values())}). "
                f"Do not proceed with contract generation until the official raw bundle "
                f"matches the published 3.5.1 baseline."
            )
            self.coverage_warnings.append(f"baseline_count_mismatch:{detail}")
            raise ValueError(detail)
        return {
            "source_mode": mode,
            "source_repo": OFFICIAL_SOURCE_REPO,
            "source_commit": self.source_commit,
            "source_branch": self.source_branch,
            "target_version": self._detect_target_version(),
            "dictionary_version": DICTIONARY_VERSION_351,
            "retrieved_at": self.retrieved_at,
            "field_count": len(fields),
            "baseline_total_expected": EXPECTED_BASELINE_TOTAL,
            "baseline_total_actual": len(fields),
            "baseline_counts_expected": EXPECTED_BASELINE_COUNTS,
            "baseline_counts_actual": actual_counts,
            "baseline_counts_match": baseline_counts_match,
            "element_enumeration_count": len(element_enumerations),
            "attribute_enumeration_count": len(attribute_enumerations),
            "defined_list_count": len({r["list_id"] for r in defined_lists}),
            "defined_list_field_count": len({r["field_id"] for r in defined_lists}),
            "official_artifact_count": len(artifacts),
            "local_seed_fallback_count": local_seed_fallback_count,
            "coverage_warnings": list(self.coverage_warnings),
        }

    # -- top-level orchestration ------------------------------------------- #

    def run(self, local_seed_fallback_count: int = 0) -> NemsisRegistryImportResult:
        xsd_artifacts = self.load_xsd_artifacts()
        other_artifacts = self.load_other_artifacts()
        artifacts = xsd_artifacts + other_artifacts
        fields = self.normalize_fields_from_data_dictionary()
        element_enums = self.normalize_element_enumerations()
        attr_enums = self.normalize_attribute_enumerations()
        defined_lists = self.normalize_defined_lists()
        code_sets = self.build_code_sets(
            fields=fields,
            element_enumerations=element_enums,
            defined_lists=defined_lists,
        )
        sections = self.build_sections(fields)
        validation_rules = self.build_validation_rules()
        required = self.normalize_required_elements(fields)
        snapshot = self.build_registry_snapshot(
            fields=fields,
            element_enumerations=element_enums,
            attribute_enumerations=attr_enums,
            defined_lists=defined_lists,
            artifacts=artifacts,
            local_seed_fallback_count=local_seed_fallback_count,
        )
        manifest = self.load_manifest(artifacts)
        return NemsisRegistryImportResult(
            manifest=manifest,
            fields=fields,
            code_sets=code_sets,
            sections=sections,
            validation_rules=validation_rules,
            element_enumerations=element_enums,
            attribute_enumerations=attr_enums,
            defined_lists=defined_lists,
            required_elements=required,
            snapshot=snapshot,
            coverage_warnings=list(self.coverage_warnings),
        )

    def write_normalized_outputs(self, result: NemsisRegistryImportResult) -> None:
        self.normalized_dir.mkdir(parents=True, exist_ok=True)
        self.official_dir.mkdir(parents=True, exist_ok=True)
        outputs = {
            self.official_dir / "manifest.json": result.manifest,
            self.normalized_dir / "fields.json": result.fields,
            self.normalized_dir / "code_sets.json": result.code_sets,
            self.normalized_dir / "sections.json": result.sections,
            self.normalized_dir / "validation_rules.json": result.validation_rules,
            self.normalized_dir / "element_enumerations.json": result.element_enumerations,
            self.normalized_dir / "attribute_enumerations.json": result.attribute_enumerations,
            self.normalized_dir / "defined_lists.json": result.defined_lists,
            self.normalized_dir / "required_elements.json": result.required_elements,
            self.normalized_dir / "registry_snapshot.json": result.snapshot,
        }
        for path, payload in outputs.items():
            path.write_text(
                json.dumps(payload, indent=2, sort_keys=False) + "\n",
                encoding="utf-8",
            )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="NEMSIS official-source registry importer.")
    p.add_argument("--source-clone", type=Path, default=None)
    p.add_argument("--source-commit", default="")
    p.add_argument("--source-branch", default="master")
    p.add_argument("--retrieved-at", default=None)
    p.add_argument("--official-dir", type=Path, default=None)
    p.add_argument("--local-seed-fallback-count", type=int, default=0)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    normalizer = NemsisRegistryNormalizer(
        official_dir=args.official_dir,
        source_clone=args.source_clone,
        source_commit=args.source_commit,
        source_branch=args.source_branch,
        retrieved_at=args.retrieved_at,
    )
    result = normalizer.run(local_seed_fallback_count=args.local_seed_fallback_count)
    normalizer.write_normalized_outputs(result)
    print(json.dumps(result.snapshot, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
