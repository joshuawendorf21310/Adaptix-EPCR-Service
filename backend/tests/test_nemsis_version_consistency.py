"""CI guard for NEMSIS version-string consistency across the epcr_app package.

These tests enforce that the entire epcr_app source tree advertises the same
NEMSIS asset build (``3.5.1.251001CP2``). Drift here means the deployed
service would claim conformance with a build it cannot actually validate
against, which is a contract violation we must catch in CI.

The provenance markdown for the bundled schematron pack is also asserted
to exist and to document the current build plus a refresh runbook so ops
can prove byte-identity between the bundled file and the public NEMSIS
mirror.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from epcr_app import nemsis_dataset_xml_builder, nemsis_exporter

# The single canonical NEMSIS asset version this service is pinned to.
TARGET_NEMSIS_ASSET_VERSION = "3.5.1.251001CP2"
STALE_NEMSIS_ASSET_PREFIX = "3.5.1.250403"

# Repository layout:  backend/tests/<this file>
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_EPCR_APP_DIR = _BACKEND_DIR / "epcr_app"
_SCHEMATRON_PROVENANCE_PATH = (
    _BACKEND_DIR / "nemsis" / "schematron" / "SCHEMATRON_VERSION_PROVENANCE.md"
)


def test_exporter_version_matches_target() -> None:
    """`NEMSIS_VERSION_FULL` in the exporter must be the pinned build."""
    assert nemsis_exporter.NEMSIS_VERSION_FULL == TARGET_NEMSIS_ASSET_VERSION


def test_dataset_xml_builder_version_matches_target() -> None:
    """`NEMSIS_VERSION` in the dataset XML builder must be the pinned build."""
    assert nemsis_dataset_xml_builder.NEMSIS_VERSION == TARGET_NEMSIS_ASSET_VERSION


def test_no_stale_version_strings_in_module_constants() -> None:
    """No Python module under ``epcr_app/`` may reference the prior build.

    A recursive scan of every ``*.py`` file under the epcr_app package must
    return zero occurrences of the prior asset version (``3.5.1.250403``).
    Vendored non-Python NEMSIS artefacts (e.g. ``.sch`` files under
    ``nemsis_resources/``) are intentionally excluded — those are immutable
    upstream files whose embedded ``schemaVersion`` attribute is part of the
    file's identity, not a module constant.
    """
    offenders: list[str] = []
    for py_file in _EPCR_APP_DIR.rglob("*.py"):
        try:
            text = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:  # pragma: no cover - defensive
            pytest.fail(f"Could not read {py_file}: {exc}")
        if STALE_NEMSIS_ASSET_PREFIX in text:
            offenders.append(str(py_file.relative_to(_BACKEND_DIR)))
    assert offenders == [], (
        "Stale NEMSIS asset version "
        f"{STALE_NEMSIS_ASSET_PREFIX!r} still referenced in: {offenders}"
    )


def test_schematron_provenance_file_exists_and_documents_current_build() -> None:
    """The schematron provenance file must exist and pin the current build.

    It must also expose an ops-runnable refresh runbook so the bundled
    schematron pack can be re-verified against the public NEMSIS mirror.
    """
    assert _SCHEMATRON_PROVENANCE_PATH.is_file(), (
        f"Missing schematron provenance file at {_SCHEMATRON_PROVENANCE_PATH}"
    )
    contents = _SCHEMATRON_PROVENANCE_PATH.read_text(encoding="utf-8")

    assert TARGET_NEMSIS_ASSET_VERSION in contents, (
        f"Provenance file does not mention the pinned build "
        f"{TARGET_NEMSIS_ASSET_VERSION!r}"
    )

    lowered = contents.lower()
    mentions_runbook = "runbook" in lowered or "to refresh" in lowered or "to-refresh" in lowered
    mentions_curl_and_sha = "curl" in lowered and "sha256" in lowered
    assert mentions_runbook and mentions_curl_and_sha, (
        "Provenance file must document a refresh runbook that uses "
        "curl + sha256 to validate the bundled schematron pack."
    )
