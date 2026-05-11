"""Device-specific OCR field extraction registry.

This is the authoritative mapping of what each physical device type exposes
for OCR extraction and how each extracted field maps to an internal key,
a display label, a NEMSIS 3.5.1 element ID, and the ePCR chart section it
belongs to.

Downstream consumers (the Android field app, the OCR worker, and the API
review layer) import DEVICE_FIELD_REGISTRY directly.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OcrFieldSpec:
    """Specification for a single extractable field from a device source.

    Attributes:
        field_key: Internal snake_case key used in OcrFieldCandidate.field_name.
        display_label: Human-readable label for UI display.
        nemsis_element: NEMSIS 3.5.1 element ID, or None if not NEMSIS-bound.
        chart_section: ePCR chart section this field belongs to.
        is_high_risk: True if this field always requires manual review.
        unit: Physical unit string (e.g. "bpm", "mmHg"), or None.
        extraction_hint: Natural-language hint for the OCR provider.
        normalization_type: One of "numeric", "text", "boolean", "timestamp", "coded".
    """

    field_key: str
    display_label: str
    nemsis_element: str | None
    chart_section: str
    is_high_risk: bool
    unit: str | None
    extraction_hint: str
    normalization_type: str


DEVICE_FIELD_REGISTRY: dict[str, list[OcrFieldSpec]] = {
    "CARDIAC_MONITOR": [
        OcrFieldSpec("heart_rate", "Heart Rate", "eVitals.10", "eVitals", False, "bpm", "HR or heart rate numeric value", "numeric"),
        OcrFieldSpec("bp_systolic", "BP Systolic", "eVitals.06", "eVitals", False, "mmHg", "Systolic blood pressure", "numeric"),
        OcrFieldSpec("bp_diastolic", "BP Diastolic", "eVitals.07", "eVitals", False, "mmHg", "Diastolic blood pressure", "numeric"),
        OcrFieldSpec("spo2", "SpO2", "eVitals.12", "eVitals", False, "%", "SpO2 or oxygen saturation percentage", "numeric"),
        OcrFieldSpec("etco2", "EtCO2", "eVitals.16", "eVitals", True, "mmHg", "End-tidal CO2 value", "numeric"),
        OcrFieldSpec("respiratory_rate", "Respiratory Rate", "eVitals.14", "eVitals", False, "/min", "Respiratory rate", "numeric"),
        OcrFieldSpec("temperature", "Temperature", "eVitals.24", "eVitals", False, "°F", "Temperature value", "numeric"),
        OcrFieldSpec("rhythm_label", "Cardiac Rhythm", "eVitals.03", "eVitals", True, None, "Rhythm interpretation text label", "text"),
        OcrFieldSpec("alarm_status", "Alarm Status", None, "eVitals", False, None, "Active alarm text", "text"),
        OcrFieldSpec("device_timestamp", "Device Timestamp", "eTimes.01", "eTimes", False, None, "Timestamp displayed on monitor screen", "timestamp"),
    ],
    "VENTILATOR": [
        OcrFieldSpec("vent_mode", "Ventilator Mode", None, "critical_care", True, None, "Ventilation mode: AC, SIMV, PSV, CPAP, BiPAP, PRVC", "text"),
        OcrFieldSpec("fio2", "FiO2", None, "critical_care", True, "%", "Fraction of inspired oxygen percentage", "numeric"),
        OcrFieldSpec("peep", "PEEP", None, "critical_care", True, "cmH2O", "Positive end-expiratory pressure", "numeric"),
        OcrFieldSpec("tidal_volume", "Tidal Volume", None, "critical_care", True, "mL", "Set or measured tidal volume", "numeric"),
        OcrFieldSpec("vent_rr", "Ventilator RR", "eVitals.14", "critical_care", False, "/min", "Set respiratory rate on ventilator", "numeric"),
        OcrFieldSpec("pressure_support", "Pressure Support", None, "critical_care", False, "cmH2O", "Pressure support level", "numeric"),
        OcrFieldSpec("pip", "Peak Inspiratory Pressure", None, "critical_care", False, "cmH2O", "Peak inspiratory pressure", "numeric"),
        OcrFieldSpec("plateau_pressure", "Plateau Pressure", None, "critical_care", False, "cmH2O", "Plateau pressure reading", "numeric"),
        OcrFieldSpec("map_airway", "Mean Airway Pressure", None, "critical_care", False, "cmH2O", "Mean airway pressure", "numeric"),
        OcrFieldSpec("minute_ventilation", "Minute Ventilation", None, "critical_care", False, "L/min", "Minute ventilation value", "numeric"),
        OcrFieldSpec("ie_ratio", "I:E Ratio", None, "critical_care", False, None, "Inspiratory to expiratory ratio", "text"),
        OcrFieldSpec("vent_timestamp", "Device Timestamp", None, "eTimes", False, None, "Timestamp on ventilator display", "timestamp"),
    ],
    "INFUSION_PUMP": [
        OcrFieldSpec("medication_name", "Medication Name", "eMedications.03", "eMedications", True, None, "Drug name on pump display or label", "text"),
        OcrFieldSpec("concentration", "Concentration", None, "eMedications", True, None, "Drug concentration e.g. 400mcg/mL", "text"),
        OcrFieldSpec("infusion_rate", "Infusion Rate", None, "eMedications", True, None, "Current infusion rate e.g. 10 mL/hr", "text"),
        OcrFieldSpec("medication_dose", "Dose", "eMedications.04", "eMedications", True, None, "Dose value displayed on pump", "text"),
        OcrFieldSpec("dose_units", "Dose Units", "eMedications.05", "eMedications", True, None, "Units: mcg/kg/min, mg/hr, units/hr, etc.", "text"),
        OcrFieldSpec("volume_infused", "Volume Infused", None, "eMedications", False, "mL", "Total volume infused so far", "numeric"),
        OcrFieldSpec("volume_remaining", "Volume Remaining", None, "eMedications", False, "mL", "Volume remaining in bag/syringe", "numeric"),
        OcrFieldSpec("pump_channel", "Pump Channel", None, "eMedications", False, None, "Channel A, B, 1, 2 etc.", "text"),
        OcrFieldSpec("pump_status", "Pump Status", None, "eMedications", False, None, "Running, paused, alarming, stopped", "text"),
        OcrFieldSpec("pump_timestamp", "Device Timestamp", None, "eTimes", False, None, "Timestamp on pump display", "timestamp"),
    ],
    "GLUCOMETER": [
        OcrFieldSpec("blood_glucose", "Blood Glucose", "eVitals.17", "eVitals", True, "mg/dL", "Blood glucose result", "numeric"),
        OcrFieldSpec("glucose_timestamp", "Test Timestamp", "eVitals.01", "eVitals", False, None, "Time of glucose test", "timestamp"),
    ],
    "MEDICATION_LABEL": [
        OcrFieldSpec("medication_name", "Medication Name", "eMedications.03", "eMedications", True, None, "Drug name on label", "text"),
        OcrFieldSpec("concentration", "Concentration", None, "eMedications", True, None, "Concentration on label", "text"),
        OcrFieldSpec("medication_dose", "Dose", "eMedications.04", "eMedications", True, None, "Dose on label", "text"),
        OcrFieldSpec("dose_units", "Units", "eMedications.05", "eMedications", True, None, "Unit on label", "text"),
        OcrFieldSpec("route", "Route", "eMedications.06", "eMedications", True, None, "Route on label", "text"),
        OcrFieldSpec("lot_number", "Lot Number", None, "eMedications", False, None, "Lot number", "text"),
        OcrFieldSpec("expiration_date", "Expiration Date", None, "eMedications", False, None, "Expiration date", "text"),
    ],
    "BLOOD_PRODUCT": [
        OcrFieldSpec("blood_product_type", "Blood Product Type", None, "eMedications", True, None, "pRBC, FFP, Plt, Cryo, WB", "text"),
        OcrFieldSpec("blood_unit_id", "Unit ID", None, "eMedications", True, None, "Blood bank unit identifier", "text"),
        OcrFieldSpec("blood_type", "Blood Type", None, "eMedications", True, None, "ABO/Rh blood type", "text"),
        OcrFieldSpec("expiration_datetime", "Expiration", None, "eMedications", True, None, "Product expiration date/time", "timestamp"),
        OcrFieldSpec("volume_ml", "Volume", None, "eMedications", False, "mL", "Volume of product unit", "numeric"),
        OcrFieldSpec("irradiated", "Irradiated", None, "eMedications", False, None, "Yes/No irradiation status", "boolean"),
        OcrFieldSpec("cmv_negative", "CMV Negative", None, "eMedications", False, None, "CMV negative status", "boolean"),
    ],
    "TRANSFER_PACKET": [
        OcrFieldSpec("patient_name", "Patient Name", "ePatient.02", "ePatient", True, None, "Full patient name from facesheet", "text"),
        OcrFieldSpec("patient_dob", "Date of Birth", "ePatient.17", "ePatient", True, None, "Patient date of birth", "text"),
        OcrFieldSpec("patient_mrn", "MRN", "ePatient.01", "ePatient", True, None, "Medical record number", "text"),
        OcrFieldSpec("sending_facility", "Sending Facility", "eDisposition.17", "eDisposition", False, None, "Name of sending hospital or facility", "text"),
        OcrFieldSpec("receiving_facility", "Receiving Facility", None, "eDisposition", False, None, "Destination facility name", "text"),
        OcrFieldSpec("primary_diagnosis", "Primary Diagnosis", "eSituation.11", "eSituation", False, None, "Primary diagnosis text", "text"),
        OcrFieldSpec("allergies", "Allergies", "eHistory.17", "eHistory", True, None, "Drug and food allergy list", "text"),
        OcrFieldSpec("code_status", "Code Status", None, "eHistory", True, None, "Full code, DNR, DNI, POLST", "text"),
        OcrFieldSpec("isolation_status", "Isolation Status", None, "eHistory", False, None, "Contact, droplet, airborne, neutropenic", "text"),
    ],
    "FACESHEET": [
        OcrFieldSpec("patient_name", "Patient Name", "ePatient.02", "ePatient", True, None, "Patient full name", "text"),
        OcrFieldSpec("patient_dob", "Date of Birth", "ePatient.17", "ePatient", True, None, "Date of birth", "text"),
        OcrFieldSpec("patient_mrn", "MRN", "ePatient.01", "ePatient", True, None, "MRN", "text"),
        OcrFieldSpec("insurance_id", "Insurance ID", "ePayment.12", "ePayment", False, None, "Insurance member ID", "text"),
        OcrFieldSpec("insurance_company", "Insurance", "ePayment.09", "ePayment", False, None, "Insurance company name", "text"),
        OcrFieldSpec("attending_physician", "Attending Physician", None, "eHistory", False, None, "Attending MD name", "text"),
        OcrFieldSpec("admit_date", "Admission Date", None, "eTimes", False, None, "Hospital admission date", "timestamp"),
    ],
    "DNR_POLST": [
        OcrFieldSpec("code_status", "Code Status", None, "eHistory", True, None, "DNR/DNI/POLST/Full Code status", "text"),
        OcrFieldSpec("dnr_signed_date", "Signed Date", None, "eHistory", True, None, "Date document was signed", "timestamp"),
        OcrFieldSpec("dnr_patient_name", "Patient Name", "ePatient.02", "ePatient", True, None, "Patient name on document", "text"),
        OcrFieldSpec("physician_name", "Signing Physician", None, "eHistory", True, None, "Physician who signed the order", "text"),
    ],
    "LAB_REPORT": [
        OcrFieldSpec("glucose_lab", "Glucose", "eVitals.17", "eVitals", False, "mg/dL", "Glucose lab value", "numeric"),
        OcrFieldSpec("potassium", "Potassium", None, "eHistory", False, "mEq/L", "Potassium result", "numeric"),
        OcrFieldSpec("sodium", "Sodium", None, "eHistory", False, "mEq/L", "Sodium result", "numeric"),
        OcrFieldSpec("creatinine", "Creatinine", None, "eHistory", False, "mg/dL", "Creatinine result", "numeric"),
        OcrFieldSpec("hemoglobin", "Hemoglobin", None, "eHistory", False, "g/dL", "Hemoglobin result", "numeric"),
        OcrFieldSpec("hematocrit", "Hematocrit", None, "eHistory", False, "%", "Hematocrit result", "numeric"),
        OcrFieldSpec("wbc", "WBC", None, "eHistory", False, "K/uL", "White blood cell count", "numeric"),
        OcrFieldSpec("platelets", "Platelets", None, "eHistory", False, "K/uL", "Platelet count", "numeric"),
        OcrFieldSpec("troponin", "Troponin", None, "eHistory", False, "ng/mL", "Troponin I or T value", "numeric"),
        OcrFieldSpec("lactate", "Lactate", None, "eHistory", False, "mmol/L", "Serum lactate", "numeric"),
        OcrFieldSpec("inr", "INR", None, "eHistory", False, None, "INR/PT ratio", "numeric"),
        OcrFieldSpec("bnp", "BNP/NT-proBNP", None, "eHistory", False, "pg/mL", "BNP or NT-proBNP value", "numeric"),
        OcrFieldSpec("collection_time", "Collection Time", None, "eTimes", False, None, "Lab collection timestamp", "timestamp"),
    ],
}


def get_device_types() -> list[str]:
    """Return sorted list of all registered device type keys."""
    return sorted(DEVICE_FIELD_REGISTRY.keys())


def get_fields_for_device(device_type: str) -> list[OcrFieldSpec] | None:
    """Return OcrFieldSpec list for a device type, or None if not registered."""
    return DEVICE_FIELD_REGISTRY.get(device_type.upper())


__all__ = [
    "OcrFieldSpec",
    "DEVICE_FIELD_REGISTRY",
    "get_device_types",
    "get_fields_for_device",
]
