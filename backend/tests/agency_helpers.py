"""Shared test helper for seeding an activated AgencyProfile.

All tests that call ChartService.create_chart() (directly or via HTTP)
require at least one activated AgencyProfile row in the same tenant scope.
This module provides a single, idempotent function that tests can call
right after Base.metadata.create_all to satisfy that requirement.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models import AgencyProfile


async def seed_active_agency(
    session: AsyncSession,
    tenant_id: str = "test-tenant",
    agency_code: str = "ADAPT001",
    agency_name: str = "Adaptix Test EMS",
    state: str = "CA",
) -> AgencyProfile:
    """Insert an activated AgencyProfile for the given tenant and flush.

    Safe to call multiple times — each call inserts a new row because the
    id is randomly generated. If the test DB already has an activated
    profile for this tenant, the resolver will use the first one found.
    """
    profile = AgencyProfile(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        agency_code=agency_code,
        agency_name=agency_name,
        state=state,
        operational_mode="full",
        numbering_policy_json="{}",
        activated_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(profile)
    await session.flush()
    return profile
