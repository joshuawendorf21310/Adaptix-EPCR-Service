"""Shared chart finalization service.

Uses the existing deterministic NEMSIS compliance check, XML builder, and
Schematron finalization gate. No parallel validator path is introduced.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models import Chart, ChartStatus, NemsisMappingRecord
from epcr_app.nemsis_finalization_gate import (
    SchematronFinalizationGate,
    SchematronGateEvaluation,
)
from epcr_app.nemsis_xml_builder import NemsisBuildError, NemsisXmlBuilder
from epcr_app.services import ChartService
from epcr_app.tac_schematron_package_service import TacSchematronPackageService

logger = logging.getLogger(__name__)


class ChartFinalizationError(Exception):
    """Structured finalization error surfaced by API and workspace layers."""

    def __init__(self, message: str, *, status_code: int, detail: dict) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class ChartFinalizationResult:
    chart: Chart
    compliance: dict
    schematron: SchematronGateEvaluation
    provenance: dict[str, Any]


class ChartFinalizationService:
    """Canonical chart finalization path with deterministic Schematron gating."""

    @staticmethod
    async def finalize_chart(
        session: AsyncSession,
        *,
        tenant_id: str,
        user_id: str,
        chart_id: str,
    ) -> ChartFinalizationResult:
        chart = await ChartService.get_chart(session, tenant_id, chart_id)
        if not chart:
            raise ChartFinalizationError(
                "Chart not found",
                status_code=404,
                detail={"message": "Chart not found"},
            )

        compliance = await ChartService.check_nemsis_compliance(session, tenant_id, chart_id)
        if not compliance.get("is_fully_compliant"):
            raise ChartFinalizationError(
                "Chart cannot be finalized: NEMSIS 3.5.1 compliance incomplete",
                status_code=422,
                detail={
                    "message": "Chart cannot be finalized: NEMSIS 3.5.1 compliance incomplete",
                    "missing_mandatory_fields": compliance.get("missing_mandatory_fields", []),
                    "compliance_percentage": compliance.get("compliance_percentage", 0),
                },
            )

        xml_bytes = await ChartFinalizationService._build_chart_xml(
            session,
            tenant_id=tenant_id,
            chart_id=chart_id,
        )
        schematron, provenance = await ChartFinalizationService._evaluate_schematron(
            session,
            tenant_id=tenant_id,
            xml_bytes=xml_bytes,
        )
        if schematron.blocked:
            raise ChartFinalizationError(
                "Chart finalization blocked by Schematron errors",
                status_code=422,
                detail={
                    "message": "Chart finalization blocked by Schematron errors",
                    "schematron": {
                        **schematron.to_payload(),
                        "provenance": provenance,
                    },
                },
            )

        if chart.status != ChartStatus.FINALIZED:
            chart.status = ChartStatus.FINALIZED
            chart.finalized_at = datetime.now(UTC)
            chart.updated_at = datetime.now(UTC)
            await session.commit()

        await ChartService.audit(
            session=session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            user_id=user_id,
            action="chart_finalized",
            detail={
                "compliance_percentage": compliance.get("compliance_percentage"),
                "mandatory_fields_filled": compliance.get("mandatory_fields_filled"),
                "schematron": {
                    **schematron.to_payload(),
                    "provenance": provenance,
                },
            },
        )

        try:
            from epcr_app.domain_events import publish_chart_finalized_sync

            publish_chart_finalized_sync(
                chart_id,
                tenant_id,
                getattr(chart, "call_number", chart_id),
            )
        except Exception as exc:  # pragma: no cover - non-blocking side effect
            logger.warning("Chart finalization event publication skipped: %s", exc)

        return ChartFinalizationResult(
            chart=chart,
            compliance=compliance,
            schematron=schematron,
            provenance=provenance,
        )

    @staticmethod
    async def _build_chart_xml(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
    ) -> bytes | None:
        chart = await ChartService.get_chart(session, tenant_id, chart_id)
        if chart is None:
            return None

        mappings = list(
            (
                await session.execute(
                    select(NemsisMappingRecord).where(
                        NemsisMappingRecord.chart_id == chart_id,
                        NemsisMappingRecord.tenant_id == tenant_id,
                    )
                )
            ).scalars()
        )

        try:
            xml_bytes, _ = NemsisXmlBuilder(chart=chart, mapping_records=mappings).build()
        except NemsisBuildError as exc:
            logger.warning(
                "Schematron gate XML build unavailable for chart %s tenant %s: %s",
                chart_id,
                tenant_id,
                exc,
            )
            return None
        return xml_bytes

    @staticmethod
    async def _evaluate_schematron(
        session: AsyncSession,
        *,
        tenant_id: str,
        xml_bytes: bytes | None,
    ) -> tuple[SchematronGateEvaluation, dict[str, Any]]:
        resolved = await TacSchematronPackageService(session).resolve_validator_for_xml(
            tenant_id=tenant_id,
            xml_bytes=xml_bytes,
        )
        evaluation = SchematronFinalizationGate().evaluate(
            xml_bytes,
            validator=resolved.validator,
        )
        return evaluation, resolved.provenance.to_payload()
