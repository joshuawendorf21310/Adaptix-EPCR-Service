from __future__ import annotations

"""Authoritative Allergy vertical-slice service: official template -> validation -> CTA evidence."""

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
import argparse
import json

from .cta_client import CtaSubmissionClient, CtaSubmissionResult
from .compare_official import compare_official
from .dem_resolver import DemographicResolver, ResolvedDemographics
from .export_builder import BuiltExportArtifact, OfficialExportBuilder
from .runtime_injector import RuntimeInjectionContext
from .schematron_validator import OfficialSchematronValidator, SchematronValidationResult
from .template_loader import LOCKED_TACTICAL_TEST_KEY, OfficialTemplateLoader, SUPPORTED_CASE_ID
from .xsd_validator import OfficialXsdValidator, XsdValidationResult


@dataclass(frozen=True)
class AllergyVerticalSliceResult:
    """Complete result payload for the authoritative Allergy CTA vertical slice."""

    case_id: str
    tactical_test_key: str
    demographic_values: dict[str, Any]
    artifact_path: str
    unresolved_placeholders: list[str]
    repeated_group_counts_before: dict[str, int]
    repeated_group_counts_after: dict[str, int]
    xsd_validation: dict[str, Any]
    schematron_validation: dict[str, Any]
    cta_submission: dict[str, Any]
    xsd_result_path: str
    schematron_result_path: str
    fidelity_result_path: str
    cta_request_path: str
    cta_response_path: str
    cta_parsed_result_path: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize the result into a JSON-safe dictionary.

        Args:
            None.

        Returns:
            JSON-safe dictionary representation.
        """

        return asdict(self)


class AllergyVerticalSliceService:
    """Run the single locked official Allergy NEMSIS CTA pass path end to end."""

    def __init__(
        self,
        template_loader: OfficialTemplateLoader | None = None,
        demographic_resolver: DemographicResolver | None = None,
        export_builder: OfficialExportBuilder | None = None,
        xsd_validator: OfficialXsdValidator | None = None,
        schematron_validator: OfficialSchematronValidator | None = None,
        cta_client: CtaSubmissionClient | None = None,
    ) -> None:
        """Initialize the authoritative vertical-slice dependencies.

        Args:
            template_loader: Optional official template loader.
            demographic_resolver: Optional DEM resolver.
            export_builder: Optional export builder.
            xsd_validator: Optional XSD validator.
            schematron_validator: Optional Schematron validator.
            cta_client: Optional CTA submission client.

        Returns:
            None.
        """

        self._template_loader = template_loader or OfficialTemplateLoader()
        self._demographic_resolver = demographic_resolver or DemographicResolver()
        self._export_builder = export_builder or OfficialExportBuilder()
        self._xsd_validator = xsd_validator or OfficialXsdValidator()
        self._schematron_validator = schematron_validator or OfficialSchematronValidator()
        self._cta_client = cta_client or CtaSubmissionClient()

    async def run(
        self,
        *,
        case_id: str = SUPPORTED_CASE_ID,
        integration_enabled: bool = False,
        patient_care_report_number: str = "PCR-ALLERGY-2025-0001",
        software_creator: str = "Adaptix EPCR Service",
        software_name: str = "Adaptix EPCR Allergy CTA Slice",
        software_version: str = "3.5.1",
    ) -> AllergyVerticalSliceResult:
        """Execute the locked official Allergy slice from template load to CTA evidence.

        Args:
            case_id: Requested official case identifier.
            integration_enabled: Explicit gate for live CTA submission.
            patient_care_report_number: Runtime PCR number for `eRecord.01`.
            software_creator: Runtime software creator for `eRecord.02`.
            software_name: Runtime software name for `eRecord.03`.
            software_version: Runtime software version for `eRecord.04`.

        Returns:
            AllergyVerticalSliceResult containing artifact, validation, and CTA evidence.

        Raises:
            ValueError: If unsupported placeholders remain or structure preservation fails.
            RuntimeError: If CTA submission is requested without prerequisites.
        """

        loaded_template = self._template_loader.load(case_id=case_id)
        demographics = self._demographic_resolver.resolve(
            dem_root=loaded_template.dem_root,
            state_root=loaded_template.state_root,
            dem_vendor_html_text=loaded_template.dem_vendor_html_text,
            ems_root=loaded_template.ems_root,
        )
        built_artifact = self._export_builder.build(
            loaded_template=loaded_template,
            context=RuntimeInjectionContext(
                demographics=demographics,
                patient_care_report_number=patient_care_report_number,
                software_creator=software_creator,
                software_name=software_name,
                software_version=software_version,
            ),
        )
        self._assert_structure_and_placeholders(built_artifact)
        xsd_validation = self._xsd_validator.validate(built_artifact.xml_bytes)
        schematron_validation = self._schematron_validator.validate(built_artifact.xml_bytes)
        fidelity_result = compare_official(
            loaded_template.paths.ems_xml_path,
            built_artifact.xml_path,
        )
        cta_submission = await self._submit_if_allowed(
            built_artifact=built_artifact,
            xsd_validation=xsd_validation,
            schematron_validation=schematron_validation,
            integration_enabled=integration_enabled,
        )
        artifact_paths = self._write_evidence(
            case_id=case_id,
            demographics=demographics,
            built_artifact=built_artifact,
            xsd_validation=xsd_validation,
            schematron_validation=schematron_validation,
            fidelity_result=fidelity_result,
            cta_submission=cta_submission,
        )
        return AllergyVerticalSliceResult(
            case_id=case_id,
            tactical_test_key=LOCKED_TACTICAL_TEST_KEY,
            demographic_values=asdict(demographics),
            artifact_path=str(built_artifact.xml_path),
            unresolved_placeholders=built_artifact.unresolved_placeholders,
            repeated_group_counts_before=built_artifact.repeated_group_counts_before,
            repeated_group_counts_after=built_artifact.repeated_group_counts_after,
            xsd_validation=asdict(xsd_validation),
            schematron_validation={
                "is_valid": schematron_validation.is_valid,
                "schema_path": schematron_validation.schema_path,
                "compiled_xsl_path": schematron_validation.compiled_xsl_path,
                "svrl_path": schematron_validation.svrl_path,
                "errors": [asdict(issue) for issue in schematron_validation.errors],
                "warnings": [asdict(issue) for issue in schematron_validation.warnings],
            },
            cta_submission=cta_submission.to_dict(),
            xsd_result_path=str(artifact_paths["xsd_result_path"]),
            schematron_result_path=str(artifact_paths["schematron_result_path"]),
            fidelity_result_path=str(artifact_paths["fidelity_result_path"]),
            cta_request_path=str(artifact_paths["cta_request_path"]),
            cta_response_path=str(artifact_paths["cta_response_path"]),
            cta_parsed_result_path=str(artifact_paths["cta_parsed_result_path"]),
        )

    @staticmethod
    def _assert_structure_and_placeholders(built_artifact: BuiltExportArtifact) -> None:
        """Enforce placeholder removal and repeating-group preservation invariants.

        Args:
            built_artifact: Built export artifact metadata.

        Returns:
            None.

        Raises:
            ValueError: If unresolved placeholders remain or repeated groups changed.
        """

        if built_artifact.unresolved_placeholders:
            raise ValueError(
                "Official Allergy export still contains unresolved placeholders: "
                + ", ".join(built_artifact.unresolved_placeholders)
            )
        if built_artifact.repeated_group_counts_before != built_artifact.repeated_group_counts_after:
            raise ValueError("Repeated group structure drift detected while building the official Allergy export.")

    async def _submit_if_allowed(
        self,
        *,
        built_artifact: BuiltExportArtifact,
        xsd_validation: XsdValidationResult,
        schematron_validation: SchematronValidationResult,
        integration_enabled: bool,
    ) -> CtaSubmissionResult:
        """Submit to CTA only when validation passes and integration is explicitly enabled.

        Args:
            built_artifact: Built XML artifact.
            xsd_validation: XSD validation result.
            schematron_validation: Schematron validation result.
            integration_enabled: Explicit live-submission flag.

        Returns:
            CTA submission result.

        Raises:
            RuntimeError: If live submission is requested for an invalid artifact.
        """

        if integration_enabled and (not xsd_validation.is_valid or not schematron_validation.is_valid):
            raise RuntimeError("CTA submission is blocked because the Allergy XML did not pass local XSD and Schematron validation.")
        return await self._cta_client.submit(
            built_artifact.xml_bytes,
            integration_enabled=integration_enabled,
            data_schema="61",
            submission_label=f"TAC-{SUPPORTED_CASE_ID}",
        )

    def _write_evidence(
        self,
        *,
        case_id: str,
        demographics: ResolvedDemographics,
        built_artifact: BuiltExportArtifact,
        xsd_validation: XsdValidationResult,
        schematron_validation: SchematronValidationResult,
        fidelity_result: dict[str, Any],
        cta_submission: CtaSubmissionResult,
    ) -> dict[str, Path]:
        """Persist JSON and CTA evidence artifacts for the full vertical-slice execution.

        Args:
            case_id: Official case identifier.
            demographics: Resolved demographic metadata.
            built_artifact: Built XML artifact.
            xsd_validation: XSD validation result.
            schematron_validation: Schematron validation result.
            cta_submission: CTA submission result.

        Returns:
            Mapping of persisted artifact paths.
        """

        backend_root = Path(__file__).resolve().parents[3]
        validation_dir = backend_root / "artifact" / "validation"
        fidelity_dir = backend_root / "artifact" / "fidelity"
        cta_dir = backend_root / "artifact" / "cta"
        validation_dir.mkdir(parents=True, exist_ok=True)
        fidelity_dir.mkdir(parents=True, exist_ok=True)
        cta_dir.mkdir(parents=True, exist_ok=True)

        xsd_result_path = validation_dir / "xsd-result.json"
        schematron_result_path = validation_dir / "schematron-result.json"
        fidelity_result_path = fidelity_dir / "official-diff.json"
        cta_request_path = cta_dir / f"{case_id}-request.xml"
        cta_response_path = cta_dir / f"{case_id}-response.xml"
        cta_parsed_result_path = cta_dir / "parsed-result.json"

        xsd_result_path.write_text(json.dumps(asdict(xsd_validation), indent=2), encoding="utf-8")
        schematron_result_path.write_text(
            json.dumps(
                {
                    "is_valid": schematron_validation.is_valid,
                    "schema_path": schematron_validation.schema_path,
                    "compiled_xsl_path": schematron_validation.compiled_xsl_path,
                    "svrl_path": schematron_validation.svrl_path,
                    "errors": [asdict(issue) for issue in schematron_validation.errors],
                    "warnings": [asdict(issue) for issue in schematron_validation.warnings],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        fidelity_result_path.write_text(json.dumps(fidelity_result, indent=2), encoding="utf-8")
        cta_request_path.write_text(
            cta_submission.request_body or "<ctaSubmissionBlocked reason=\"missing_credentials\" />",
            encoding="utf-8",
        )
        cta_response_path.write_text(
            cta_submission.response_body
            or (
                "<ctaSubmissionBlocked>CTA NETWORK SUBMISSION BLOCKED — MISSING CREDENTIALS</ctaSubmissionBlocked>"
                if cta_submission.response_status == "blocked"
                else "<ctaSubmissionSkipped />"
            ),
            encoding="utf-8",
        )
        cta_parsed_result_path.write_text(json.dumps(cta_submission.to_dict(), indent=2), encoding="utf-8")

        return {
            "xsd_result_path": xsd_result_path,
            "schematron_result_path": schematron_result_path,
            "fidelity_result_path": fidelity_result_path,
            "cta_request_path": cta_request_path,
            "cta_response_path": cta_response_path,
            "cta_parsed_result_path": cta_parsed_result_path,
        }


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the official Allergy CTA vertical slice.")
    parser.add_argument("--case", default=SUPPORTED_CASE_ID, help="Official case identifier.")
    parser.add_argument("--submit", action="store_true", help="Attempt CTA submission after local validation passes.")
    return parser


def _print_result_summary(result: AllergyVerticalSliceResult) -> None:
    print(json.dumps(result.to_dict(), indent=2))


async def _main_async() -> int:
    args = _build_cli_parser().parse_args()
    result = await AllergyVerticalSliceService().run(
        case_id=args.case,
        integration_enabled=args.submit,
    )
    _print_result_summary(result)
    if not result.xsd_validation["is_valid"] or not result.schematron_validation["is_valid"]:
        return 1
    if args.submit and result.cta_submission["status_code"] != "1":
        return 2
    return 0


def main() -> int:
    import asyncio

    return asyncio.run(_main_async())


if __name__ == "__main__":
    raise SystemExit(main())
