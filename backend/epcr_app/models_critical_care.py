"""Critical Care Intervention Engine models.

Critical care interventions are first-class CareGraph entities.
Every intervention must store:
- Intervention family and specific intervention
- Indication and contraindication context
- Protocol context
- Initiator and authorizer
- Exact time, dosage, rate, route
- Device settings
- Pre-intervention state
- Expected and actual response
- Reassessment interval
- Escalation and downgrade paths
- NEMSIS mapping state
- Terminology bindings

An intervention is NOT clinically complete unless:
- Actual response is documented, OR
- Response is explicitly unavailable with a valid reason.
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

class InterventionFamily(str, Enum):
    AIRWAY = "airway"
    VENTILATION = "ventilation"
    OXYGENATION = "oxygenation"
    HEMODYNAMICS = "hemodynamics"
    VASOACTIVE_INFUSION = "vasoactive_infusion"
    SEDATION = "sedation"
    ANALGESIA = "analgesia"
    ANTIARRHYTHMIC = "antiarrhythmic"
    SEIZURE_CARE = "seizure_care"
    BLOOD_PRODUCT = "blood_product"
    POST_ROSC = "post_rosc"
    NEONATAL_RESUSCITATION = "neonatal_resuscitation"
    PEDIATRIC_CRITICAL_CARE = "pediatric_critical_care"
    TRAUMA_CRITICAL_CARE = "trauma_critical_care"
    INTERFACILITY_TRANSPORT = "interfacility_transport"
    DEVICE_CONTINUITY = "device_continuity"
    PACING = "pacing"
    CARDIOVERSION = "cardioversion"
    DECOMPRESSION = "decompression"
    INFUSION_TITRATION = "infusion_titration"


class CriticalCareDeviceType(str, Enum):
    VENTILATOR = "ventilator"
    INFUSION_PUMP = "infusion_pump"
    CARDIAC_MONITOR = "cardiac_monitor"
    PACEMAKER = "pacemaker"
    IABP = "iabp"
    ECMO = "ecmo"
    LVAD = "lvad"
    CPAP = "cpap"
    BIPAP = "bipap"
    PULSE_OXIMETER = "pulse_oximeter"
    CAPNOGRAPH = "capnograph"
    GLUCOMETER = "glucometer"
    TEMPERATURE_PROBE = "temperature_probe"
    ARTERIAL_LINE = "arterial_line"
    CVP_MONITOR = "cvp_monitor"


class ResponseAvailability(str, Enum):
    DOCUMENTED = "documented"
    UNAVAILABLE_TRANSPORT_TIME = "unavailable_transport_time"
    UNAVAILABLE_PATIENT_CONDITION = "unavailable_patient_condition"
    UNAVAILABLE_DEVICE_LIMITATION = "unavailable_device_limitation"
    PENDING = "pending"


# ---------------------------------------------------------------------------
# Critical Care Device
# ---------------------------------------------------------------------------

class CriticalCareDevice(Base):
    """Device in use during critical care transport.

    Tracks device type, settings, and continuity state for interfacility
    transport. Device settings are structured JSON, not free text.
    """
    __tablename__ = "epcr_critical_care_devices"

    id = Column(String(36), primary_key=True, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    caregraph_node_id = Column(String(36), nullable=True, index=True)

    device_type = Column(String(64), nullable=False)  # CriticalCareDeviceType
    device_name = Column(String(128), nullable=False)
    device_model = Column(String(128), nullable=True)
    device_serial = Column(String(64), nullable=True)

    # Settings at time of transport assumption
    initial_settings_json = Column(Text, nullable=True)
    current_settings_json = Column(Text, nullable=True)
    settings_change_log_json = Column(Text, nullable=True)  # JSON array of timestamped changes

    # Continuity state
    received_from_facility = Column(String(255), nullable=True)
    received_at = Column(DateTime(timezone=True), nullable=True)
    delivered_to_facility = Column(String(255), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    continuity_notes = Column(Text, nullable=True)

    provider_id = Column(String(255), nullable=False)
    documented_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------------------
# Infusion Run
# ---------------------------------------------------------------------------

class InfusionRun(Base):
    """Continuous infusion run with titration history.

    Tracks vasoactive drips, sedation infusions, analgesia infusions,
    and other continuous medication infusions with full titration log.
    """
    __tablename__ = "epcr_infusion_runs"

    id = Column(String(36), primary_key=True, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    caregraph_node_id = Column(String(36), nullable=True, index=True)

    medication_name = Column(String(128), nullable=False)
    rxnorm_code = Column(String(32), nullable=True)
    concentration = Column(String(64), nullable=True)  # e.g., "400mg/250mL"
    concentration_unit = Column(String(32), nullable=True)

    # Initial settings
    initial_rate_value = Column(Float, nullable=False)
    initial_rate_unit = Column(String(32), nullable=False)  # mcg/kg/min, mL/hr, etc.
    initial_dose_value = Column(Float, nullable=True)
    initial_dose_unit = Column(String(32), nullable=True)

    # Titration log (JSON array of {timestamp, rate, dose, reason, provider_id})
    titration_log_json = Column(Text, nullable=True)

    indication = Column(Text, nullable=False)
    protocol_family = Column(String(64), nullable=True)

    started_at = Column(DateTime(timezone=True), nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    end_reason = Column(String(255), nullable=True)

    provider_id = Column(String(255), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------------------
# Ventilator Session
# ---------------------------------------------------------------------------

class VentilatorSession(Base):
    """Ventilator management session with settings and waveform context.

    Tracks mode, settings, alarms, and changes during mechanical ventilation.
    """
    __tablename__ = "epcr_ventilator_sessions"

    id = Column(String(36), primary_key=True, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    device_id = Column(String(36), nullable=True, index=True)  # FK to CriticalCareDevice
    caregraph_node_id = Column(String(36), nullable=True, index=True)

    # Ventilator mode and settings
    mode = Column(String(64), nullable=False)  # AC/VC, AC/PC, SIMV, CPAP, BiPAP, etc.
    tidal_volume_ml = Column(Integer, nullable=True)
    respiratory_rate = Column(Integer, nullable=True)
    fio2_percent = Column(Integer, nullable=True)
    peep_cmh2o = Column(Float, nullable=True)
    inspiratory_pressure_cmh2o = Column(Float, nullable=True)
    inspiratory_time_seconds = Column(Float, nullable=True)
    flow_rate_lpm = Column(Float, nullable=True)
    pressure_support_cmh2o = Column(Float, nullable=True)

    # Measured values
    peak_pressure_cmh2o = Column(Float, nullable=True)
    plateau_pressure_cmh2o = Column(Float, nullable=True)
    minute_ventilation_lpm = Column(Float, nullable=True)
    etco2_mmhg = Column(Float, nullable=True)

    # Settings change log
    settings_change_log_json = Column(Text, nullable=True)

    # Airway context
    airway_type = Column(String(64), nullable=True)  # ETT, trach, LMA, etc.
    ett_size_mm = Column(Float, nullable=True)
    ett_depth_cm = Column(Float, nullable=True)
    cuff_pressure_cmh2o = Column(Float, nullable=True)

    indication = Column(Text, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=True)

    provider_id = Column(String(255), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------------------
# Blood Product Administration
# ---------------------------------------------------------------------------

class BloodProductAdministration(Base):
    """Blood product administration record with compatibility and response tracking."""

    __tablename__ = "epcr_blood_product_administrations"

    id = Column(String(36), primary_key=True, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    caregraph_node_id = Column(String(36), nullable=True, index=True)

    product_type = Column(String(64), nullable=False)  # pRBC, FFP, platelets, cryo, whole_blood
    unit_number = Column(String(64), nullable=True)
    blood_type = Column(String(16), nullable=True)
    volume_ml = Column(Integer, nullable=True)
    rate_ml_per_hr = Column(Float, nullable=True)

    indication = Column(Text, nullable=False)
    pre_transfusion_hgb = Column(Float, nullable=True)
    pre_transfusion_hct = Column(Float, nullable=True)

    # Reaction monitoring
    reaction_observed = Column(Boolean, nullable=False, default=False)
    reaction_description = Column(Text, nullable=True)
    reaction_intervention = Column(Text, nullable=True)

    started_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    provider_id = Column(String(255), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------------------
# Response Window
# ---------------------------------------------------------------------------

class ResponseWindow(Base):
    """Structured response window for an intervention.

    Captures the expected and actual clinical response to an intervention
    within a defined time window. An intervention is NOT complete without
    a documented response or an explicit unavailability reason.
    """
    __tablename__ = "epcr_response_windows"

    id = Column(String(36), primary_key=True, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    intervention_id = Column(String(36), nullable=False, index=True)  # FK to ClinicalIntervention
    tenant_id = Column(String(36), index=True, nullable=False)
    caregraph_node_id = Column(String(36), nullable=True, index=True)

    expected_response = Column(Text, nullable=False)
    expected_response_window_minutes = Column(Integer, nullable=True)

    actual_response = Column(Text, nullable=True)
    response_availability = Column(String(64), nullable=False, default="pending")  # ResponseAvailability
    unavailability_reason = Column(Text, nullable=True)

    response_adequate = Column(Boolean, nullable=True)
    escalation_triggered = Column(Boolean, nullable=False, default=False)
    escalation_detail = Column(Text, nullable=True)

    assessed_at = Column(DateTime(timezone=True), nullable=True)
    provider_id = Column(String(255), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------------------
# Intervention Intent
# ---------------------------------------------------------------------------

class InterventionIntent(Base):
    """Structured intent record for a clinical intervention."""

    __tablename__ = "epcr_intervention_intents"

    id = Column(String(36), primary_key=True, index=True)
    intervention_id = Column(String(36), nullable=False, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    intent_category = Column(String(64), nullable=False)  # therapeutic, diagnostic, supportive, palliative
    intent_description = Column(Text, nullable=False)
    clinical_goal = Column(Text, nullable=True)
    target_parameter = Column(String(128), nullable=True)  # e.g., MAP > 65 mmHg
    target_value = Column(String(64), nullable=True)

    provider_id = Column(String(255), nullable=False)
    documented_at = Column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# Intervention Indication
# ---------------------------------------------------------------------------

class InterventionIndication(Base):
    """Structured indication for a clinical intervention."""

    __tablename__ = "epcr_intervention_indications"

    id = Column(String(36), primary_key=True, index=True)
    intervention_id = Column(String(36), nullable=False, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    indication_label = Column(String(255), nullable=False)
    snomed_code = Column(String(32), nullable=True)
    icd10_code = Column(String(32), nullable=True)
    evidence_node_ids_json = Column(Text, nullable=True)  # CareGraph node IDs supporting this indication

    provider_id = Column(String(255), nullable=False)
    documented_at = Column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# Intervention Contraindication
# ---------------------------------------------------------------------------

class InterventionContraindication(Base):
    """Documented contraindication context for a clinical intervention."""

    __tablename__ = "epcr_intervention_contraindications"

    id = Column(String(36), primary_key=True, index=True)
    intervention_id = Column(String(36), nullable=False, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    contraindication_label = Column(String(255), nullable=False)
    contraindication_present = Column(Boolean, nullable=False)
    override_reason = Column(Text, nullable=True)  # if contraindicated but proceeded
    override_authorized_by = Column(String(255), nullable=True)

    provider_id = Column(String(255), nullable=False)
    documented_at = Column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# Intervention Protocol Link
# ---------------------------------------------------------------------------

class InterventionProtocolLink(Base):
    """Links an intervention to the governing protocol."""

    __tablename__ = "epcr_intervention_protocol_links"

    id = Column(String(36), primary_key=True, index=True)
    intervention_id = Column(String(36), nullable=False, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    protocol_family = Column(String(64), nullable=False)
    protocol_name = Column(String(255), nullable=False)
    protocol_version = Column(String(64), nullable=True)
    protocol_step = Column(String(128), nullable=True)
    deviation_present = Column(Boolean, nullable=False, default=False)
    deviation_reason = Column(Text, nullable=True)

    provider_id = Column(String(255), nullable=False)
    documented_at = Column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# Intervention Terminology Binding
# ---------------------------------------------------------------------------

class InterventionTerminologyBinding(Base):
    """Terminology bindings for a clinical intervention."""

    __tablename__ = "epcr_intervention_terminology_bindings"

    id = Column(String(36), primary_key=True, index=True)
    intervention_id = Column(String(36), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    terminology_system = Column(String(32), nullable=False)  # snomed, icd10, rxnorm, nemsis
    code = Column(String(64), nullable=False)
    display = Column(String(255), nullable=True)
    binding_confidence = Column(String(32), nullable=False, default="confirmed")
    source = Column(String(64), nullable=True)  # manual, ai_suggested, protocol_mapped


# ---------------------------------------------------------------------------
# Intervention NEMSIS Link
# ---------------------------------------------------------------------------

class InterventionNemsisLink(Base):
    """NEMSIS export mapping for a clinical intervention."""

    __tablename__ = "epcr_intervention_nemsis_links"

    id = Column(String(36), primary_key=True, index=True)
    intervention_id = Column(String(36), nullable=False, index=True)
    chart_id = Column(String(36), ForeignKey("epcr_charts.id"), nullable=False, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)

    nemsis_section = Column(String(32), nullable=False)  # eProcedures, eMedications, eAirway
    nemsis_element = Column(String(64), nullable=False)
    nemsis_value = Column(String(255), nullable=False)
    xml_path = Column(String(255), nullable=True)
    export_ready = Column(Boolean, nullable=False, default=False)
    export_blocker_reason = Column(Text, nullable=True)
