"""Care domain business services for ePCR and NEMSIS 3.5.1 compliance.

This module provides core business logic for managing ePCR charts, including
chart lifecycle management, clinical data recording, and NEMSIS 3.5.1 compliance
validation and tracking. All operations log activity and failures for audit trails.
"""
import uuid
import json
import logging
from datetime import datetime, UTC
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from epcr_app.models import Chart, Vitals, Assessment, NemsisMappingRecord, NemsisCompliance, ComplianceStatus, FieldSource

logger = logging.getLogger(__name__)


NEMSIS_MANDATORY_FIELDS = {
    "eRecord.01": "Patient Care Report Number",
    "eRecord.02": "Software Creator",
    "eRecord.03": "Software Name",
    "eRecord.04": "Software Version",
    "eResponse.01": "EMS Agency Number",
    "eResponse.03": "Incident Number",
    "eResponse.04": "EMS Response Number",
    "eResponse.05": "Type of Service Requested",
    "eTimes.01": "Time Incident Report Called In",
    "eTimes.02": "Time Unit Dispatched",
    "eTimes.03": "Time Unit On Scene",
    "eTimes.04": "Time Unit Left Scene",
    "eTimes.05": "Time at Destination",
}


class ChartService:
    """ePCR chart lifecycle and NEMSIS 3.5.1 compliance management.
    
    Provides methods for creating charts, recording clinical data,
    tracking NEMSIS compliance, and managing chart state transitions.
    All operations include logging and validation.
    """

    @staticmethod
    async def create_chart(
        session: AsyncSession,
        tenant_id: str,
        call_number: str,
        incident_type: str,
        created_by_user_id: str,
        patient_id: str = None
    ) -> Chart:
        """Create new ePCR chart with NEMSIS compliance tracking.
        
        Args:
            session: AsyncSession for database operations.
            tenant_id: Tenant identifier for multi-tenant isolation.
            call_number: Unique call/dispatch number (must be non-empty).
            incident_type: Type of incident (medical, trauma, behavioral, other).
            created_by_user_id: User ID of chart creator (must be non-empty).
            patient_id: Optional patient identifier.
            
        Returns:
            Chart: Created chart object with NEMSIS compliance record.
            
        Raises:
            ValueError: If validation fails (empty fields, invalid incident_type).
            SQLAlchemyError: If database operation fails.
        """
        if not tenant_id or not isinstance(tenant_id, str) or len(tenant_id.strip()) == 0:
            logger.warning("Chart creation rejected: invalid tenant_id")
            raise ValueError("tenant_id is required and cannot be empty")
        
        if not call_number or not isinstance(call_number, str) or len(call_number.strip()) == 0:
            logger.warning(f"Chart creation rejected for tenant {tenant_id}: invalid call_number")
            raise ValueError("call_number is required and cannot be empty")
        
        if not created_by_user_id or not isinstance(created_by_user_id, str) or len(created_by_user_id.strip()) == 0:
            logger.warning("Chart creation rejected: invalid created_by_user_id")
            raise ValueError("created_by_user_id is required and cannot be empty")
        
        valid_incident_types = ["medical", "trauma", "behavioral", "other"]
        if incident_type not in valid_incident_types:
            logger.warning(f"Chart creation rejected: invalid incident_type '{incident_type}'")
            raise ValueError(f"incident_type must be one of: {', '.join(valid_incident_types)}")
        
        try:
            chart = Chart(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id.strip(),
                call_number=call_number.strip(),
                incident_type=incident_type,
                created_by_user_id=created_by_user_id.strip(),
                patient_id=patient_id
            )
            session.add(chart)
            
            compliance = NemsisCompliance(
                id=str(uuid.uuid4()),
                chart_id=chart.id,
                tenant_id=tenant_id.strip(),
                mandatory_fields_required=len(NEMSIS_MANDATORY_FIELDS),
                missing_mandatory_fields=json.dumps(list(NEMSIS_MANDATORY_FIELDS.keys()))
            )
            session.add(compliance)
            
            await session.commit()
            logger.info(f"Chart created: id={chart.id}, call_number={call_number}, incident_type={incident_type}, tenant_id={tenant_id}")
            return chart
        except SQLAlchemyError as e:
            logger.error(f"Database error creating chart for tenant {tenant_id}: {str(e)}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Unexpected error creating chart: {str(e)}", exc_info=True)
            raise

    @staticmethod
    async def get_chart(session: AsyncSession, tenant_id: str, chart_id: str) -> Chart:
        """Retrieve chart by ID.
        
        Args:
            session: AsyncSession for database operations.
            tenant_id: Tenant identifier (enforces tenant isolation).
            chart_id: Chart identifier to retrieve.
            
        Returns:
            Chart: Chart object if found, None otherwise.
            
        Raises:
            SQLAlchemyError: If database query fails.
        """
        try:
            result = await session.execute(
                select(Chart).where(
                    and_(
                        Chart.id == chart_id,
                        Chart.tenant_id == tenant_id,
                        Chart.deleted_at.is_(None)
                    )
                )
            )
            chart = result.scalars().first()
            if chart:
                logger.debug(f"Retrieved chart: id={chart_id}, tenant_id={tenant_id}")
            else:
                logger.debug(f"Chart not found: id={chart_id}, tenant_id={tenant_id}")
            return chart
        except SQLAlchemyError as e:
            logger.error(f"Database error retrieving chart {chart_id}: {str(e)}", exc_info=True)
            raise

    @staticmethod
    async def check_nemsis_compliance(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str
    ) -> dict:
        """Check NEMSIS 3.5.1 compliance for chart.
        
        Validates chart against mandatory NEMSIS 3.5.1 fields and returns
        detailed compliance status, including percentage filled and list
        of missing required fields.
        
        Args:
            session: AsyncSession for database operations.
            tenant_id: Tenant identifier (enforces tenant isolation).
            chart_id: Chart identifier to check.
            
        Returns:
            dict: Compliance status with keys:
                - chart_id: Chart identifier
                - compliance_status: Current compliance status
                - compliance_percentage: Percentage of mandatory fields filled
                - mandatory_fields_filled: Count of populated mandatory fields
                - mandatory_fields_required: Total mandatory fields
                - missing_mandatory_fields: List of missing field IDs
                - is_fully_compliant: Boolean indicating full compliance
                
        Raises:
            ValueError: If chart not found.
            SQLAlchemyError: If database operation fails.
        """
        try:
            chart = await ChartService.get_chart(session, tenant_id, chart_id)
            if not chart:
                logger.warning(f"Compliance check failed: chart not found (id={chart_id}, tenant_id={tenant_id})")
                raise ValueError(f"Chart {chart_id} not found")

            result = await session.execute(
                select(NemsisMappingRecord).where(
                    and_(
                        NemsisMappingRecord.chart_id == chart_id,
                        NemsisMappingRecord.nemsis_value.isnot(None)
                    )
                )
            )
            populated = {r.nemsis_field for r in result.scalars().all()}
            missing = [f for f in NEMSIS_MANDATORY_FIELDS.keys() if f not in populated]
            
            filled = len(NEMSIS_MANDATORY_FIELDS) - len(missing)
            total = len(NEMSIS_MANDATORY_FIELDS)
            percentage = (filled / total * 100) if total > 0 else 0
            
            if filled == 0:
                status = ComplianceStatus.NOT_STARTED
            elif not missing:
                status = ComplianceStatus.FULLY_COMPLIANT
            elif percentage >= 75:
                status = ComplianceStatus.PARTIALLY_COMPLIANT
            else:
                status = ComplianceStatus.IN_PROGRESS
            
            compliance_result = await session.execute(
                select(NemsisCompliance).where(NemsisCompliance.chart_id == chart_id)
            )
            compliance = compliance_result.scalars().first()
            
            if compliance:
                compliance.compliance_status = status
                compliance.mandatory_fields_filled = filled
                compliance.missing_mandatory_fields = json.dumps(missing)
                compliance.compliance_checked_at = datetime.now(UTC)
                await session.commit()
                logger.info(f"Compliance updated: chart_id={chart_id}, status={status.value}, percentage={percentage:.1f}%")
            
            return {
                "chart_id": chart_id,
                "compliance_status": status.value,
                "compliance_percentage": round(percentage, 2),
                "mandatory_fields_filled": filled,
                "mandatory_fields_required": total,
                "missing_mandatory_fields": missing,
                "is_fully_compliant": status == ComplianceStatus.FULLY_COMPLIANT
            }
        except ValueError:
            raise
        except SQLAlchemyError as e:
            logger.error(f"Database error checking compliance for chart {chart_id}: {str(e)}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Unexpected error checking compliance: {str(e)}", exc_info=True)
            raise

    @staticmethod
    async def update_chart(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        update_data: dict
    ) -> Chart:
        """Update ePCR chart fields (incident_type, patient_id, vitals, assessment).
        
        Applies partial field updates to a chart, including optional vitals and
        assessment data. Updates chart.updated_at timestamp. Enforces tenant
        isolation and soft-delete filtering.
        
        Args:
            session: AsyncSession for database operations.
            tenant_id: Tenant identifier (enforces tenant isolation).
            chart_id: Chart identifier to update.
            update_data: Dict with optional keys:
                - incident_type: str (medical, trauma, behavioral, other)
                - patient_id: str (optional patient identifier)
                - bp_sys, bp_dia, hr, rr, temp_f, spo2, glucose: vitals data
                - chief_complaint, field_diagnosis: assessment data
                
        Returns:
            Chart: Updated chart object.
            
        Raises:
            ValueError: If chart not found or update_data is invalid.
            SQLAlchemyError: If database operation fails.
        """
        try:
            chart = await ChartService.get_chart(session, tenant_id, chart_id)
            if not chart:
                logger.warning(f"Update chart rejected: chart not found (id={chart_id}, tenant_id={tenant_id})")
                raise ValueError(f"Chart {chart_id} not found")
            
            # Update Chart fields if present
            if "incident_type" in update_data and update_data["incident_type"] is not None:
                incident_type = update_data["incident_type"]
                valid_types = ["medical", "trauma", "behavioral", "other"]
                if incident_type not in valid_types:
                    logger.warning(f"Update rejected: invalid incident_type '{incident_type}'")
                    raise ValueError(f"incident_type must be one of: {', '.join(valid_types)}")
                chart.incident_type = incident_type
            
            if "patient_id" in update_data and update_data["patient_id"] is not None:
                chart.patient_id = update_data["patient_id"]
            
            # Update or create Vitals if any vital fields are present
            vital_fields = {"bp_sys", "bp_dia", "hr", "rr", "temp_f", "spo2", "glucose"}
            has_vital_update = any(k in update_data for k in vital_fields)
            
            if has_vital_update:
                result = await session.execute(
                    select(Vitals).where(
                        and_(
                            Vitals.chart_id == chart_id,
                            Vitals.deleted_at.is_(None)
                        )
                    )
                )
                vitals = result.scalars().first()
                
                if not vitals:
                    vitals = Vitals(
                        id=str(uuid.uuid4()),
                        chart_id=chart_id,
                        tenant_id=tenant_id,
                        recorded_at=datetime.now(UTC)
                    )
                    session.add(vitals)
                
                for field in vital_fields:
                    if field in update_data and update_data[field] is not None:
                        setattr(vitals, field, update_data[field])
            
            # Update or create Assessment if assessment fields are present
            assessment_fields = {"chief_complaint", "field_diagnosis"}
            has_assessment_update = any(k in update_data for k in assessment_fields)
            
            if has_assessment_update:
                result = await session.execute(
                    select(Assessment).where(
                        and_(
                            Assessment.chart_id == chart_id,
                            Assessment.deleted_at.is_(None)
                        )
                    )
                )
                assessment = result.scalars().first()
                
                if not assessment:
                    assessment = Assessment(
                        id=str(uuid.uuid4()),
                        chart_id=chart_id,
                        tenant_id=tenant_id,
                        documented_at=datetime.now(UTC)
                    )
                    session.add(assessment)
                
                for field in assessment_fields:
                    if field in update_data and update_data[field] is not None:
                        setattr(assessment, field, update_data[field])
            
            # Update chart timestamp
            chart.updated_at = datetime.now(UTC)
            
            await session.commit()
            logger.info(f"Chart updated: id={chart_id}, tenant_id={tenant_id}, fields_updated={list(update_data.keys())}")
            return chart
        except ValueError:
            raise
        except SQLAlchemyError as e:
            logger.error(f"Database error updating chart {chart_id}: {str(e)}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Unexpected error updating chart: {str(e)}", exc_info=True)
            raise

    @staticmethod
    async def record_nemsis_field(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        nemsis_field: str,
        nemsis_value: str,
        source: str = "manual"
    ) -> "NemsisMappingRecord":
        """Record or update a single NEMSIS field value for a chart.

        Creates a new NemsisMappingRecord if the field does not exist for this
        chart, or updates the existing record if it does. Updates compliance
        status after recording. Raises ValueError if chart not found.

        Args:
            session: AsyncSession for database operations.
            tenant_id: Tenant identifier (enforces tenant isolation).
            chart_id: Chart identifier.
            nemsis_field: NEMSIS field identifier (e.g. 'eRecord.01').
            nemsis_value: Value to record for this field.
            source: Source of value: manual, ocr, device, or system.

        Returns:
            NemsisMappingRecord: Created or updated mapping record.

        Raises:
            ValueError: If chart not found or source is invalid.
            SQLAlchemyError: If database operation fails.
        """
        valid_sources = {"manual", "ocr", "device", "system"}
        if source not in valid_sources:
            raise ValueError(f"source must be one of: {', '.join(sorted(valid_sources))}")

        chart = await ChartService.get_chart(session, tenant_id, chart_id)
        if not chart:
            raise ValueError(f"Chart {chart_id} not found")

        try:
            existing = await session.execute(
                select(NemsisMappingRecord).where(
                    and_(
                        NemsisMappingRecord.chart_id == chart_id,
                        NemsisMappingRecord.nemsis_field == nemsis_field
                    )
                )
            )
            record = existing.scalars().first()

            if record:
                record.nemsis_value = nemsis_value
                record.source = FieldSource(source)
                record.updated_at = datetime.now(UTC)
            else:
                record = NemsisMappingRecord(
                    id=str(uuid.uuid4()),
                    chart_id=chart_id,
                    tenant_id=tenant_id.strip(),
                    nemsis_field=nemsis_field,
                    nemsis_value=nemsis_value,
                    source=FieldSource(source)
                )
                session.add(record)

            await session.commit()
            logger.info(
                f"NEMSIS field recorded: chart_id={chart_id}, field={nemsis_field}, source={source}"
            )
            return record
        except SQLAlchemyError as e:
            logger.error(f"Database error recording NEMSIS field for chart {chart_id}: {str(e)}", exc_info=True)
            raise

    @staticmethod
    async def record_export(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        exported_by_user_id: str,
        export_status: str,
        export_payload: dict,
        error_message: str = None,
    ) -> "NemsisExportHistory":
        """Record a NEMSIS export attempt in the export history table.

        Args:
            session: AsyncSession for database operations.
            tenant_id: Tenant identifier.
            chart_id: Chart identifier.
            exported_by_user_id: User who triggered the export.
            export_status: 'success' or 'failed'.
            export_payload: Dict of NEMSIS fields at time of export.
            error_message: Error detail if export failed (optional).

        Returns:
            NemsisExportHistory: Created export history record.

        Raises:
            SQLAlchemyError: If database operation fails.
        """
        import json as _json
        from epcr_app.models import NemsisExportHistory
        record = NemsisExportHistory(
            id=str(uuid.uuid4()),
            chart_id=chart_id,
            tenant_id=tenant_id,
            exported_by_user_id=exported_by_user_id,
            export_status=export_status,
            export_payload_json=_json.dumps(export_payload) if export_payload else None,
            error_message=error_message,
        )
        session.add(record)
        await session.commit()
        logger.info(
            f"Export recorded: chart_id={chart_id}, status={export_status}, "
            f"user={exported_by_user_id}"
        )
        return record

    @staticmethod
    async def audit(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        user_id: str,
        action: str,
        detail: dict = None,
    ) -> None:
        """Write an audit log entry for an ePCR chart action.

        Args:
            session: AsyncSession for database operations.
            tenant_id: Tenant identifier.
            chart_id: Chart identifier.
            user_id: User performing the action.
            action: Action type (create, update, finalize, export, compliance_check).
            detail: Optional dict with additional context.
        """
        import json as _json
        from epcr_app.models import EpcrAuditLog
        entry = EpcrAuditLog(
            id=str(uuid.uuid4()),
            chart_id=chart_id,
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            detail_json=_json.dumps(detail) if detail else None,
        )
        session.add(entry)
        await session.commit()
        logger.info(f"Audit: chart_id={chart_id}, action={action}, user={user_id}")
