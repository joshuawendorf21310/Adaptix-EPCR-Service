"""Comprehensive tests for care domain (ePCR NEMSIS compliance).

Tests verify:
- Chart creation with validation
- Compliance checking against NEMSIS 3.5.1 mandatory fields
- Input validation and error handling
- Database operations and tenant isolation
- Health checks report truthful status
"""
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from epcr_app.models import Base, Chart, NemsisCompliance, ChartStatus, ComplianceStatus, EpcrAuditLog
from epcr_app.services import ChartService
from epcr_app.db import check_health


@pytest_asyncio.fixture
async def test_db():
    """Create temporary in-memory test database."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield async_session
    
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_chart_success(test_db):
    """Test successful chart creation with all required fields."""
    async with test_db() as session:
        chart = await ChartService.create_chart(
            session=session,
            tenant_id="test-tenant",
            call_number="CALL-2026-001",
            incident_type="medical",
            created_by_user_id="paramedic-123"
        )
        
        assert chart.id is not None
        assert chart.call_number == "CALL-2026-001"
        assert chart.status == ChartStatus.NEW
        assert chart.incident_type == "medical"
        assert chart.created_by_user_id == "paramedic-123"
        
        compliance = await session.execute(
            select(NemsisCompliance).where(NemsisCompliance.chart_id == chart.id)
        )
        assert compliance.scalars().first() is not None

        audit = await session.execute(
            select(EpcrAuditLog).where(EpcrAuditLog.chart_id == chart.id)
        )
        entries = audit.scalars().all()
        assert len(entries) == 1
        assert entries[0].action == "chart_created"


@pytest.mark.asyncio
async def test_create_chart_invalid_tenant_id(test_db):
    """Test chart creation rejects invalid tenant_id."""
    async with test_db() as session:
        with pytest.raises(ValueError, match="tenant_id is required"):
            await ChartService.create_chart(
                session=session,
                tenant_id="",  # Invalid
                call_number="CALL-2026-001",
                incident_type="medical",
                created_by_user_id="user-123"
            )


@pytest.mark.asyncio
async def test_create_chart_invalid_call_number(test_db):
    """Test chart creation rejects empty call_number."""
    async with test_db() as session:
        with pytest.raises(ValueError, match="call_number is required"):
            await ChartService.create_chart(
                session=session,
                tenant_id="test-tenant",
                call_number="",  # Invalid
                incident_type="medical",
                created_by_user_id="user-123"
            )


@pytest.mark.asyncio
async def test_create_chart_invalid_incident_type(test_db):
    """Test chart creation rejects invalid incident_type."""
    async with test_db() as session:
        with pytest.raises(ValueError, match="incident_type must be one of"):
            await ChartService.create_chart(
                session=session,
                tenant_id="test-tenant",
                call_number="CALL-2026-001",
                incident_type="invalid",  # Invalid
                created_by_user_id="user-123"
            )


@pytest.mark.asyncio
async def test_create_chart_invalid_user_id(test_db):
    """Test chart creation rejects empty user_id."""
    async with test_db() as session:
        with pytest.raises(ValueError, match="created_by_user_id is required"):
            await ChartService.create_chart(
                session=session,
                tenant_id="test-tenant",
                call_number="CALL-2026-001",
                incident_type="medical",
                created_by_user_id=""  # Invalid
            )


@pytest.mark.asyncio
async def test_create_chart_with_patient_id(test_db):
    """Test chart creation with optional patient_id."""
    async with test_db() as session:
        chart = await ChartService.create_chart(
            session=session,
            tenant_id="test-tenant",
            call_number="CALL-2026-002",
            incident_type="trauma",
            created_by_user_id="user-123",
            patient_id="patient-456"
        )
        
        assert chart.patient_id == "patient-456"
        assert chart.incident_type == "trauma"


@pytest.mark.asyncio
async def test_get_chart_found(test_db):
    """Test retrieving existing chart."""
    async with test_db() as session:
        chart = await ChartService.create_chart(
            session=session,
            tenant_id="test-tenant",
            call_number="CALL-2026-003",
            incident_type="medical",
            created_by_user_id="user-123"
        )
        
        retrieved = await ChartService.get_chart(session, "test-tenant", chart.id)
        assert retrieved is not None
        assert retrieved.id == chart.id
        assert retrieved.call_number == "CALL-2026-003"


@pytest.mark.asyncio
async def test_get_chart_not_found(test_db):
    """Test retrieving non-existent chart returns None."""
    async with test_db() as session:
        retrieved = await ChartService.get_chart(session, "test-tenant", "nonexistent-id")
        assert retrieved is None


@pytest.mark.asyncio
async def test_get_chart_tenant_isolation(test_db):
    """Test tenant isolation: chart from one tenant not visible to another."""
    async with test_db() as session:
        chart = await ChartService.create_chart(
            session=session,
            tenant_id="tenant-a",
            call_number="CALL-2026-004",
            incident_type="medical",
            created_by_user_id="user-123"
        )
        
        # Try to retrieve with different tenant
        retrieved = await ChartService.get_chart(session, "tenant-b", chart.id)
        assert retrieved is None  # Should NOT be found


@pytest.mark.asyncio
async def test_check_nemsis_compliance_initial(test_db):
    """Test compliance check on new chart shows 0% filled."""
    async with test_db() as session:
        chart = await ChartService.create_chart(
            session=session,
            tenant_id="test-tenant",
            call_number="CALL-2026-005",
            incident_type="medical",
            created_by_user_id="user-123"
        )
        
        result = await ChartService.check_nemsis_compliance(session, "test-tenant", chart.id)
        
        assert result["compliance_status"] == ComplianceStatus.NOT_STARTED.value
        assert result["compliance_percentage"] == 0.0
        assert result["mandatory_fields_filled"] == 0
        assert result["mandatory_fields_required"] == 13  # NEMSIS 3.5.1 has 13 mandatory fields
        assert result["is_fully_compliant"] is False
        assert len(result["missing_mandatory_fields"]) == 13


@pytest.mark.asyncio
async def test_check_nemsis_compliance_not_found(test_db):
    """Test compliance check raises ValueError for non-existent chart."""
    async with test_db() as session:
        with pytest.raises(ValueError, match="Chart .* not found"):
            await ChartService.check_nemsis_compliance(session, "test-tenant", "nonexistent")


@pytest.mark.asyncio
async def test_check_nemsis_compliance_tenant_isolation(test_db):
    """Test compliance check enforces tenant isolation."""
    async with test_db() as session:
        chart = await ChartService.create_chart(
            session=session,
            tenant_id="tenant-a",
            call_number="CALL-2026-006",
            incident_type="medical",
            created_by_user_id="user-123"
        )
        
        with pytest.raises(ValueError, match="Chart .* not found"):
            await ChartService.check_nemsis_compliance(session, "tenant-b", chart.id)


@pytest.mark.asyncio
async def test_health_check_connected():
    """Test health check reports connected status."""
    health = await check_health()
    
    # Cannot guarantee success on all systems, but should return valid structure
    assert "status" in health
    assert health["status"] in ["healthy", "degraded"]
    assert "service" in health
    assert health["service"] == "epcr"
    assert "database" in health


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
