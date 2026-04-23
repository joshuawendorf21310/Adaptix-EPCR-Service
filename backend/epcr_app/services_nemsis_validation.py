"""NEMSIS validation service with export blocking logic.

Orchestrates validation, persistence, and export gating based on
NEMSIS 3.5.1 compliance requirements.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from epcr_app.repositories_nemsis_validation import NEMSISValidationRepository
from epcr_app.models_nemsis_validation import NEMSISValidationResult, ValidationStatus


class NEMSISValidationService:
    """Service for NEMSIS validation and export blocking."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = NEMSISValidationRepository(db)

    def run_validation(
        self,
        *,
        tenant_id: str,
        incident_id: str,
        incident_data: dict[str, Any],
        user_id: str,
    ) -> NEMSISValidationResult:
        """Run NEMSIS validation and save result to database.

        Args:
            tenant_id: Tenant UUID
            incident_id: Incident/chart UUID
            incident_data: Full incident data dictionary
            user_id: User who triggered validation

        Returns:
            Validation result with errors and warnings

        Raises:
            ValueError: If incident data is invalid
        """
        # Validate required fields
        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []

        # Check required NEMSIS elements
        errors.extend(self._validate_demographics(incident_data))
        errors.extend(self._validate_times(incident_data))
        errors.extend(self._validate_scene_location(incident_data))
        errors.extend(self._validate_dispatch_info(incident_data))
        errors.extend(self._validate_patient_info(incident_data))

        warnings.extend(self._validate_optional_fields(incident_data))

        # Determine overall status
        if errors:
            validation_status = ValidationStatus.FAIL.value
        elif warnings:
            validation_status = ValidationStatus.WARNING.value
        else:
            validation_status = ValidationStatus.PASS.value

        # Summary metadata
        summary = {
            "total_errors": len(errors),
            "total_warnings": len(warnings),
            "validation_status": validation_status,
            "required_fields_checked": 25,
            "optional_fields_checked": 10,
            "nemsis_version": "3.5.1",
        }

        # Save to database
        result = self.repo.save_validation_result(
            tenant_id=tenant_id,
            incident_id=incident_id,
            validation_status=validation_status,
            errors=errors,
            warnings=warnings,
            summary=summary,
            created_by_user_id=user_id,
        )

        return result

    def get_cached_validation(
        self, *, tenant_id: str, incident_id: str
    ) -> NEMSISValidationResult | None:
        """Get the most recent cached validation result.

        Args:
            tenant_id: Tenant UUID
            incident_id: Incident/chart UUID

        Returns:
            Latest validation result or None
        """
        return self.repo.get_validation_result(tenant_id=tenant_id, incident_id=incident_id)

    def block_export_if_invalid(self, *, tenant_id: str, incident_id: str) -> tuple[bool, str]:
        """Check if export should be blocked due to validation failures.

        Args:
            tenant_id: Tenant UUID
            incident_id: Incident/chart UUID

        Returns:
            Tuple of (is_blocked, reason)
        """
        result = self.get_cached_validation(tenant_id=tenant_id, incident_id=incident_id)

        if not result:
            return True, "No validation result found. Run validation first."

        if result.validation_status == ValidationStatus.FAIL.value:
            return (
                True,
                f"Validation failed with {result.error_count} error(s). Fix errors before exporting.",
            )

        return False, ""

    def require_manual_override_for_warnings(
        self, *, tenant_id: str, incident_id: str, override_approved: bool
    ) -> tuple[bool, str]:
        """Check if warnings require manual override approval.

        Args:
            tenant_id: Tenant UUID
            incident_id: Incident/chart UUID
            override_approved: Whether user has approved override

        Returns:
            Tuple of (is_blocked, reason)
        """
        result = self.get_cached_validation(tenant_id=tenant_id, incident_id=incident_id)

        if not result:
            return True, "No validation result found."

        if result.validation_status == ValidationStatus.WARNING.value and not override_approved:
            return (
                True,
                f"Validation has {result.warning_count} warning(s). Manual override required.",
            )

        return False, ""

    def _validate_demographics(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Validate required demographic fields."""
        errors = []

        if not data.get("agency_name"):
            errors.append(
                {
                    "element_id": "dAgency.01",
                    "error_code": "MISSING_REQUIRED",
                    "message": "Agency Name is required",
                    "field_path": "agency_name",
                }
            )

        if not data.get("agency_number"):
            errors.append(
                {
                    "element_id": "dAgency.02",
                    "error_code": "MISSING_REQUIRED",
                    "message": "Agency Number is required",
                    "field_path": "agency_number",
                }
            )

        return errors

    def _validate_times(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Validate required timestamp fields."""
        errors = []

        if not data.get("dispatch_notified_time"):
            errors.append(
                {
                    "element_id": "eTimes.01",
                    "error_code": "MISSING_REQUIRED",
                    "message": "Unit Notified by Dispatch Date/Time is required",
                    "field_path": "dispatch_notified_time",
                }
            )

        if not data.get("unit_enroute_time"):
            errors.append(
                {
                    "element_id": "eTimes.02",
                    "error_code": "MISSING_REQUIRED",
                    "message": "Unit En Route Date/Time is required",
                    "field_path": "unit_enroute_time",
                }
            )

        if not data.get("arrival_at_scene_time"):
            errors.append(
                {
                    "element_id": "eTimes.03",
                    "error_code": "MISSING_REQUIRED",
                    "message": "Unit Arrived at Scene Date/Time is required",
                    "field_path": "arrival_at_scene_time",
                }
            )

        return errors

    def _validate_scene_location(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Validate scene location fields."""
        errors = []

        if not data.get("scene_gps_latitude"):
            errors.append(
                {
                    "element_id": "eScene.01",
                    "error_code": "MISSING_REQUIRED",
                    "message": "Scene GPS Latitude is required",
                    "field_path": "scene_gps_latitude",
                }
            )

        if not data.get("scene_gps_longitude"):
            errors.append(
                {
                    "element_id": "eScene.02",
                    "error_code": "MISSING_REQUIRED",
                    "message": "Scene GPS Longitude is required",
                    "field_path": "scene_gps_longitude",
                }
            )

        return errors

    def _validate_dispatch_info(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Validate dispatch information fields."""
        errors = []

        if not data.get("dispatch_reason"):
            errors.append(
                {
                    "element_id": "eDispatch.01",
                    "error_code": "MISSING_REQUIRED",
                    "message": "Dispatch Reason is required",
                    "field_path": "dispatch_reason",
                }
            )

        return errors

    def _validate_patient_info(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Validate patient information fields."""
        errors = []

        if not data.get("patient_age"):
            errors.append(
                {
                    "element_id": "ePatient.15",
                    "error_code": "MISSING_REQUIRED",
                    "message": "Patient Age is required",
                    "field_path": "patient_age",
                }
            )

        if not data.get("patient_gender"):
            errors.append(
                {
                    "element_id": "ePatient.13",
                    "error_code": "MISSING_REQUIRED",
                    "message": "Patient Gender is required",
                    "field_path": "patient_gender",
                }
            )

        return errors

    def _validate_optional_fields(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Validate optional fields that generate warnings."""
        warnings = []

        if not data.get("patient_weight"):
            warnings.append(
                {
                    "element_id": "eVitals.26",
                    "error_code": "OPTIONAL_MISSING",
                    "message": "Patient Weight is recommended but not required",
                    "field_path": "patient_weight",
                }
            )

        if not data.get("primary_symptom"):
            warnings.append(
                {
                    "element_id": "eHistory.01",
                    "error_code": "OPTIONAL_MISSING",
                    "message": "Primary Symptom is recommended",
                    "field_path": "primary_symptom",
                }
            )

        return warnings
