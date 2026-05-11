"""NEMSIS eScene (chart scene) ORM models.

Backs the ``epcr_chart_scene`` (1:1) and ``epcr_chart_scene_other_agencies``
(1:M) tables created by migration ``028``. Represents the NEMSIS v3.5.1
eScene section as two related child aggregates of :class:`Chart`:

* :class:`ChartScene` holds the once-per-chart scene metadata (eScene.01,
  .05..23 minus the multi-row .02/.03/.04/.24/.25 group).
* :class:`ChartSceneOtherAgency` holds the repeating "Other EMS or Public
  Safety Agencies at Scene" group (eScene.02/.03/.04/.24/.25).

NEMSIS element bindings (handled by :mod:`projection_chart_scene`):

    first_ems_unit_indicator_code              -> eScene.01
    initial_responder_arrived_at               -> eScene.05
    number_of_patients                         -> eScene.06
    mci_indicator_code                         -> eScene.07
    mci_triage_classification_code             -> eScene.08
    incident_location_type_code                -> eScene.09
    incident_facility_code                     -> eScene.10
    scene_lat, scene_long                      -> eScene.11 (group)
    scene_usng                                 -> eScene.12
    incident_facility_name                     -> eScene.13
    mile_post_or_major_roadway                 -> eScene.14
    incident_street_address                    -> eScene.15
    incident_apartment                         -> eScene.16
    incident_city                              -> eScene.17
    incident_state                             -> eScene.18
    incident_zip                               -> eScene.19
    scene_cross_street                         -> eScene.20
    incident_county                            -> eScene.21
    incident_country                           -> eScene.22
    incident_census_tract                      -> eScene.23

    ChartSceneOtherAgency.agency_id                      -> eScene.03
    ChartSceneOtherAgency.other_service_type_code        -> eScene.04
    ChartSceneOtherAgency.first_to_provide_patient_care_indicator
                                                          -> eScene.24
    ChartSceneOtherAgency.patient_care_handoff_code      -> eScene.25
    (eScene.02 Other EMS or Public Safety Agencies at Scene is satisfied
    by the presence of one or more ChartSceneOtherAgency rows.)
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship

from epcr_app.models import Base


class ChartScene(Base):
    """NEMSIS eScene 1:1 aggregate for a chart.

    Required-at-National columns (eScene.01/.05/.06/.07/.08/.09/.15/.17/
    .18/.19) are stored nullable because real-world charts may be drafted
    before every field is recorded. The chart-finalization gate enforces
    the Required subset via the registry-driven validator, not the ORM
    layer.
    """

    __tablename__ = "epcr_chart_scene"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "chart_id",
            name="uq_epcr_chart_scene_tenant_chart",
        ),
    )

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    chart_id = Column(
        String(36),
        ForeignKey("epcr_charts.id"),
        nullable=False,
        unique=True,
        index=True,
    )

    # eScene.01 First EMS Unit on Scene (Required)
    first_ems_unit_indicator_code = Column(String(16), nullable=True)
    # eScene.05 Date/Time Initial Responder Arrived on Scene (Required)
    initial_responder_arrived_at = Column(DateTime(timezone=True), nullable=True)
    # eScene.06 Number of Patients at Scene (Required)
    number_of_patients = Column(Integer, nullable=True)
    # eScene.07 Mass Casualty Incident (Required)
    mci_indicator_code = Column(String(16), nullable=True)
    # eScene.08 Triage Classification for MCI Patient (Required when MCI)
    mci_triage_classification_code = Column(String(16), nullable=True)
    # eScene.09 Incident Location Type (Required)
    incident_location_type_code = Column(String(16), nullable=True)
    # eScene.10 Incident Facility Code
    incident_facility_code = Column(String(64), nullable=True)
    # eScene.11 Scene GPS Location (group)
    scene_lat = Column(Float, nullable=True)
    scene_long = Column(Float, nullable=True)
    # eScene.12 Scene US National Grid Coordinates
    scene_usng = Column(String(64), nullable=True)
    # eScene.13 Incident Facility or Location Name
    incident_facility_name = Column(String(255), nullable=True)
    # eScene.14 Mile Post or Major Roadway
    mile_post_or_major_roadway = Column(String(255), nullable=True)
    # eScene.15 Incident Street Address (Required)
    incident_street_address = Column(String(255), nullable=True)
    # eScene.16 Incident Apartment, Suite, or Room
    incident_apartment = Column(String(64), nullable=True)
    # eScene.17 Incident City (Required)
    incident_city = Column(String(120), nullable=True)
    # eScene.18 Incident State (Required)
    incident_state = Column(String(8), nullable=True)
    # eScene.19 Incident ZIP Code (Required)
    incident_zip = Column(String(16), nullable=True)
    # eScene.20 Scene Cross Street or Directions
    scene_cross_street = Column(String(255), nullable=True)
    # eScene.21 Incident County
    incident_county = Column(String(120), nullable=True)
    # eScene.22 Incident Country
    incident_country = Column(String(8), nullable=True, default="US")
    # eScene.23 Incident Census Tract
    incident_census_tract = Column(String(32), nullable=True)

    created_by_user_id = Column(String(64), nullable=True)
    updated_by_user_id = Column(String(64), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    chart = relationship("Chart", foreign_keys=[chart_id])


class ChartSceneOtherAgency(Base):
    """NEMSIS eScene 1:M aggregate for the "Other EMS or Public Safety
    Agencies at Scene" repeating group (eScene.02/.03/.04/.24/.25).

    Each row is one other-agency occurrence on the chart. The chart
    finalization gate enforces the Required subset
    (eScene.02 via presence of at least one row, plus eScene.03/.04 per
    row) via the registry-driven validator, not the ORM layer.
    """

    __tablename__ = "epcr_chart_scene_other_agencies"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "chart_id",
            "agency_id",
            name="uq_epcr_chart_scene_other_agencies_tenant_chart_agency",
        ),
    )

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    chart_id = Column(
        String(36),
        ForeignKey("epcr_charts.id"),
        nullable=False,
        index=True,
    )

    # eScene.03 Other EMS or Public Safety Agency ID Number (Required)
    agency_id = Column(String(64), nullable=False)
    # eScene.04 Type of Other Service at Scene (Required)
    other_service_type_code = Column(String(16), nullable=False)
    # eScene.24 First Other EMS or Public Safety Agency at Scene to
    # Provide Patient Care
    first_to_provide_patient_care_indicator = Column(String(16), nullable=True)
    # eScene.25 Transferred Patient/Care To/From Agency
    patient_care_handoff_code = Column(String(16), nullable=True)
    sequence_index = Column(Integer, nullable=False, default=0)

    created_by_user_id = Column(String(64), nullable=True)
    updated_by_user_id = Column(String(64), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)


__all__ = ["ChartScene", "ChartSceneOtherAgency"]
