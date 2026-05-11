"""Tenant-scoped repeat-patient registry service.

Builds a registry profile from chart-owned patient demographics without
storing plaintext high-risk identifiers such as phone numbers.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models import (
    PatientProfile,
    PatientRegistryChartLink,
    PatientRegistryIdentifier,
    PatientRegistryProfile,
)


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _hash_key_path() -> Path:
    configured = os.environ.get("EPCR_REGISTRY_HASH_KEY_PATH", "").strip()
    if configured:
        return Path(configured)
    return _backend_root() / ".local" / "patient_registry" / "hash-key.txt"


def _get_hash_key() -> str:
    configured = os.environ.get("EPCR_REGISTRY_HASH_KEY", "").strip()
    if configured:
        return configured

    secret_path = _hash_key_path()
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    if secret_path.exists():
        return secret_path.read_text(encoding="utf-8").strip()

    secret_value = secrets.token_urlsafe(64)
    secret_path.write_text(secret_value, encoding="utf-8")
    return secret_value


@dataclass(slots=True)
class PatientRegistrySearchResult:
    profile_id: str
    canonical_patient_key: str | None
    first_name: str | None
    last_name: str | None
    date_of_birth: str | None
    sex: str | None
    phone_last4: str | None


class PatientRegistryService:
    """Synchronize chart-scoped patient profiles into a tenant registry."""

    @staticmethod
    def _normalize_name(value: str | None) -> str | None:
        if not value:
            return None
        normalized = re.sub(r"[^a-z0-9]+", " ", value.strip().lower())
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized or None

    @staticmethod
    def _normalize_phone(value: str | None) -> str | None:
        if not value:
            return None
        digits = re.sub(r"\D+", "", value)
        return digits or None

    @staticmethod
    def build_canonical_patient_key(
        first_name: str | None,
        last_name: str | None,
        date_of_birth: str | None,
    ) -> str | None:
        first_norm = PatientRegistryService._normalize_name(first_name)
        last_norm = PatientRegistryService._normalize_name(last_name)
        dob = (date_of_birth or "").strip() or None
        if not first_norm or not last_norm or not dob:
            return None
        payload = f"{last_norm}|{first_norm}|{dob}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def hash_identifier(identifier_value: str) -> str:
        return hmac.new(
            _get_hash_key().encode("utf-8"),
            identifier_value.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    async def _find_existing_profile(
        session: AsyncSession,
        tenant_id: str,
        canonical_patient_key: str | None,
        phone_hash: str | None,
        date_of_birth: str | None,
    ) -> PatientRegistryProfile | None:
        if canonical_patient_key:
            result = await session.execute(
                select(PatientRegistryProfile).where(
                    and_(
                        PatientRegistryProfile.tenant_id == tenant_id,
                        PatientRegistryProfile.canonical_patient_key == canonical_patient_key,
                        PatientRegistryProfile.deleted_at.is_(None),
                        PatientRegistryProfile.merged_into_patient_id.is_(None),
                    )
                )
            )
            profile = result.scalars().first()
            if profile is not None:
                return profile

        if phone_hash and date_of_birth:
            result = await session.execute(
                select(PatientRegistryProfile)
                .join(
                    PatientRegistryIdentifier,
                    PatientRegistryIdentifier.patient_registry_profile_id == PatientRegistryProfile.id,
                )
                .where(
                    and_(
                        PatientRegistryProfile.tenant_id == tenant_id,
                        PatientRegistryProfile.date_of_birth == date_of_birth,
                        PatientRegistryProfile.deleted_at.is_(None),
                        PatientRegistryProfile.merged_into_patient_id.is_(None),
                        PatientRegistryIdentifier.identifier_type == "phone_number",
                        PatientRegistryIdentifier.identifier_hash == phone_hash,
                        PatientRegistryIdentifier.deleted_at.is_(None),
                    )
                )
            )
            return result.scalars().first()
        return None

    @staticmethod
    async def sync_chart_patient_profile(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        provider_id: str,
        patient_profile: PatientProfile,
    ) -> PatientRegistryProfile:
        canonical_patient_key = PatientRegistryService.build_canonical_patient_key(
            patient_profile.first_name,
            patient_profile.last_name,
            patient_profile.date_of_birth,
        )
        normalized_phone = PatientRegistryService._normalize_phone(patient_profile.phone_number)
        phone_hash = (
            PatientRegistryService.hash_identifier(normalized_phone)
            if normalized_phone
            else None
        )
        phone_last4 = normalized_phone[-4:] if normalized_phone and len(normalized_phone) >= 4 else None

        registry_profile = await PatientRegistryService._find_existing_profile(
            session=session,
            tenant_id=tenant_id,
            canonical_patient_key=canonical_patient_key,
            phone_hash=phone_hash,
            date_of_birth=patient_profile.date_of_birth,
        )

        now = datetime.now(UTC)
        if registry_profile is None:
            registry_profile = PatientRegistryProfile(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                canonical_patient_key=canonical_patient_key,
                first_name=patient_profile.first_name,
                middle_name=patient_profile.middle_name,
                last_name=patient_profile.last_name,
                first_name_norm=PatientRegistryService._normalize_name(patient_profile.first_name),
                last_name_norm=PatientRegistryService._normalize_name(patient_profile.last_name),
                date_of_birth=patient_profile.date_of_birth,
                sex=patient_profile.sex,
                phone_last4=phone_last4,
                primary_phone_hash=phone_hash,
                ai_assisted=False,
                created_at=now,
                updated_at=now,
            )
            session.add(registry_profile)
            await session.flush()
        else:
            if canonical_patient_key and not registry_profile.canonical_patient_key:
                registry_profile.canonical_patient_key = canonical_patient_key
            if patient_profile.first_name:
                registry_profile.first_name = patient_profile.first_name
                registry_profile.first_name_norm = PatientRegistryService._normalize_name(patient_profile.first_name)
            if patient_profile.middle_name:
                registry_profile.middle_name = patient_profile.middle_name
            if patient_profile.last_name:
                registry_profile.last_name = patient_profile.last_name
                registry_profile.last_name_norm = PatientRegistryService._normalize_name(patient_profile.last_name)
            if patient_profile.date_of_birth:
                registry_profile.date_of_birth = patient_profile.date_of_birth
            if patient_profile.sex:
                registry_profile.sex = patient_profile.sex
            if phone_last4:
                registry_profile.phone_last4 = phone_last4
            if phone_hash:
                registry_profile.primary_phone_hash = phone_hash
            registry_profile.updated_at = now

        if phone_hash:
            result = await session.execute(
                select(PatientRegistryIdentifier).where(
                    and_(
                        PatientRegistryIdentifier.patient_registry_profile_id == registry_profile.id,
                        PatientRegistryIdentifier.identifier_type == "phone_number",
                        PatientRegistryIdentifier.identifier_hash == phone_hash,
                        PatientRegistryIdentifier.deleted_at.is_(None),
                    )
                )
            )
            identifier = result.scalars().first()
            if identifier is None:
                identifier = PatientRegistryIdentifier(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    patient_registry_profile_id=registry_profile.id,
                    identifier_type="phone_number",
                    identifier_hash=phone_hash,
                    identifier_last4=phone_last4,
                    is_primary=True,
                    source_chart_id=chart_id,
                    created_at=now,
                    updated_at=now,
                )
                session.add(identifier)
            else:
                identifier.identifier_last4 = phone_last4
                identifier.is_primary = True
                identifier.source_chart_id = chart_id
                identifier.updated_at = now

        result = await session.execute(
            select(PatientRegistryChartLink).where(
                and_(
                    PatientRegistryChartLink.chart_id == chart_id,
                    PatientRegistryChartLink.tenant_id == tenant_id,
                    PatientRegistryChartLink.deleted_at.is_(None),
                )
            )
        )
        chart_link = result.scalars().first()
        if chart_link is None:
            chart_link = PatientRegistryChartLink(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                patient_registry_profile_id=registry_profile.id,
                chart_id=chart_id,
                link_status="linked",
                confidence_status=(
                    "exact_duplicate" if canonical_patient_key else "manual_review_pending"
                ),
                linked_by_user_id=provider_id,
                linked_at=now,
                updated_at=now,
            )
            session.add(chart_link)
        else:
            chart_link.patient_registry_profile_id = registry_profile.id
            chart_link.link_status = "linked"
            if canonical_patient_key:
                chart_link.confidence_status = "exact_duplicate"
            chart_link.linked_by_user_id = provider_id
            chart_link.updated_at = now

        return registry_profile

    @staticmethod
    async def search_profiles(
        session: AsyncSession,
        tenant_id: str,
        *,
        first_name: str | None = None,
        last_name: str | None = None,
        date_of_birth: str | None = None,
        phone_number: str | None = None,
    ) -> list[PatientRegistrySearchResult]:
        stmt = select(PatientRegistryProfile).where(
            and_(
                PatientRegistryProfile.tenant_id == tenant_id,
                PatientRegistryProfile.deleted_at.is_(None),
                PatientRegistryProfile.merged_into_patient_id.is_(None),
            )
        )

        first_norm = PatientRegistryService._normalize_name(first_name)
        last_norm = PatientRegistryService._normalize_name(last_name)
        if first_norm:
            stmt = stmt.where(PatientRegistryProfile.first_name_norm == first_norm)
        if last_norm:
            stmt = stmt.where(PatientRegistryProfile.last_name_norm == last_norm)
        if date_of_birth:
            stmt = stmt.where(PatientRegistryProfile.date_of_birth == date_of_birth)

        profiles = list((await session.execute(stmt.order_by(PatientRegistryProfile.updated_at.desc()))).scalars().all())

        normalized_phone = PatientRegistryService._normalize_phone(phone_number)
        if normalized_phone:
            phone_hash = PatientRegistryService.hash_identifier(normalized_phone)
            profile_ids = {
                row.patient_registry_profile_id
                for row in (
                    await session.execute(
                        select(PatientRegistryIdentifier).where(
                            and_(
                                PatientRegistryIdentifier.tenant_id == tenant_id,
                                PatientRegistryIdentifier.identifier_type == "phone_number",
                                PatientRegistryIdentifier.identifier_hash == phone_hash,
                                PatientRegistryIdentifier.deleted_at.is_(None),
                            )
                        )
                    )
                ).scalars().all()
            }
            profiles = [profile for profile in profiles if profile.id in profile_ids]

        return [
            PatientRegistrySearchResult(
                profile_id=profile.id,
                canonical_patient_key=profile.canonical_patient_key,
                first_name=profile.first_name,
                last_name=profile.last_name,
                date_of_birth=profile.date_of_birth,
                sex=profile.sex,
                phone_last4=profile.phone_last4,
            )
            for profile in profiles
        ]

    @staticmethod
    async def get_profile(
        session: AsyncSession,
        tenant_id: str,
        profile_id: str,
    ) -> PatientRegistryProfile | None:
        result = await session.execute(
            select(PatientRegistryProfile).where(
                and_(
                    PatientRegistryProfile.id == profile_id,
                    PatientRegistryProfile.tenant_id == tenant_id,
                    PatientRegistryProfile.deleted_at.is_(None),
                )
            )
        )
        return result.scalars().first()

    @staticmethod
    async def get_profile_chart_links(
        session: AsyncSession,
        tenant_id: str,
        profile_id: str,
    ) -> list[PatientRegistryChartLink]:
        result = await session.execute(
            select(PatientRegistryChartLink).where(
                and_(
                    PatientRegistryChartLink.tenant_id == tenant_id,
                    PatientRegistryChartLink.patient_registry_profile_id == profile_id,
                    PatientRegistryChartLink.deleted_at.is_(None),
                )
            )
        )
        return list(result.scalars().all())