"""Tests for the NEMSIS official-source registry importer (Slice 3B+)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from epcr_app.nemsis_registry_importer import (
    DEFAULT_OFFICIAL_DIR,
    NemsisRegistryArtifact,
    NemsisRegistryNormalizer,
    OFFICIAL_SOURCE_REPO,
    SOURCE_MODE_NOT_CONFIGURED,
    SOURCE_MODE_OFFICIAL_PARTIAL,
)


PINNED_COMMIT = "9bff090cbf95db614529bdff5e1e988a93f89717"


def test_default_official_dir_exists() -> None:
    assert DEFAULT_OFFICIAL_DIR.exists()
    assert (DEFAULT_OFFICIAL_DIR / "raw").exists()
    assert (DEFAULT_OFFICIAL_DIR / "normalized").exists()
    assert (DEFAULT_OFFICIAL_DIR / "manifest.json").exists()


def test_manifest_records_official_repo_and_commit() -> None:
    manifest = json.loads((DEFAULT_OFFICIAL_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_repo"] == OFFICIAL_SOURCE_REPO
    assert manifest["source_commit"] == PINNED_COMMIT
    assert manifest["source_branch"]
    assert manifest["target_version"]
    assert manifest["retrieved_at"]
    assert isinstance(manifest["artifacts"], list)
    assert manifest["artifacts"], "manifest must record at least one artifact"


def test_every_artifact_has_sha256_and_commit() -> None:
    manifest = json.loads((DEFAULT_OFFICIAL_DIR / "manifest.json").read_text(encoding="utf-8"))
    for art in manifest["artifacts"]:
        assert art["sha256"] and len(art["sha256"]) == 64
        assert art["source_commit"] == PINNED_COMMIT
        assert art["source_repo_path"]
        assert art["local_path"]
        assert art["artifact_type"]
        assert art["dataset"]


def test_artifact_types_include_xsd_dictionary_and_defined_list() -> None:
    manifest = json.loads((DEFAULT_OFFICIAL_DIR / "manifest.json").read_text(encoding="utf-8"))
    types = {a["artifact_type"] for a in manifest["artifacts"]}
    assert "xsd" in types
    assert "data_dictionary" in types
    assert "defined_list" in types


def test_registry_snapshot_reports_source_commit_and_mode() -> None:
    snap = json.loads(
        (DEFAULT_OFFICIAL_DIR / "normalized" / "registry_snapshot.json").read_text(encoding="utf-8")
    )
    assert snap["source_repo"] == OFFICIAL_SOURCE_REPO
    assert snap["source_commit"] == PINNED_COMMIT
    assert snap["source_mode"] in {SOURCE_MODE_OFFICIAL_PARTIAL, "mixed_official_and_local_seed"}
    assert snap["field_count"] > 0
    assert snap["element_enumeration_count"] > 0
    assert snap["defined_list_count"] >= 6
    assert snap["official_artifact_count"] > 0


def test_normalized_fields_have_traceability() -> None:
    fields = json.loads(
        (DEFAULT_OFFICIAL_DIR / "normalized" / "fields.json").read_text(encoding="utf-8")
    )
    assert fields, "fields.json must not be empty"
    sample = fields[0]
    assert sample["field_id"]
    assert sample["dataset"]
    assert sample["section"]
    assert sample["source_artifact"]
    assert sample["source_repo_path"]
    assert sample["source_commit"] == PINNED_COMMIT


def test_normalized_element_enumerations_have_code_display_source() -> None:
    rows = json.loads(
        (DEFAULT_OFFICIAL_DIR / "normalized" / "element_enumerations.json").read_text(encoding="utf-8")
    )
    assert rows
    for r in rows[:50]:
        assert r["field_id"]
        assert r["code"]
        assert r["display"]
        assert r["source_artifact"]
        assert r["source_commit"] == PINNED_COMMIT


def test_normalized_defined_lists_have_provenance() -> None:
    rows = json.loads(
        (DEFAULT_OFFICIAL_DIR / "normalized" / "defined_lists.json").read_text(encoding="utf-8")
    )
    assert rows
    for r in rows:
        assert r["field_id"]
        assert r["list_id"]
        assert r["source_artifact"]
        assert r["source_repo_path"].startswith("DefinedLists/")
        assert r["source_url"], "official defined-list rows must keep the upstream source URL"


def test_normalizer_emits_not_configured_when_dirs_missing(tmp_path: Path) -> None:
    n = NemsisRegistryNormalizer(
        official_dir=tmp_path,
        source_commit="deadbeef",
        retrieved_at="2026-05-06",
    )
    result = n.run(local_seed_fallback_count=0)
    assert result.snapshot["source_mode"] == SOURCE_MODE_NOT_CONFIGURED
    assert result.snapshot["field_count"] == 0
    assert result.snapshot["official_artifact_count"] == 0


def test_artifact_dataclass_round_trip() -> None:
    a = NemsisRegistryArtifact(
        name="x.xsd",
        artifact_type="xsd",
        dataset="EMSDataSet",
        source_repo_path="XSDs/NEMSIS_EMS_XSDs/x.xsd",
        local_path="raw/xsd_ems/x.xsd",
        sha256="0" * 64,
        source_commit=PINNED_COMMIT,
    )
    payload = a.to_payload()
    assert payload["sha256"] == "0" * 64
    assert payload["source_commit"] == PINNED_COMMIT


def test_pipe_table_handles_quoted_cells_and_nulls(tmp_path: Path) -> None:
    from epcr_app.nemsis_registry_importer import _parse_pipe_table

    p = tmp_path / "sample.txt"
    p.write_text(
        "'Col1'|'Col2'|\n"
        "'a'|'b'|\n"
        "'c'|'null'|\n",
        encoding="utf-8",
    )
    rows = _parse_pipe_table(p)
    assert rows == [{"Col1": "a", "Col2": "b"}, {"Col1": "c", "Col2": "null"}]


def test_no_runtime_network_imports_in_service() -> None:
    """Belt-and-suspenders: importer/service modules must not import network libs."""

    forbidden = ("requests", "httpx.Client", "urllib.request.urlopen", "git.Repo")
    for module_name in (
        "epcr_app.nemsis_registry_importer",
        "epcr_app.nemsis_registry_service",
    ):
        text = Path(__file__).parent.parent.joinpath(
            "epcr_app", module_name.split(".")[-1] + ".py"
        ).read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{module_name} must not reference {token}"


def test_sample_custom_elements_are_artifact_only_not_registry_fields() -> None:
    manifest = json.loads((DEFAULT_OFFICIAL_DIR / "manifest.json").read_text(encoding="utf-8"))
    sample_artifacts = [a for a in manifest["artifacts"] if a["artifact_type"] == "sample_custom_element"]
    if not sample_artifacts:
        pytest.skip("no sample custom elements present in this clone")
    fields = json.loads(
        (DEFAULT_OFFICIAL_DIR / "normalized" / "fields.json").read_text(encoding="utf-8")
    )
    for f in fields:
        assert f["dataset"] != "CustomElement"
