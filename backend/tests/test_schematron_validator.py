from __future__ import annotations

from pathlib import Path
import os

import pytest

from epcr_app.nemsis import schematron_validator


def test_default_paths_resolve_to_baked_backend_schematron_assets(tmp_path: Path) -> None:
    """Default validation assets must come from the production-baked backend/nemsis tree."""

    validator = schematron_validator.OfficialSchematronValidator(compile_root=tmp_path)

    assert validator._schema_path.name == "EMSDataSet.sch"
    assert "backend" in validator._schema_path.parts
    assert validator._schema_path.parts[-3:] == (
        "nemsis",
        "schematron",
        "EMSDataSet.sch",
    )
    assert validator._utilities_root.parts[-4:] == (
        "nemsis",
        "schematron",
        "Schematron",
        "utilities",
    )


def test_default_schema_falls_back_to_legacy_sample_asset_when_baked_schema_missing(tmp_path: Path) -> None:
    """Legacy repos without the baked EMSDataSet wrapper should still resolve the sample rule file."""

    service_root = tmp_path / "service"
    module_path = service_root / "epcr_app" / "nemsis" / "schematron_validator.py"
    legacy_root = service_root / "nemsis_test" / "assets" / "schematron" / "Schematron"
    schema_path = legacy_root / "rules" / "SampleEMSDataSet.sch"
    utilities_root = legacy_root / "utilities"
    schema_path.parent.mkdir(parents=True)
    utilities_root.mkdir(parents=True)
    schema_path.write_text("<schema />", encoding="utf-8")

    resolved_root = schematron_validator.OfficialSchematronValidator._resolve_service_root(module_path)
    default_root = legacy_root

    assert resolved_root == service_root
    assert (
        schematron_validator.OfficialSchematronValidator._infer_default_schema_path(
            resolved_root,
            default_root,
        )
        == schema_path
    )


def test_validate_fails_cleanly_when_saxonche_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The public validator API should raise a clear error when XSLT 2.0 support is missing."""

    backend_root = Path(__file__).resolve().parents[1]
    schema_path = (
        backend_root
        / "nemsis"
        / "schematron"
        / "Schematron"
        / "rules"
        / "SampleEMSDataSet.sch"
    )

    monkeypatch.setattr(schematron_validator, "PySaxonProcessor", None)

    validator = schematron_validator.OfficialSchematronValidator(
        schema_path=schema_path,
        compile_root=tmp_path,
    )

    with pytest.raises(RuntimeError, match="saxonche is not installed"):
        validator.validate(b"<EMSDataSet xmlns=\"http://www.nemsis.org\" />")


def test_explicit_schema_path_infers_adjacent_utilities(tmp_path: Path) -> None:
    """Explicit schema overrides must not force callers to also override utility paths."""

    schematron_root = tmp_path / "nemsis" / "schematron" / "Schematron"
    schema_path = schematron_root / "rules" / "SampleEMSDataSet.sch"
    utilities_root = schematron_root / "utilities"
    schema_path.parent.mkdir(parents=True)
    utilities_root.mkdir(parents=True)
    schema_path.write_text("<schema />", encoding="utf-8")

    validator = schematron_validator.OfficialSchematronValidator(
        schema_path=schema_path,
        compile_root=tmp_path / "cache",
    )

    assert validator._schema_path == schema_path
    assert validator._utilities_root == utilities_root


def test_validate_uses_explicit_schema_stem_for_svrl_artifact_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """SVRL artifact naming must follow the active schema, not a hardcoded sample prefix."""

    backend_root = Path(__file__).resolve().parents[1]
    schema_path = backend_root / "nemsis" / "schematron" / "EMSDataSet.sch"

    class _FakeExecutable:
        def __init__(self) -> None:
            self.parameters: dict[str, object] = {}

        def set_parameter(self, name: str, value: object) -> None:
            self.parameters[name] = value

        def transform_to_file(self, *, source_file: str, output_file: str) -> None:
            Path(output_file).write_text(
                """<svrl:schematron-output xmlns:svrl=\"http://purl.oclc.org/dsdl/svrl\"/>""",
                encoding="utf-8",
            )

    class _FakeXslt30Processor:
        def transform_to_file(self, *, source_file: str, stylesheet_file: str, output_file: str) -> None:
                        output_path = Path(output_file)
                        if output_path.suffix == ".svrl":
                                output_path.write_text(
                                        """<svrl:schematron-output xmlns:svrl=\"http://purl.oclc.org/dsdl/svrl\">
    <svrl:failed-assert role=\" error \" location=\"/EMSDataSet\" test=\"true()\">
        <svrl:text>Error severity should stay fatal to validation.</svrl:text>
    </svrl:failed-assert>
    <svrl:successful-report role=\"warning\" location=\"/EMSDataSet\" test=\"true()\">
        <svrl:text>Warning severity should stay a warning.</svrl:text>
    </svrl:successful-report>
</svrl:schematron-output>""",
                                        encoding="utf-8",
                                )
                                return
                        output_path.write_text("<schema />", encoding="utf-8")

        def compile_stylesheet(self, *, stylesheet_file: str) -> _FakeExecutable:
            return _FakeExecutable()

    class _FakeSaxonProcessor:
        def __init__(self, *, license: bool) -> None:
            self.license = license

        def __enter__(self) -> "_FakeSaxonProcessor":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def new_xslt30_processor(self) -> _FakeXslt30Processor:
            return _FakeXslt30Processor()

        def make_string_value(self, value: str) -> str:
            return value

    monkeypatch.setattr(schematron_validator, "PySaxonProcessor", _FakeSaxonProcessor)

    validator = schematron_validator.OfficialSchematronValidator(
        schema_path=schema_path,
        compile_root=tmp_path,
    )

    result = validator.validate(b"<EMSDataSet xmlns=\"http://www.nemsis.org\" />")

    assert Path(result.svrl_path).name.startswith("EMSDataSet.")
    assert Path(result.svrl_path).suffix == ".svrl"


def test_compiled_xsl_rebuilds_when_utility_dependency_is_newer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A newer ISO Schematron utility must invalidate the compiled XSL cache."""

    schematron_root = tmp_path / "nemsis" / "schematron" / "Schematron"
    schema_path = schematron_root / "rules" / "SampleEMSDataSet.sch"
    iso_root = schematron_root / "utilities" / "iso-schematron-xslt2"
    schema_path.parent.mkdir(parents=True)
    iso_root.mkdir(parents=True)
    schema_path.write_text("<schema />", encoding="utf-8")
    include_xsl = iso_root / "iso_dsdl_include.xsl"
    abstract_xsl = iso_root / "iso_abstract_expand.xsl"
    svrl_xsl = iso_root / "iso_svrl_for_xslt2.xsl"
    include_xsl.write_text("<xsl:stylesheet version=\"1.0\" xmlns:xsl=\"http://www.w3.org/1999/XSL/Transform\"/>", encoding="utf-8")
    abstract_xsl.write_text("<xsl:stylesheet version=\"1.0\" xmlns:xsl=\"http://www.w3.org/1999/XSL/Transform\"/>", encoding="utf-8")
    svrl_xsl.write_text("<xsl:stylesheet version=\"1.0\" xmlns:xsl=\"http://www.w3.org/1999/XSL/Transform\"/>", encoding="utf-8")

    compile_calls = {"count": 0}

    class _FakeExecutable:
        def set_parameter(self, name: str, value: object) -> None:
            return None

        def transform_to_file(self, *, source_file: str, output_file: str) -> None:
            Path(output_file).write_text("compiled-xsl", encoding="utf-8")

    class _FakeXslt30Processor:
        def transform_to_file(self, *, source_file: str, stylesheet_file: str, output_file: str) -> None:
            Path(output_file).write_text("compiled-sch", encoding="utf-8")

        def compile_stylesheet(self, *, stylesheet_file: str) -> _FakeExecutable:
            compile_calls["count"] += 1
            return _FakeExecutable()

    class _FakeSaxonProcessor:
        def __init__(self, *, license: bool) -> None:
            self.license = license

        def __enter__(self) -> "_FakeSaxonProcessor":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def new_xslt30_processor(self) -> _FakeXslt30Processor:
            return _FakeXslt30Processor()

        def make_string_value(self, value: str) -> str:
            return value

    monkeypatch.setattr(schematron_validator, "PySaxonProcessor", _FakeSaxonProcessor)

    validator = schematron_validator.OfficialSchematronValidator(
        schema_path=schema_path,
        utilities_root=schematron_root / "utilities",
        compile_root=tmp_path / "cache",
    )

    first_path = validator._ensure_compiled_xsl()
    assert first_path.exists()
    assert compile_calls["count"] == 1

    cached_mtime = first_path.stat().st_mtime
    os.utime(svrl_xsl, (cached_mtime + 10, cached_mtime + 10))

    second_path = validator._ensure_compiled_xsl()
    assert second_path == first_path
    assert compile_calls["count"] == 2


def test_validate_normalizes_svrl_role_severity_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Severity classification must survive SVRL role formatting drift."""

    backend_root = Path(__file__).resolve().parents[1]
    schema_path = backend_root / "nemsis" / "schematron" / "EMSDataSet.sch"

    class _FakeExecutable:
        def __init__(self) -> None:
            self.parameters: dict[str, object] = {}

        def set_parameter(self, name: str, value: object) -> None:
            self.parameters[name] = value

        def transform_to_file(self, *, source_file: str, output_file: str) -> None:
            Path(output_file).write_text(
                                """<svrl:schematron-output xmlns:svrl=\"http://purl.oclc.org/dsdl/svrl\">
    <svrl:failed-assert role=\" error \" location=\"/EMSDataSet\" test=\"true()\">
        <svrl:text>Error severity should stay fatal to validation.</svrl:text>
    </svrl:failed-assert>
    <svrl:successful-report role=\"warning\" location=\"/EMSDataSet\" test=\"true()\">
        <svrl:text>Warning severity should stay a warning.</svrl:text>
    </svrl:successful-report>
</svrl:schematron-output>""",
                encoding="utf-8",
            )

    class _FakeXslt30Processor:
        def transform_to_file(self, *, source_file: str, stylesheet_file: str, output_file: str) -> None:
            output_path = Path(output_file)
            if output_path.suffix == ".svrl":
                output_path.write_text(
                    """<svrl:schematron-output xmlns:svrl=\"http://purl.oclc.org/dsdl/svrl\">
    <svrl:failed-assert role=\" error \" location=\"/EMSDataSet\" test=\"true()\">
        <svrl:text>Error severity should stay fatal to validation.</svrl:text>
    </svrl:failed-assert>
    <svrl:successful-report role=\"warning\" location=\"/EMSDataSet\" test=\"true()\">
        <svrl:text>Warning severity should stay a warning.</svrl:text>
    </svrl:successful-report>
</svrl:schematron-output>""",
                    encoding="utf-8",
                )
                return
            output_path.write_text("<schema />", encoding="utf-8")

        def compile_stylesheet(self, *, stylesheet_file: str) -> _FakeExecutable:
            return _FakeExecutable()

    class _FakeSaxonProcessor:
        def __init__(self, *, license: bool) -> None:
            self.license = license

        def __enter__(self) -> "_FakeSaxonProcessor":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def new_xslt30_processor(self) -> _FakeXslt30Processor:
            return _FakeXslt30Processor()

        def make_string_value(self, value: str) -> str:
            return value

    monkeypatch.setattr(schematron_validator, "PySaxonProcessor", _FakeSaxonProcessor)

    validator = schematron_validator.OfficialSchematronValidator(
        schema_path=schema_path,
        compile_root=tmp_path,
    )

    result = validator.validate(b"<EMSDataSet xmlns=\"http://www.nemsis.org\" />")

    assert result.is_valid is False
    assert [issue.role for issue in result.errors] == [" error "]
    assert [issue.role for issue in result.warnings] == ["warning"]