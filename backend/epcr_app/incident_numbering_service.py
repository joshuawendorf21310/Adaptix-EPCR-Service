"""Deterministic tenant + agency + year-scoped visible chart numbering."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models import AgencyProfile, Chart, EpcrNumberingSequence


AGENCY_CODE_RE = re.compile(r"^[A-Z0-9]{2,12}$")
INCIDENT_NUMBER_RE = re.compile(r"^[0-9]{4}-[A-Z0-9]{2,12}-[0-9]{6}$")
RESPONSE_NUMBER_RE = re.compile(r"^[0-9]{4}-[A-Z0-9]{2,12}-[0-9]{6}-R[0-9]{2}$")
PCR_NUMBER_RE = re.compile(r"^[0-9]{4}-[A-Z0-9]{2,12}-[0-9]{6}-PCR[0-9]{2}$")
BILLING_CASE_NUMBER_RE = re.compile(r"^[0-9]{4}-[A-Z0-9]{2,12}-[0-9]{6}-BILL[0-9]{2}$")


class AgencyCodeMissingError(ValueError):
    pass


class AgencyCodeInvalidError(ValueError):
    pass


class AgencyCodeInactiveError(ValueError):
    pass


@dataclass(slots=True)
class IncidentNumberBundle:
    agency_code: str
    incident_year: int
    incident_sequence: int
    incident_number: str
    response_sequence: int
    response_number: str
    pcr_sequence: int
    pcr_number: str
    billing_sequence: int
    billing_case_number: str


class IncidentNumberingService:
    """Generate deterministic visible identifiers for ePCR charts."""

    @staticmethod
    def validate_agency_code(agency_code: str) -> str:
        normalized = (agency_code or "").strip().upper()
        if not AGENCY_CODE_RE.fullmatch(normalized):
            raise AgencyCodeInvalidError(
                "agency_code must match ^[A-Z0-9]{2,12}$"
            )
        return normalized

    @staticmethod
    async def resolve_agency_profile(
        session: AsyncSession,
        tenant_id: str,
        agency_id: str | None = None,
        agency_code: str | None = None,
    ) -> AgencyProfile:
        stmt = select(AgencyProfile).where(
            and_(
                AgencyProfile.tenant_id == tenant_id,
                AgencyProfile.deleted_at.is_(None),
            )
        )
        if agency_id:
            stmt = stmt.where(AgencyProfile.id == agency_id)
        elif agency_code:
            stmt = stmt.where(
                AgencyProfile.agency_code
                == IncidentNumberingService.validate_agency_code(agency_code)
            )

        result = await session.execute(stmt.order_by(AgencyProfile.created_at.asc()))
        profiles = list(result.scalars().all())
        if agency_id or agency_code:
            profile = profiles[0] if profiles else None
        else:
            profile = profiles[0] if len(profiles) == 1 else None

        if profile is None:
            raise AgencyCodeMissingError(
                "agency_code is missing for this activated agency; onboarding/provisioning must store it before chart creation"
            )
        if profile.activated_at is None:
            raise AgencyCodeInactiveError(
                f"agency_code {profile.agency_code} is not activated yet"
            )
        IncidentNumberingService.validate_agency_code(profile.agency_code)
        return profile

    @staticmethod
    async def generate_incident_number(
        session: AsyncSession,
        tenant_id: str,
        agency_code: str,
        incident_datetime: datetime | None = None,
    ) -> IncidentNumberBundle:
        agency_code = IncidentNumberingService.validate_agency_code(agency_code)
        incident_dt = incident_datetime or datetime.now(UTC)
        incident_year = incident_dt.year

        sequence_result = await session.execute(
            select(EpcrNumberingSequence)
            .where(
                and_(
                    EpcrNumberingSequence.tenant_id == tenant_id,
                    EpcrNumberingSequence.agency_code == agency_code,
                    EpcrNumberingSequence.sequence_year == incident_year,
                )
            )
            .with_for_update()
        )
        sequence = sequence_result.scalars().first()
        if sequence is None:
            sequence = EpcrNumberingSequence(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                agency_code=agency_code,
                sequence_year=incident_year,
                next_incident_sequence=1,
            )
            session.add(sequence)
            await session.flush()

        incident_sequence = int(sequence.next_incident_sequence)
        sequence.next_incident_sequence = incident_sequence + 1
        sequence.updated_at = datetime.now(UTC)

        incident_number = f"{incident_year}-{agency_code}-{incident_sequence:06d}"
        response_sequence = 1
        pcr_sequence = 1
        billing_sequence = 1
        response_number = f"{incident_number}-R{response_sequence:02d}"
        pcr_number = f"{incident_number}-PCR{pcr_sequence:02d}"
        billing_case_number = f"{incident_number}-BILL{billing_sequence:02d}"

        IncidentNumberingService._validate_number_formats(
            incident_number=incident_number,
            response_number=response_number,
            pcr_number=pcr_number,
            billing_case_number=billing_case_number,
        )

        return IncidentNumberBundle(
            agency_code=agency_code,
            incident_year=incident_year,
            incident_sequence=incident_sequence,
            incident_number=incident_number,
            response_sequence=response_sequence,
            response_number=response_number,
            pcr_sequence=pcr_sequence,
            pcr_number=pcr_number,
            billing_sequence=billing_sequence,
            billing_case_number=billing_case_number,
        )

    @staticmethod
    async def generate_response_number(
        session: AsyncSession,
        tenant_id: str,
        incident_number: str,
    ) -> str:
        return await IncidentNumberingService._generate_child_number(
            session=session,
            tenant_id=tenant_id,
            incident_number=incident_number,
            field_name="response_sequence",
            suffix_template="R{sequence:02d}",
            validator=RESPONSE_NUMBER_RE,
        )

    @staticmethod
    async def generate_pcr_number(
        session: AsyncSession,
        tenant_id: str,
        incident_number: str,
    ) -> str:
        return await IncidentNumberingService._generate_child_number(
            session=session,
            tenant_id=tenant_id,
            incident_number=incident_number,
            field_name="pcr_sequence",
            suffix_template="PCR{sequence:02d}",
            validator=PCR_NUMBER_RE,
        )

    @staticmethod
    async def generate_billing_case_number(
        session: AsyncSession,
        tenant_id: str,
        incident_number: str,
    ) -> str:
        return await IncidentNumberingService._generate_child_number(
            session=session,
            tenant_id=tenant_id,
            incident_number=incident_number,
            field_name="billing_sequence",
            suffix_template="BILL{sequence:02d}",
            validator=BILLING_CASE_NUMBER_RE,
        )

    @staticmethod
    async def _generate_child_number(
        session: AsyncSession,
        tenant_id: str,
        incident_number: str,
        field_name: str,
        suffix_template: str,
        validator: re.Pattern[str],
    ) -> str:
        if not INCIDENT_NUMBER_RE.fullmatch(incident_number):
            raise ValueError("incident_number must match ^[0-9]{4}-[A-Z0-9]{2,12}-[0-9]{6}$")

        field = getattr(Chart, field_name)
        result = await session.execute(
            select(func.max(field)).where(
                and_(
                    Chart.tenant_id == tenant_id,
                    Chart.incident_number == incident_number,
                    Chart.deleted_at.is_(None),
                )
            )
        )
        next_sequence = int(result.scalar() or 0) + 1
        number = f"{incident_number}-{suffix_template.format(sequence=next_sequence)}"
        if not validator.fullmatch(number):
            raise ValueError(f"generated child number is invalid: {number}")
        return number

    @staticmethod
    def default_numbering_policy(agency_code: str) -> dict[str, object]:
        return {
            "agencyCode": agency_code,
            "incidentFormat": "{YYYY}-{AGENCY}-{SEQ6}",
            "responseFormat": "{INCIDENT}-R{SEQ2}",
            "pcrFormat": "{INCIDENT}-PCR{SEQ2}",
            "billingFormat": "{INCIDENT}-BILL{SEQ2}",
            "incidentNumberSource": "adaptix_generated",
            "resetFrequency": "yearly",
            "sequencePadding": 6,
            "childSequencePadding": 2,
            "allowAdminOverride": True,
        }

    @staticmethod
    def parse_numbering_policy(profile: AgencyProfile) -> dict[str, object]:
        if profile.numbering_policy_json:
            try:
                return json.loads(profile.numbering_policy_json)
            except json.JSONDecodeError:
                pass
        return IncidentNumberingService.default_numbering_policy(profile.agency_code)

    @staticmethod
    def _validate_number_formats(
        incident_number: str,
        response_number: str,
        pcr_number: str,
        billing_case_number: str,
    ) -> None:
        validators = (
            (INCIDENT_NUMBER_RE, incident_number, "incident_number"),
            (RESPONSE_NUMBER_RE, response_number, "response_number"),
            (PCR_NUMBER_RE, pcr_number, "pcr_number"),
            (BILLING_CASE_NUMBER_RE, billing_case_number, "billing_case_number"),
        )
        for validator, value, label in validators:
            if not validator.fullmatch(value):
                raise ValueError(f"{label} has invalid format: {value}")