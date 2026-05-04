"""Dashboard and User Customization models.

User customization is a required EPCR capability.
Customization MUST NOT:
- Mutate clinical truth
- Hide mandatory completion blockers
- Break NEMSIS mapping
- Be stored only on the client

Supported customization:
- Dashboard card order and visibility
- Section visibility and density
- Favorite interventions, medications, protocols, impressions, destinations
- Theme colors, dark mode, light mode, field mode, high-contrast mode
- Role-based layouts
- Remembered workspace profiles (ALS, CCT, neonatal, pediatric, air, transport, trauma, supervisor QA)
"""
from __future__ import annotations

from datetime import datetime, UTC
from enum import Enum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import relationship

from epcr_app.models import Base


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class WorkspaceProfileType(str, Enum):
    ALS = "als"
    CRITICAL_CARE_TRANSPORT = "critical_care_transport"
    NEONATAL = "neonatal"
    PEDIATRIC = "pediatric"
    AIR = "air"
    TRANSPORT = "transport"
    TRAUMA = "trauma"
    SUPERVISOR_QA = "supervisor_qa"
    CUSTOM = "custom"


class ThemeMode(str, Enum):
    LIGHT = "light"
    DARK = "dark"
    FIELD = "field"
    HIGH_CONTRAST = "high_contrast"
    SYSTEM = "system"


class DashboardCardType(str, Enum):
    CHART_STATUS = "chart_status"
    VITALS_TIMELINE = "vitals_timeline"
    NEMSIS_READINESS = "nemsis_readiness"
    BILLING_READINESS = "billing_readiness"
    CLINICAL_COMPLETENESS = "clinical_completeness"
    SYNC_HEALTH = "sync_health"
    ACTIVE_INTERVENTIONS = "active_interventions"
    PROTOCOL_STATUS = "protocol_status"
    VISION_INBOX = "vision_inbox"
    RECENT_CHARTS = "recent_charts"
    QUICK_ACTIONS = "quick_actions"
    PATIENT_SUMMARY = "patient_summary"
    CAREGRAPH_SUMMARY = "caregraph_summary"
    EXPORT_STATUS = "export_status"


# ---------------------------------------------------------------------------
# User Dashboard Profile
# ---------------------------------------------------------------------------

class UserDashboardProfile(Base):
    """User-specific dashboard configuration.

    Stores card order, visibility, density, and layout preferences.
    Dashboard customization NEVER affects clinical truth or NEMSIS mapping.
    """
    __tablename__ = "epcr_user_dashboard_profiles"

    id = Column(String(36), primary_key=True, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    profile_name = Column(String(128), nullable=False, default="default")
    is_active = Column(Boolean, nullable=False, default=True)

    # Layout
    card_order_json = Column(Text, nullable=True)  # JSON ordered list of DashboardCardType
    hidden_cards_json = Column(Text, nullable=True)  # JSON list of hidden card types
    density = Column(String(32), nullable=False, default="normal")  # compact, normal, expanded

    # Theme
    theme_mode = Column(String(32), nullable=False, default="system")  # ThemeMode
    accent_color = Column(String(16), nullable=True)  # hex color
    custom_theme_json = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))

    card_preferences = relationship("DashboardCardPreference", back_populates="profile", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# Dashboard Card Preference
# ---------------------------------------------------------------------------

class DashboardCardPreference(Base):
    """Per-card configuration within a dashboard profile."""

    __tablename__ = "epcr_dashboard_card_preferences"

    id = Column(String(36), primary_key=True, index=True)
    profile_id = Column(String(36), ForeignKey("epcr_user_dashboard_profiles.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    card_type = Column(String(64), nullable=False)  # DashboardCardType
    is_visible = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)
    config_json = Column(Text, nullable=True)  # card-specific configuration

    profile = relationship("UserDashboardProfile", back_populates="card_preferences")


# ---------------------------------------------------------------------------
# User Favorites
# ---------------------------------------------------------------------------

class UserFavorite(Base):
    """User-specific favorites for rapid clinical access.

    Favorites for: interventions, medications, protocols, impressions,
    destinations. Favorites NEVER affect clinical truth.
    """
    __tablename__ = "epcr_user_favorites"

    id = Column(String(36), primary_key=True, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    favorite_type = Column(String(64), nullable=False, index=True)  # intervention, medication, protocol, impression, destination
    favorite_key = Column(String(255), nullable=False)  # identifier for the favorite item
    display_label = Column(String(255), nullable=False)
    metadata_json = Column(Text, nullable=True)  # type-specific metadata

    sort_order = Column(Integer, nullable=False, default=0)
    use_count = Column(Integer, nullable=False, default=0)
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


# ---------------------------------------------------------------------------
# User Theme Settings
# ---------------------------------------------------------------------------

class UserThemeSettings(Base):
    """User-specific theme and display settings."""

    __tablename__ = "epcr_user_theme_settings"

    id = Column(String(36), primary_key=True, index=True)
    user_id = Column(String(255), nullable=False, unique=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    theme_mode = Column(String(32), nullable=False, default="system")
    accent_color = Column(String(16), nullable=True)
    font_size_scale = Column(Float, nullable=False, default=1.0)
    high_contrast_enabled = Column(Boolean, nullable=False, default=False)
    reduce_motion = Column(Boolean, nullable=False, default=False)
    glove_mode = Column(Boolean, nullable=False, default=False)  # larger touch targets

    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))


# ---------------------------------------------------------------------------
# User Recent Actions
# ---------------------------------------------------------------------------

class UserRecentAction(Base):
    """Recent actions for quick-access suggestions."""

    __tablename__ = "epcr_user_recent_actions"

    id = Column(String(36), primary_key=True, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    action_type = Column(String(64), nullable=False)
    action_key = Column(String(255), nullable=False)
    display_label = Column(String(255), nullable=False)
    context_json = Column(Text, nullable=True)

    performed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


# ---------------------------------------------------------------------------
# Workspace Profile
# ---------------------------------------------------------------------------

class WorkspaceProfile(Base):
    """Saved workspace profile for role-specific EPCR configuration.

    Profiles define which sections are visible, which panels are expanded,
    and which quick-access items are shown for a specific clinical role.

    Profiles NEVER hide mandatory completion blockers.
    """
    __tablename__ = "epcr_workspace_profiles"

    id = Column(String(36), primary_key=True, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    profile_type = Column(String(64), nullable=False)  # WorkspaceProfileType
    profile_name = Column(String(128), nullable=False)
    is_default = Column(Boolean, nullable=False, default=False)

    # Section visibility (NEVER hides mandatory blockers)
    visible_sections_json = Column(Text, nullable=True)  # JSON list of visible section keys
    expanded_panels_json = Column(Text, nullable=True)   # JSON list of expanded panel keys
    quick_access_items_json = Column(Text, nullable=True)  # JSON list of quick-access items

    # Critical care workspace mode
    critical_care_mode = Column(Boolean, nullable=False, default=False)
    show_ventilator_panel = Column(Boolean, nullable=False, default=False)
    show_infusion_panel = Column(Boolean, nullable=False, default=False)
    show_device_continuity_panel = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))


# ---------------------------------------------------------------------------
# Agency Workflow Configuration
# ---------------------------------------------------------------------------

class AgencyWorkflowConfig(Base):
    """Agency-level workflow configuration for EPCR.

    Agencies may configure custom workflows, required fields, and
    protocol configurations. Agency configuration MUST NOT break
    NEMSIS mapping or hide mandatory fields.
    """
    __tablename__ = "epcr_agency_workflow_configs"

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), unique=True, index=True, nullable=False)

    # Required field overrides (agencies may require additional fields)
    additional_required_fields_json = Column(Text, nullable=True)

    # Protocol configuration
    enabled_protocol_families_json = Column(Text, nullable=True)
    default_protocol_family = Column(String(64), nullable=True)

    # Workflow configuration
    require_opqrst_for_pain = Column(Boolean, nullable=False, default=True)
    require_reassessment_after_intervention = Column(Boolean, nullable=False, default=True)
    require_response_documentation = Column(Boolean, nullable=False, default=True)
    require_bilateral_assessment = Column(Boolean, nullable=False, default=False)

    # NEMSIS configuration
    state_code = Column(String(8), nullable=True)
    agency_number = Column(String(32), nullable=True)
    custom_nemsis_fields_json = Column(Text, nullable=True)

    updated_by = Column(String(255), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
