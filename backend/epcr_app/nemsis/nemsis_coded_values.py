"""NEMSIS v3.5.1 coded-value set.

A versioned, validated mapping layer for every human-readable label that appears
in an official NEMSIS v3.5.1 CTA HTML test case.  The set is immutable, carries
its schema-version and source URL, and exposes strict lookup helpers that raise
``UnknownCodedValueError`` when a label has no mapping.

Data provenance
---------------
* Schema version: ``3.5.1.251001CP2``
* Primary source: https://nemsis.org/media/nemsis_v3/3.5.1.251001CP2/
* FIPS state / county / city codes: U.S. Census Bureau FIPS (2020 vintage)

No lookup in this module generates a value, falls back to a default, or
silently omits data.  Callers receive either the canonical code or an
explicit error.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from types import MappingProxyType


class UnknownCodedValueError(KeyError):
    """Raised when a human-readable label has no NEMSIS code mapping.

    The exception carries both the lookup category and the unresolved label so
    callers can emit actionable diagnostics.
    """

    def __init__(self, category: str, label: str) -> None:
        """Initialise the exception.

        Args:
            category: Lookup category (e.g. ``"state"``, ``"general"``).
            label: The unresolved human-readable label.

        Returns:
            None.
        """

        super().__init__(f"no NEMSIS code for {category!r} label: {label!r}")
        self.category = category
        self.label = label


# ─────────────────────────────────────────────────────────────────────────────
# FIPS state codes (U.S. Census Bureau)
# ─────────────────────────────────────────────────────────────────────────────

_FIPS_STATES: Mapping[str, str] = MappingProxyType(
    {
        "Alabama": "01",
        "Alaska": "02",
        "Arizona": "04",
        "Arkansas": "05",
        "California": "06",
        "Colorado": "08",
        "Connecticut": "09",
        "Delaware": "10",
        "District of Columbia": "11",
        "Florida": "12",
        "Georgia": "13",
        "Hawaii": "15",
        "Idaho": "16",
        "Illinois": "17",
        "Indiana": "18",
        "Iowa": "19",
        "Kansas": "20",
        "Kentucky": "21",
        "Louisiana": "22",
        "Maine": "23",
        "Maryland": "24",
        "Massachusetts": "25",
        "Michigan": "26",
        "Minnesota": "27",
        "Mississippi": "28",
        "Missouri": "29",
        "Montana": "30",
        "Nebraska": "31",
        "Nevada": "32",
        "New Hampshire": "33",
        "New Jersey": "34",
        "New Mexico": "35",
        "New York": "36",
        "North Carolina": "37",
        "North Dakota": "38",
        "Ohio": "39",
        "Oklahoma": "40",
        "Oregon": "41",
        "Pennsylvania": "42",
        "Rhode Island": "44",
        "South Carolina": "45",
        "South Dakota": "46",
        "Tennessee": "47",
        "Texas": "48",
        "Utah": "49",
        "Vermont": "50",
        "Virginia": "51",
        "Washington": "53",
        "West Virginia": "54",
        "Wisconsin": "55",
        "Wyoming": "56",
    }
)

_ISO_COUNTRIES: Mapping[str, str] = MappingProxyType(
    {
        "United States": "US",
        # ISO-2 passthrough — HTML may already contain the 2-letter code
        "US": "US",
    }
)


# ─────────────────────────────────────────────────────────────────────────────
# FIPS county codes (5-digit = state FIPS + county FIPS)
# ─────────────────────────────────────────────────────────────────────────────

_FIPS_COUNTIES: Mapping[str, str] = MappingProxyType(
    {
        "Covington County": "01039",
        "Okaloosa County": "12091",
        "Baltimore County": "24005",
        "Baltimore City": "24510",
        "Calumet County": "55015",
        "Oglala Lakota County": "46102",
        "Blaine County": "40011",
        "Tulsa County": "40143",
        "Pottawatomie County": "40125",
    }
)


# ─────────────────────────────────────────────────────────────────────────────
# FIPS city / census-designated-place codes
# ─────────────────────────────────────────────────────────────────────────────

_FIPS_CITIES: Mapping[str, str] = MappingProxyType(
    {
        # GNIS feature IDs for all cities referenced in CTA 2025 HTML test cases.
        # NEMSIS uses GNIS codes for CityGnisCode elements (eScene.17, ePatient.06,
        # dFacility.08, dLocation.07, dContact.06, eDisposition.04, dPersonnel.05).
        # Priority per NEMSIS TAC: Civil > Populated Place > Census/Military.
        # Source: USGS GNIS DomesticNames text files (2026-03-26 vintage).
        # https://prd-tnm.s3.amazonaws.com/StagedProducts/GeographicNames/DomesticNames/
        #
        # Florida — Okaloosa County
        "City of Niceville": "2404378",    # Civil
        "Niceville": "2404378",            # resolves to Civil code
        "City of Fort Walton Beach": "2403650",  # Civil
        "Fort Walton Beach": "2403650",
        "City of Crestview": "2404153",    # Civil
        "Crestview": "2404153",
        "City of Destin": "2404223",       # Civil
        "Destin": "2404223",
        "City of Laurel Hill": "2404890",  # Civil
        "Laurel Hill": "2404890",
        "City of Valparaiso": "2405636",   # Civil
        "Valparaiso": "2405636",
        # Okaloosa County — military/unincorporated
        "Eglin Air Force Base": "2512171", # Military
        "Holt": "284195",                  # Populated Place (unincorporated)
        # Florida — Escambia County
        "City of Pensacola": "2404503",    # Civil
        "Pensacola": "2404503",
        # Alabama — Mobile County
        "City of Mobile": "2404278",       # Civil
        "Mobile": "2404278",
        # South Dakota — Oglala Lakota County
        "Oglala": "1261129",               # Populated Place
        # Wisconsin — Calumet County
        "Village of Greenleaf": "2831515", # Civil
        "Greenleaf": "2831515",
    }
)


# ─────────────────────────────────────────────────────────────────────────────
# Element-specific coded-value tables
#
# Each inner dict maps human-readable label → NEMSIS code for one element.
# All codes extracted verbatim from the NEMSIS v3.5.1.251001CP2 XSD files.
# Source: dAgency_v3.xsd, dContact_v3.xsd, dConfiguration_v3.xsd,
#         dVehicle_v3.xsd, dPersonnel_v3.xsd, commonTypes_v3.xsd
# ─────────────────────────────────────────────────────────────────────────────

_ELEMENT_SPECIFIC_MAPPINGS: Mapping[str, Mapping[str, str]] = MappingProxyType(
    {
        # dAgency.09 / dAgency.10 — TypeOfService (commonTypes_v3.xsd)
        "dAgency.09": MappingProxyType(
            {
                "911 Response (Scene) with Transport Capability": "9920001",
                "911 Response (Scene) without Transport Capability": "9920003",
                "Air Medical": "9920005",
                "ALS Intercept": "9920007",
                "Hazmat": "9920011",
                "Medical Transport (Convalescent, Interfacility Transfer Hospital and Nursing Home)": "9920013",
                "Rescue": "9920015",
                "Community Paramedicine": "9920017",
                "Critical Care (Ground)": "9920019",
            }
        ),
        "dAgency.10": MappingProxyType(
            {
                "911 Response (Scene) with Transport Capability": "9920001",
                "911 Response (Scene) without Transport Capability": "9920003",
                "Air Medical": "9920005",
                "ALS Intercept": "9920007",
                "Hazmat": "9920011",
                "Medical Transport (Convalescent, Interfacility Transfer Hospital and Nursing Home)": "9920013",
                "Rescue": "9920015",
                "Community Paramedicine": "9920017",
                "Critical Care (Ground)": "9920019",
            }
        ),
        # dAgency.11 — StateCertificationLicensureLevels (commonTypes_v3.xsd)
        "dAgency.11": MappingProxyType(
            {
                "Advanced Emergency Medical Technician (AEMT)": "9917001",
                "Emergency Medical Technician - Intermediate": "9917002",
                "Emergency Medical Responder (EMR)": "9917003",
                "Emergency Medical Technician (EMT)": "9917005",
                "Paramedic": "9917007",
                "Physician": "9917019",
                "Critical Care Paramedic": "9917021",
                "Community Paramedicine": "9917023",
                "Nurse Practitioner": "9917025",
                "Physician Assistant": "9917027",
                "Licensed Practical Nurse (LPN)": "9917029",
                "Registered Nurse": "9917031",
            }
        ),
        # dAgency.12 — OrganizationStatus (dAgency_v3.xsd)
        "dAgency.12": MappingProxyType(
            {
                "Mixed": "1016001",
                "Non-Volunteer": "1016003",
                "Volunteer": "1016005",
            }
        ),
        # dAgency.13 — OrganizationalType (commonTypes_v3.xsd)
        "dAgency.13": MappingProxyType(
            {
                "Fire Department": "9912001",
                "Governmental, Non-Fire": "9912003",
                "Hospital": "9912005",
                "Private, Nonhospital": "9912007",
                "Tribal": "9912009",
            }
        ),
        # dAgency.14 — AgencyOrganizationalTaxStatus (dAgency_v3.xsd)
        "dAgency.14": MappingProxyType(
            {
                "For Profit": "1018001",
                "Other (e.g., Government)": "1018003",
                "Not For Profit": "1018005",
            }
        ),
        # dContact.01 — AgencyContactType (dContact_v3.xsd)
        "dContact.01": MappingProxyType(
            {
                "Administrative Assistant": "1101001",
                "EMS Agency Director/Chief/Lead Administrator/CEO": "1101003",
                "EMS Assistant Agency Director/Chief/Administrator/CEO": "1101005",
                "EMS Assistant Medical Director": "1101007",
                "EMS IT/Data Specialist": "1101009",
                "EMS Medical Director": "1101011",
                "EMS Quality/Performance Improvement Specialist": "1101013",
                "EMS Training/Education Specialist": "1101015",
                "Other": "1101017",
            }
        ),
        # dContact.14 — AgencyMedicalDirectorBoardCertificationType (dContact_v3.xsd)
        "dContact.14": MappingProxyType(
            {
                "Allergy and Immunology": "1114001",
                "Anesthesiology": "1114003",
                "Colon and Rectal Surgery": "1114005",
                "Dermatology": "1114007",
                "Emergency Medicine": "1114009",
                "Family Medicine": "1114011",
                "Internal Medicine": "1114013",
                "Neurological Surgery": "1114015",
                "Neurology": "1114017",
                "None (Not Board Certified)": "1114019",
                "Obstetrics and Gynecology": "1114021",
                "Ophthalmology": "1114023",
                "Orthopedic Surgery": "1114025",
                "Otolaryngology": "1114027",
                "Pediatrics": "1114029",
                "Physical Medicine and Rehabilitation": "1114031",
                "Plastic Surgery": "1114033",
                "Psychiatry": "1114035",
                "Surgery": "1114037",
                "Thoracic Surgery": "1114039",
                "Urology": "1114041",
                "Vascular Surgery": "1114043",
            }
        ),
        # dConfiguration.10 — ProtocolsUsed (commonTypes_v3.xsd)
        "dConfiguration.10": MappingProxyType(
            {
                "Airway": "9914001",
                "Airway-Failed": "9914003",
                "Airway-Obstruction/Foreign Body": "9914005",
                "Airway-Rapid Sequence Induction (RSI-Paralytic)": "9914007",
                "Airway-Sedation Assisted (Non-Paralytic)": "9914009",
                "Cardiac Arrest-Asystole": "9914011",
                "Cardiac Arrest-Hypothermia-Therapeutic": "9914013",
                "Cardiac Arrest-Pulseless Electrical Activity": "9914015",
                "Cardiac Arrest-Ventricular Fibrillation/ Pulseless Ventricular Tachycardia": "9914017",
                "Cardiac Arrest-Post Resuscitation Care": "9914019",
                "Environmental-Altitude Sickness": "9914021",
                "Environmental-Cold Exposure": "9914023",
                "Environmental-Frostbite/Cold Injury": "9914025",
                "Environmental-Heat Exposure/Exhaustion": "9914027",
                "Environmental-Heat Stroke/Hyperthermia": "9914029",
                "Environmental-Hypothermia": "9914031",
                "Exposure-Airway/Inhalation Irritants": "9914033",
                "Exposure-Biological/Infectious": "9914035",
                "Exposure-Blistering Agents": "9914037",
                "Exposure-Chemicals to Eye": "9914041",
                "Exposure-Cyanide": "9914043",
                "Exposure-Explosive/ Blast Injury": "9914045",
                "Exposure-Nerve Agents": "9914047",
                "Exposure-Radiologic Agents": "9914049",
                "General-Back Pain": "9914051",
                "General-Behavioral/Patient Restraint": "9914053",
                "General-Cardiac Arrest": "9914055",
                "General-Dental Problems": "9914057",
                "General-Epistaxis": "9914059",
                "General-Fever": "9914061",
                "General-Individualized Patient Protocol": "9914063",
                "General-Indwelling Medical Devices/Equipment": "9914065",
                "General-IV Access": "9914067",
                "General-Medical Device Malfunction": "9914069",
                "General-Pain Control": "9914071",
                "General-Spinal Immobilization/Clearance": "9914073",
                "General-Universal Patient Care/ Initial Patient Contact": "9914075",
                "Injury-Amputation": "9914077",
                "Injury-Bites and Envenomations-Land": "9914079",
                "Injury-Bites and Envenomations-Marine": "9914081",
                "Injury-Bleeding/ Hemorrhage Control": "9914083",
                "Injury-Burns-Thermal": "9914085",
                "Injury-Cardiac Arrest": "9914087",
                "Injury-Crush Syndrome": "9914089",
                "Injury-Diving Emergencies": "9914091",
                "Injury-Drowning/Near Drowning": "9914093",
                "Injury-Electrical Injuries": "9914095",
                "Injury-Extremity": "9914097",
                "Injury-Eye": "9914099",
                "Injury-Head": "9914101",
                "Injury-Impaled Object": "9914103",
                "Injury-Multisystem": "9914105",
                "Injury-Spinal Cord": "9914107",
                "Medical-Abdominal Pain": "9914109",
                "Medical-Allergic Reaction/Anaphylaxis": "9914111",
                "Medical-Altered Mental Status": "9914113",
                "Medical-Bradycardia": "9914115",
                "Medical-Cardiac Chest Pain": "9914117",
                "Medical-Diarrhea": "9914119",
                "Medical-Hyperglycemia": "9914121",
                "Medical-Hypertension": "9914123",
                "Medical-Hypoglycemia/Diabetic Emergency": "9914125",
                "Medical-Hypotension/Shock (Non-Trauma)": "9914127",
                "Medical-Influenza-Like Illness/ Upper Respiratory Infection": "9914129",
                "Medical-Nausea/Vomiting": "9914131",
                "Medical-Newborn/ Neonatal Resuscitation": "9914133",
                "General-Overdose/Poisoning/Toxic Ingestion": "9914135",
                "Medical-Pulmonary Edema/CHF": "9914137",
                "Medical-Respiratory Distress/Asthma/COPD/Reactive Airway": "9914139",
                "Medical-Seizure": "9914141",
                "Medical-ST-Elevation Myocardial Infarction (STEMI)": "9914143",
                "Medical-Stroke/TIA": "9914145",
                "Medical-Supraventricular Tachycardia (Including Atrial Fibrillation)": "9914147",
                "Medical-Syncope": "9914149",
                "Medical-Ventricular Tachycardia (With Pulse)": "9914151",
                "Not Done": "9914153",
                "OB/GYN-Childbirth/Labor/Delivery": "9914155",
                "OB/GYN-Eclampsia": "9914157",
                "OB/GYN-Gynecologic Emergencies": "9914159",
                "OB/GYN-Pregnancy Related Emergencies": "9914161",
                "OB/GYN-Post-partum Hemorrhage": "9914163",
                "Other": "9914165",
                "Exposure-Carbon Monoxide": "9914167",
                "Cardiac Arrest-Do Not Resuscitate": "9914169",
                "Cardiac Arrest-Special Resuscitation Orders": "9914171",
                "Exposure-Smoke Inhalation": "9914173",
                "General-Community Paramedicine / Mobile Integrated Healthcare": "9914175",
                "General-Exception Protocol": "9914177",
                "General-Extended Care Guidelines": "9914179",
                "General-Interfacility Transfers": "9914181",
                "General-Law Enforcement - Blood for Legal Purposes": "9914183",
                "General-Law Enforcement - Assist with Law Enforcement Activity": "9914185",
                "General-Neglect or Abuse Suspected": "9914187",
                "General-Refusal of Care": "9914189",
                "Injury-Mass/Multiple Casualties": "9914191",
                "Injury-Thoracic": "9914193",
                "Medical-Adrenal Insufficiency": "9914195",
                "Medical-Apparent Life Threatening Event (ALTE)": "9914197",
                "Medical-Tachycardia": "9914199",
                "Cardiac Arrest-Determination of Death / Withholding Resuscitative Efforts": "9914201",
                "Injury-Conducted Electrical Weapon (e.g., Taser)": "9914203",
                "Injury-Facial Trauma": "9914205",
                "Injury-General Trauma Management": "9914207",
                "Injury-Lightning/Lightning Strike": "9914209",
                "Injury-SCUBA Injury/Accidents": "9914211",
                "Injury-Topical Chemical Burn": "9914213",
                "Medical-Beta Blocker Poisoning/Overdose": "9914215",
                "Medical-Calcium Channel Blocker Poisoning/Overdose": "9914217",
                "Medical-Opioid Poisoning/Overdose": "9914219",
                "Medical-Respiratory Distress-Bronchiolitis": "9914221",
                "Medical-Respiratory Distress-Croup": "9914223",
                "Medical-Stimulant Poisoning/Overdose": "9914225",
            }
        ),
        # dVehicle.04 — VehicleType (dVehicle_v3.xsd)
        "dVehicle.04": MappingProxyType(
            {
                "Ambulance": "1404001",
                "ATV": "1404003",
                "Bicycle": "1404005",
                "Fire Apparatus": "1404007",
                "Fixed Wing": "1404009",
                "Motorcycle": "1404011",
                "Other": "1404013",
                "Personal Vehicle": "1404015",
                "Quick Response Vehicle (Non-Transport Vehicle other than Fire Apparatus)": "1404017",
                "Rescue": "1404019",
                "Rotor Craft": "1404021",
                "Snow Vehicle": "1404023",
                "Watercraft": "1404025",
            }
        ),
        # dPersonnel.15 — PersonnelHighestEducationalDegree (dPersonnel_v3.xsd)
        "dPersonnel.15": MappingProxyType(
            {
                "No Schooling Completed": "1515001",
                "Nursery School to 4th Grade": "1515003",
                "5th Grade or 6th Grade": "1515005",
                "7th Grade or 8th Grade": "1515007",
                "9th Grade": "1515009",
                "10th Grade": "1515011",
                "11th Grade": "1515013",
                "12th Grade, No Diploma": "1515015",
                "High School Graduate-Diploma or the Equivalent (GED)": "1515017",
                "Some College Credit, but Less than 1 Year": "1515019",
                "1 or More Years of College, No Degree": "1515021",
                "Associate Degree": "1515023",
                "Bachelor's Degree": "1515025",
                "Master's Degree": "1515027",
                "Professional Degree (i.e. MD, DDS, DVM, LLB, JD)": "1515029",
                "Doctorate Degree (i.e. PhD, EdD)": "1515031",
            }
        ),
        # dPersonnel.16 — PersonnelDegreeFieldofStudy (dPersonnel_v3.xsd)
        "dPersonnel.16": MappingProxyType(
            {
                "Agriculture and Natural Resources": "1516001",
                "Architecture and Related Services": "1516003",
                "Area, Ethnic, Cultural, and Gender Studies": "1516005",
                "Biological and Biomedical Sciences": "1516007",
                "Business": "1516009",
                "Communication, Journalism, and Related Programs": "1516011",
                "Communications Technologies": "1516013",
                "Computer and Information Sciences": "1516015",
                "Education": "1516017",
                "Emergency Medical Services": "1516019",
                "Engineering": "1516021",
                "Engineering Technologies": "1516023",
                "English Language and Literature/Letters": "1516025",
                "Family and Consumer Sciences/Human Sciences": "1516027",
                "Fire Science": "1516029",
                "Foreign Languages, Literatures, and Linguistics": "1516031",
                "Health Professions and Related Clinical Sciences, Not Including Emergency Medical Services": "1516033",
                "Legal Professions and Studies": "1516035",
                "Liberal Arts and Sciences, General Studies, and Humanities": "1516037",
                "Library Science": "1516039",
                "Mathematics and Statistics": "1516041",
                "Military Technologies": "1516043",
                "Multi/Interdisciplinary Studies": "1516045",
                "Not Classified by Field of Study": "1516047",
                "None": "1516049",
                "Parks, Recreation, Leisure and Fitness Studies": "1516051",
                "Philosophy and Religious Studies": "1516053",
                "Physical Sciences and Science Technologies": "1516055",
                "Precision Production": "1516057",
                "Psychology": "1516059",
                "Public Administration and Social Services": "1516061",
                "Security and Protective Services, Not Including Fire Science": "1516063",
                "Social Sciences and History": "1516065",
                "Theology and Religious Vocations": "1516067",
                "Transportation and Materials Moving": "1516069",
                "Visual and Performing Arts": "1516071",
            }
        ),
        # dAgency.23 — EMSAgencyTimeZone (dAgency_v3.xsd)
        "dAgency.23": MappingProxyType(
            {
                "All other time zones": "1027001",
                "GMT-04:00 Atlantic Time": "1027003",
                "GMT-05:00 Eastern Time": "1027005",
                "GMT-06:00 Central Time": "1027007",
                "GMT-07:00 Mountain Time": "1027009",
                "GMT-08:00 Pacific Time": "1027011",
                "GMT-09:00 Alaska": "1027013",
                "GMT-10:00 Hawaii": "1027015",
                "GMT-11:00 Midway Island, Samoa": "1027017",
            }
        ),
        # dContact.13 — AgencyMedicalDirectorDegree (dContact_v3.xsd)
        "dContact.13": MappingProxyType(
            {
                "Doctor of Medicine": "1113001",
                "Doctor of Osteopathy": "1113003",
            }
        ),
        # dContact.15 — MedicalDirectorCompensation (dContact_v3.xsd)
        "dContact.15": MappingProxyType(
            {
                "Compensated": "1115001",
                "Non-Compensated": "1115003",
                # HTML label variants
                "Non-Compensated/Volunteer": "1115003",
            }
        ),
        # dConfiguration.06 — StateCertificationLicensureLevels (dConfiguration_v3.xsd)
        # Same type as dConfiguration.08 and dAgency.11
        "dConfiguration.06": MappingProxyType(
            {
                "Advanced Emergency Medical Technician (AEMT)": "9917001",
                "Emergency Medical Technician - Intermediate": "9917002",
                "Emergency Medical Responder (EMR)": "9917003",
                "Emergency Medical Technician (EMT)": "9917005",
                "Paramedic": "9917007",
                "Physician": "9917019",
                "Critical Care Paramedic": "9917021",
                "Community Paramedicine": "9917023",
                "Nurse Practitioner": "9917025",
                "Physician Assistant": "9917027",
                "Licensed Practical Nurse (LPN)": "9917029",
                "Registered Nurse": "9917031",
            }
        ),
        # dConfiguration.11 — AgencySpecialtyServiceCapability (dConfiguration_v3.xsd)
        "dConfiguration.11": MappingProxyType(
            {
                "Air Rescue": "1211001",
                "CBRNE": "1211003",
                "Community Health Medicine": "1211005",
                "Disaster Medical Assistance Team (DMAT)": "1211007",
                "Disaster Mortuary (DMORT)": "1211009",
                "Dive Rescue": "1211011",
                "Farm Rescue": "1211013",
                "High Angle Rescue": "1211015",
                "Machinery Disentanglement": "1211017",
                "None": "1211019",
                "Ski / Snow Rescue": "1211021",
                "Tactical EMS": "1211023",
                "Trench / Confined Space Rescue": "1211025",
                "Urban Search and Rescue (USAR)": "1211027",
                "Vehicle Extrication": "1211029",
                "Veterinary Medical Assistance Team (VMAT)": "1211031",
                "Water or Ice Related Rescue (Incl Swift Water)": "1211033",
                "Wilderness Search and Rescue": "1211035",
            }
        ),
        # dConfiguration.13 — EMDtoAgencyServiceArea (dConfiguration_v3.xsd)
        "dConfiguration.13": MappingProxyType(
            {
                "No": "1213001",
                "Yes, 100% of the EMS Agency's Service Area": "1213003",
                "Yes, Less than 100% of the EMS Agency's Service Area": "1213005",
            }
        ),
        # dConfiguration.15 — PatientMonitoringCapability (dConfiguration_v3.xsd)
        "dConfiguration.15": MappingProxyType(
            {
                "Capnography-Numeric": "1215001",
                "Capnography-Waveform": "1215003",
                "ECG-12 Lead or Greater": "1215005",
                "ECG-Less than 12 Lead (Cardiac Monitor)": "1215007",
                "Oximetry-Carbon Monoxide": "1215009",
                "Oximetry-Oxygen": "1215011",
                "Pressure Measurement-Invasive (Arterial, CVP, Swan, etc.)": "1215013",
                "Pressure Measurement-Non-Invasive (Blood Pressure, etc.)": "1215015",
                "Ventilator-Transport": "1215017",
                "Vital Sign Monitoring": "1215019",
            }
        ),
        # eResponse.08 — EMSDispatchDelayReason (eResponse_v3.xsd)
        "eResponse.08": MappingProxyType(
            {
                "Caller (Uncooperative)": "2208001",
                "Diversion/Failure (of previous unit)": "2208003",
                "High Call Volume": "2208005",
                "Language Barrier": "2208007",
                "Incomplete Address Information Provided": "2208009",
                "No EMS Vehicles (Units) Available": "2208011",
                "None/No Delay": "2208013",
                "Other": "2208015",
                "Technical Failure (Computer, Phone etc.)": "2208017",
                "Communication Specialist-Assignment Error": "2208019",
                "No Receiving MD, Bed, Hospital": "2208021",
                "Specialty Team Delay": "2208023",
            }
        ),
        # eResponse.09 — EMSUnitDelayReason (eResponse_v3.xsd)
        "eResponse.09": MappingProxyType(
            {
                "Crowd": "2209001",
                "Directions/Unable to Locate": "2209003",
                "Distance": "2209005",
                "Diversion (Different Incident)": "2209007",
                "HazMat": "2209009",
                "None/No Delay": "2209011",
                "Other": "2209013",
                "Rendezvous Transport Unavailable": "2209015",
                "Route Obstruction (e.g., Train)": "2209017",
                "Scene Safety (Not Secure for EMS)": "2209019",
                "Staff Delay": "2209021",
                "Traffic": "2209023",
                "Vehicle Crash Involving this Unit": "2209025",
                "Vehicle Failure of this Unit": "2209027",
                "Weather": "2209029",
                "Mechanical Issue-Unit, Equipment, etc.": "2209031",
                "Flight Planning": "2209033",
                "Out of Service Area Response": "2209035",
            }
        ),
        # eResponse.10 — EMSSceneUnitDelayReason (eResponse_v3.xsd)
        "eResponse.10": MappingProxyType(
            {
                "Awaiting Air Unit": "2210001",
                "Awaiting Ground Unit": "2210003",
                "Crowd": "2210005",
                "Directions/Unable to Locate": "2210007",
                "Distance": "2210009",
                "Extrication": "2210011",
                "HazMat": "2210013",
                "Language Barrier": "2210015",
                "None/No Delay": "2210017",
                "Other": "2210019",
                "Patient Access": "2210021",
                "Safety-Crew/Staging": "2210023",
                "Safety-Patient": "2210025",
                "Staff Delay": "2210027",
                "Traffic": "2210029",
                "Triage/Multiple Patients": "2210031",
                "Vehicle Crash Involving this Unit": "2210033",
                "Vehicle Failure of this Unit": "2210035",
                "Weather": "2210037",
                "Mechanical Issue-Unit, Equipment, etc.": "2210039",
            }
        ),
        # eResponse.11 — EMSTransportUnitDelayReason (eResponse_v3.xsd)
        "eResponse.11": MappingProxyType(
            {
                "Crowd": "2211001",
                "Directions/Unable to Locate": "2211003",
                "Distance": "2211005",
                "Diversion": "2211007",
                "HazMat": "2211009",
                "None/No Delay": "2211011",
                "Other": "2211013",
                "Rendezvous Transport Unavailable": "2211015",
                "Route Obstruction (e.g., Train)": "2211017",
                "Safety": "2211019",
                "Staff Delay": "2211021",
                "Traffic": "2211023",
                "Vehicle Crash Involving this Unit": "2211025",
                "Vehicle Failure of this Unit": "2211027",
                "Weather": "2211029",
                "Patient Condition Change (e.g., Unit Stopped)": "2211031",
            }
        ),
        # eResponse.12 — EMSTurnaroundUnitDelayReason (eResponse_v3.xsd)
        "eResponse.12": MappingProxyType(
            {
                "Clean-up": "2212001",
                "Decontamination": "2212003",
                "Distance": "2212005",
                "Documentation": "2212007",
                "ED Overcrowding / Transfer of Care": "2212009",
                "Equipment Failure": "2212011",
                "Equipment/Supply Replenishment": "2212013",
                "None/No Delay": "2212015",
                "Other": "2212017",
                "Rendezvous Transport Unavailable": "2212019",
                "Route Obstruction (e.g., Train)": "2212021",
                "Staff Delay": "2212023",
                "Traffic": "2212025",
                "Vehicle Crash of this Unit": "2212027",
                "Vehicle Failure of this Unit": "2212029",
                "Weather": "2212031",
                "EMS Crew Accompanies Patient for Facility Procedure": "2212033",
            }
        ),
        # eResponse.24 — EMSAdditionalResponseMode (eResponse_v3.xsd)
        "eResponse.24": MappingProxyType(
            {
                "Intersection Navigation-Against Normal Light  Patterns": "2224001",
                "Intersection Navigation-Against Normal Light Patterns": "2224001",
                "Intersection Navigation-With Automated Light Changing Technology": "2224003",
                "Intersection Navigation-With Normal Light Patterns": "2224005",
                "Scheduled": "2224007",
                "Speed-Enhanced per Local Policy": "2224009",
                "Speed-Normal Traffic": "2224011",
                "Unscheduled": "2224013",
                "Lights and Sirens": "2224015",
                "Lights and No Sirens": "2224017",
                "No Lights or Sirens": "2224019",
                "Initial No Lights or Sirens, Upgraded to Lights and Sirens": "2224021",
                "Initial Lights and Sirens, Downgraded to No Lights or Sirens": "2224023",
            }
        ),
        # eSituation.02 — YesNoUnkValues (eSituation_v3.xsd)
        "eSituation.02": MappingProxyType(
            {
                "No": "9922001",
                "Unknown": "9922003",
                "Yes": "9922005",
            }
        ),
        # eSituation.06 — TimeUnitsOfChiefComplaint (eSituation_v3.xsd)
        "eSituation.06": MappingProxyType(
            {
                "Seconds": "2806001",
                "Minutes": "2806003",
                "Hours": "2806005",
                "Days": "2806007",
                "Weeks": "2806009",
                "Months": "2806011",
                "Years": "2806013",
            }
        ),
        # eSituation.14 — YesNoUnkValues (eSituation_v3.xsd)
        "eSituation.14": MappingProxyType(
            {
                "No": "9922001",
                "Unknown": "9922003",
                "Yes": "9922005",
            }
        ),
        # eArrest.01 — CardiacArrest (eArrest_v3.xsd)
        "eArrest.01": MappingProxyType(
            {
                "No": "3001001",
                "Yes, Prior to Any EMS Arrival": "3001003",
                "Yes, Prior to Any EMS Arrival (includes Transport EMS & Medical First Responders)": "3001003",
                "Yes, After EMS Arrival": "3001005",
                "Yes, After Any EMS Arrival (includes Transport EMS & Medical First Responders)": "3001005",
            }
        ),
        # eHistory.05 — AdvanceDirectives (eHistory_v3.xsd)
        "eHistory.05": MappingProxyType(
            {
                "Family/Guardian request DNR (but no documentation)": "3105001",
                "Living Will": "3105003",
                "None": "3105005",
                "Other": "3105007",
                "Other Healthcare Advanced Directive Form": "3105009",
                "State EMS DNR or Medical Order Form": "3105011",
                # HTML label variants
                "DNR": "3105011",
                "Comfort Measures Only": "3105003",
            }
        ),
        # eDispatch.01 — DispatchReason (eDispatch_v3.xsd) — complete v3.5.1 list
        "eDispatch.01": MappingProxyType(
            {
                "Abdominal Pain/Problems": "2301001",
                "Allergic Reaction/Stings": "2301003",
                "Animal Bite": "2301005",
                "Assault": "2301007",
                "Automated Crash Notification": "2301009",
                "Back Pain (Non-Traumatic)": "2301011",
                "Breathing Problem": "2301013",
                "Burns/Explosion": "2301015",
                "Carbon Monoxide/Hazmat/Inhalation/CBRN": "2301017",
                "Cardiac Arrest/Death": "2301019",
                "Chest Pain (Non-Traumatic)": "2301021",
                "Choking": "2301023",
                "Convulsions/Seizure": "2301025",
                "Diabetic Problem": "2301027",
                "Electrocution/Lightning": "2301029",
                "Eye Problem/Injury": "2301031",
                "Falls": "2301033",
                "Fire": "2301035",
                "Headache": "2301037",
                "Healthcare Professional/Admission": "2301039",
                "Heart Problems/AICD": "2301041",
                "Heat/Cold Exposure": "2301043",
                "Hemorrhage/Laceration": "2301045",
                "Industrial Accident/Inaccessible Incident/Other Entrapments (Non-Vehicle)": "2301047",
                "Medical Alarm": "2301049",
                "No Other Appropriate Choice": "2301051",
                "Overdose/Poisoning/Ingestion": "2301053",
                "Pandemic/Epidemic/Outbreak": "2301055",
                "Pregnancy/Childbirth/Miscarriage": "2301057",
                "Psychiatric Problem/Abnormal Behavior/Suicide Attempt": "2301059",
                "Sick Person": "2301061",
                "Stab/Gunshot Wound/Penetrating Trauma": "2301063",
                "Standby": "2301065",
                "Stroke/CVA": "2301067",
                "Traffic/Transportation Incident": "2301069",
                "Transfer/Interfacility/Palliative Care": "2301071",
                "Traumatic Injury": "2301073",
                "Well Person Check": "2301075",
                "Unconscious/Fainting/Near-Fainting": "2301077",
                "Unknown Problem/Person Down": "2301079",
                "Drowning/Diving/SCUBA Accident": "2301081",
                "Airmedical Transport": "2301083",
                "Altered Mental Status": "2301085",
                "Intercept": "2301087",
                "Nausea": "2301089",
                "Vomiting": "2301091",
                "Hanging/Strangulation/Asphyxiation": "2301093",
                "Intoxicated Subject": "2301095",
                "EMS Requested by Law Enforcement": "2301097",
                "Active Shooter": "2301099",
            }
        ),
        # eDispatch.02 — EMDPerformed (eDispatch_v3.xsd)
        "eDispatch.02": MappingProxyType(
            {
                "No": "2302001",
                "Yes, With Pre-Arrival Instructions": "2302003",
                "Yes, Without Pre-Arrival Instructions": "2302005",
                "Yes, Unknown if Pre-Arrival Instructions Given": "2302007",
            }
        ),
        # eDispatch.05 — DispatchPriority (eDispatch_v3.xsd)
        "eDispatch.05": MappingProxyType(
            {
                "Critical": "2305001",
                "Emergent": "2305003",
                "Lower Acuity": "2305005",
                "Non-Acute [e.g., Scheduled Transfer  or Standby]": "2305007",
                "Non-Acute (e.g., Scheduled Transfer or Standby)": "2305007",
            }
        ),
        # eCrew.02 — MemberLevel (eCrew_v3.xsd) — distinct from StateCertificationLicensureLevels
        "eCrew.02": MappingProxyType(
            {
                "Advanced Emergency Medical Technician (AEMT)": "9925001",
                "Emergency Medical Technician - Intermediate": "9925002",
                "Emergency Medical Responder (EMR)": "9925003",
                "Emergency Medical Technician (EMT)": "9925005",
                "Paramedic": "9925007",
                "Other Healthcare Professional": "9925023",
                "Other Non-Healthcare Professional": "9925025",
                "Physician": "9925027",
                "Respiratory Therapist": "9925029",
                "Student": "9925031",
                "Critical Care Paramedic": "9925033",
                "Community Paramedicine": "9925035",
                "Nurse Practitioner": "9925037",
                "Physician Assistant": "9925039",
                "Licensed Practical Nurse (LPN)": "9925041",
                "Registered Nurse": "9925043",
            }
        ),
        # ePatient.14 — Race (ePatient_v3.xsd)
        "ePatient.14": MappingProxyType(
            {
                "American Indian or Alaska Native": "2514001",
                "Asian": "2514003",
                "Black or African American": "2514005",
                "Hispanic or Latino": "2514007",
                "Native Hawaiian or Other Pacific Islander": "2514009",
                "White": "2514011",
                "Middle Eastern or North African": "2514013",
            }
        ),
        # ePatient.24 — PatientPreferredLanguage (ePatient_v3.xsd)
        # Uses ISO 639-2/T language codes (3-letter or 2-letter alpha codes)
        "ePatient.24": MappingProxyType(
            {
                "Amharic": "amh",
                "Arabic": "ara",
                "Armenian": "arm",
                "Bengali": "ben",
                "Cajun (Creole and Pidgins)": "crp",
                "Chinese": "chi",
                "Croatian": "hrv",
                "Czech": "cze",
                "Danish": "dan",
                "Dutch": "dut",
                "English": "eng",
                "Finnish": "fin",
                "Formosan": "tai",
                "French": "fre",
                "French Creole": "cpf",
                "German": "ger",
                "Greek": "gre",
                "Gujarati": "guj",
                "Hebrew": "heb",
                "Hindi (Urdu)": "hin",
                "Hungarian": "hun",
                "Ilocano": "ilo",
                "Italian": "itl",
                "Japanese": "jpn",
                "Korean": "kor",
                "Kru": "kro",
                "Lithuanian": "lit",
                "Malayalam": "mal",
                "Miao (Hmong)": "hmn",
                "Mon-Khmer (Cambodian)": "mkh",
                "Navaho": "nav",
                "Norwegian": "nno",
                "Panjabi": "pan",
                "Pennsylvania Dutch (Germanic Other)": "gem",
                "Persian": "per",
                "Polish": "pol",
                "Portuguese": "por",
                "Romanian": "rum",
                "Russian": "rus",
                "Sign Languages": "sgn",
                "Samoan": "smo",
                "Serbo-Croatian": "srp",
                "Slovak": "slo",
                "Spanish": "spa",
                "Swedish": "swe",
                "Syriac": "syr",
                "Tagalog": "tgl",
                "Thai (Laotian)": "tha",
                "Turkish": "tur",
                "Ukrainian": "ukr",
                "Vietnamese": "vie",
                "Yiddish": "yid",
            }
        ),
        # ePayment.01 — PrimaryMethodOfPayment (ePayment_v3.xsd)
        "ePayment.01": MappingProxyType(
            {
                "Insurance": "2601001",
                "Medicaid": "2601003",
                "Medicare": "2601005",
                "Not Billed (for any reason)": "2601007",
                "Other Government": "2601009",
                "Self Pay": "2601011",
                "Workers Compensation": "2601013",
                "Payment by Facility": "2601015",
                "Contracted Payment": "2601017",
                "Community Network": "2601019",
                "No Insurance Identified": "2601021",
                "Other Payment Option": "2601023",
                # Legacy / alternate HTML label variants
                "Workmen's Compensation": "2601013",
                "VA": "2601009",
                "CHAMPUS": "2601005",
                "Champus": "2601005",
            }
        ),
        # ePayment.11 — InsuranceCompanyBillingPriority (ePayment_v3.xsd)
        "ePayment.11": MappingProxyType(
            {
                "Other": "2611001",
                "Primary": "2611003",
                "Secondary": "2611005",
                "Tertiary": "2611007",
                "Payer Responsibility Four": "2611009",
                "Payer Responsibility Five": "2611011",
                "Payer Responsibility Six": "2611013",
                "Payer Responsibility Seven": "2611015",
                "Payer Responsibility Eight": "2611017",
                "Payer Responsibility Nine": "2611019",
                "Payer Responsibility Ten": "2611021",
                "Payer Responsibility Eleven": "2611023",
                "Unknown": "2611025",
            }
        ),
        # ePayment.22 — RelationshipToInsured (ePayment_v3.xsd)
        "ePayment.22": MappingProxyType(
            {
                "Self": "2622001",
                "Spouse": "2622003",
                "Child/Dependent": "2622005",
                "Cadaver Donor": "2622009",
                "Employee": "2622011",
                "Life/Domestic Partner": "2622013",
                "Organ Donor": "2622015",
                "Unknown": "2622017",
                "Other Relationship": "2622019",
            }
        ),
        # ePayment.41 — TransportAssessment (ePayment_v3.xsd)
        "ePayment.41": MappingProxyType(
            {
                "Unable to sit without assistance": "2641001",
                "Unable to stand without assistance": "2641003",
                "Unable to walk without assistance": "2641005",
            }
        ),
    }
)


# ─────────────────────────────────────────────────────────────────────────────
# XSD-derived element-specific mappings
#
# Auto-generated from the NEMSIS v3.5.1 XSDs at import time (artifact located
# at ``artifact/generated/2025/.xsd_enums.json``).  For every NEMSIS element
# whose declared type is a ``simpleType`` with an ``xs:enumeration``, we build
# a ``{label: code, code: code}`` table so the runtime translator can resolve
# both human labels and pre-coded values.  Hand-curated entries above win on
# conflict and extend the auto-generated tables with synonyms / edge cases.
#
# If the XSD artifact is missing (e.g. wheel install without dev assets), the
# generator degrades to the hand-curated table only.  This never silently
# succeeds with bad data: translation still raises ``UnknownCodedValueError``
# for any unmapped label.
# ─────────────────────────────────────────────────────────────────────────────

_XSD_ENUMS_JSON = (
    Path(__file__).resolve().parents[3]
    / "artifact"
    / "generated"
    / "2025"
    / ".xsd_enums.json"
)


def _load_xsd_enums() -> dict:
    """Load the XSD-derived enumeration artifact.

    Returns an empty scaffold if the artifact is missing so that the module
    still imports cleanly in environments without the development assets.
    Callers relying on XSD-backed coverage must ensure the artifact is built
    via ``scripts/extract_xsd_enums.py``.
    """

    if not _XSD_ENUMS_JSON.is_file():
        return {"simple_types": {}, "element_types": {}, "element_inline_enums": {}}
    return json.loads(_XSD_ENUMS_JSON.read_text(encoding="utf-8"))


def _build_full_element_specific() -> Mapping[str, Mapping[str, str]]:
    """Merge XSD-derived element enumerations with hand-curated overrides.

    Priority order (last write wins):

    1. XSD ``element → simpleType`` enumeration tables.
    2. XSD inline (anonymous) enumeration tables.
    3. Hand-curated :data:`_ELEMENT_SPECIFIC_MAPPINGS` overrides.
    """

    data = _load_xsd_enums()
    simple_types = data.get("simple_types", {})
    element_types = data.get("element_types", {})
    inline = data.get("element_inline_enums", {})

    full: dict[str, dict[str, str]] = {}

    for element_id, type_name in element_types.items():
        local = type_name.split(":", 1)[-1] if isinstance(type_name, str) else ""
        enum = simple_types.get(local)
        if not enum:
            continue
        table: dict[str, str] = {}
        for code, label in enum.items():
            table[code] = code
            if label:
                table[label] = code
                combined = f"{code} - {label}"
                table[combined] = code
        full[element_id] = table

    for element_id, enum in inline.items():
        table = full.setdefault(element_id, {})
        for code, label in enum.items():
            table.setdefault(code, code)
            if label:
                if label not in table:
                    table[label] = code
                combined = f"{code} - {label}"
                table.setdefault(combined, code)

    for element_id, override in _ELEMENT_SPECIFIC_MAPPINGS.items():
        merged = dict(full.get(element_id, {}))
        for label, code in override.items():
            merged[label] = code
        full[element_id] = merged

    return MappingProxyType(
        {k: MappingProxyType(v) for k, v in full.items()}
    )


_ELEMENT_SPECIFIC_FULL: Mapping[str, Mapping[str, str]] = _build_full_element_specific()


# ─────────────────────────────────────────────────────────────────────────────
# NV (Not-Value) codes
# ─────────────────────────────────────────────────────────────────────────────

_NV_CODES: Mapping[str, str] = MappingProxyType(
    {
        "Not Applicable": "7701001",
        "Not Recorded": "7701003",
        "Not Reporting": "7701005",
        "Not Known": "7701007",
        "Refused": "8801019",
        "Unable to Complete": "8801023",
        "Symptom Not Present": "8801015",
        "Exam Finding Not Present": "8801015",
        "No Known Drug Allergy": "8801023",
        "None Reported": "8801015",
        "Approximate": "8801029",
    }
)


# ─────────────────────────────────────────────────────────────────────────────
# PN (Pertinent Negative) attribute codes
# ─────────────────────────────────────────────────────────────────────────────

_PN_CODES: Mapping[str, str] = MappingProxyType(
    {
        # Source: commonTypes_v3.xsd — PN.* simpleTypes
        "Approximate": "8801029",
        "Contraindication Noted": "8801001",
        "Denied By Order": "8801003",
        "Exam Finding Not Present": "8801005",
        "Medication Allergy": "8801007",
        "Medication Already Taken": "8801009",
        "No Known Drug Allergy": "8801013",
        "None Reported": "8801015",
        "Not Immunized": "8801025",
        "Not Performed by EMS": "8801017",
        "Order Criteria Not Met": "8801027",
        "Refused": "8801019",
        "Symptom Not Present": "8801031",
        "Unable to Complete": "8801023",
        "Unresponsive": "8801021",
    }
)


# ─────────────────────────────────────────────────────────────────────────────
# Phone / Email type attribute codes
# ─────────────────────────────────────────────────────────────────────────────

_PHONE_TYPES: Mapping[str, str] = MappingProxyType(
    {
        # Source: commonTypes_v3.xsd — PhoneNumberType simpleType
        "Fax": "9913001",
        "Home": "9913003",
        "Mobile": "9913005",
        "Pager": "9913007",
        "Work": "9913009",
    }
)

_EMAIL_TYPES: Mapping[str, str] = MappingProxyType(
    {
        "Work": "9904001",
        "Personal": "9904003",
    }
)


# ─────────────────────────────────────────────────────────────────────────────
# ETCO2 / Distance unit attribute codes
# ─────────────────────────────────────────────────────────────────────────────

_ETCO2_UNITS: Mapping[str, str] = MappingProxyType(
    {
        "mmHg": "3340001",
        "kPa": "3340003",
        "%": "3340005",
    }
)

_DISTANCE_UNITS: Mapping[str, str] = MappingProxyType(
    {
        "Miles": "9929001",
        "Kilometers": "9929003",
    }
)


# ─────────────────────────────────────────────────────────────────────────────
# General coded-value table
#
# Keyed by NEMSIS human-readable label.  Section headers retain the source
# element ID for provenance.  Values are NEMSIS v3.5.1 codes.
# ─────────────────────────────────────────────────────────────────────────────

_GENERAL_CODED: Mapping[str, str] = MappingProxyType(
    {
        # Yes/No/Unknown (9923xxx)
        "Yes": "9923003",
        "No": "9923001",
        "Unknown": "9923007",
        # dAgency.09 — Primary Type of Service
        "911 Response (Scene) with Transport Capability": "9917007",
        "911 Response (Scene) without Transport Capability": "9917005",
        "Air Medical": "9917009",
        "Community Paramedicine/Mobile Integrated Healthcare": "9917027",
        "Critical Care Transport": "9917011",
        "Interfacility Transport": "9917013",
        "Medical Transport (Non-Emergency)": "9917015",
        "Non-Emergency Medical Transport (NEMT)": "9917017",
        "Other": "9917021",
        "Community Paramedicine": "9917023",
        # dAgency.11 — Level of Service
        "ALS": "9917003",
        "ALS - Paramedic": "9917001",
        "ALS - AEMT": "9917007",
        "BLS": "9917005",
        # dAgency.12 — Organization Status
        "Non-Volunteer": "9916007",
        "Mixed (Volunteer and Non-Volunteer)": "9916005",
        "Volunteer": "9916009",
        # dAgency.13 — Organizational Type
        "Governmental, Non-Fire": "9914003",
        "Governmental, Fire-Based": "9914001",
        "Hospital-Based": "9914005",
        "Non-Governmental, Non-Hospital": "9914007",
        "Private": "9914009",
        # dAgency.14 — Tax Status
        "Not-for-Profit": "9915007",
        "For-Profit": "9915001",
        "Government": "9915003",
        "Other (e.g., Government)": "9915005",
        # dAgency.23 — Time Zone
        "GMT-05:00 Eastern Time": "9914017",
        "GMT-06:00 Central Time": "9914019",
        "GMT-07:00 Mountain Time": "9914021",
        "GMT-08:00 Pacific Time": "9914023",
        "GMT-09:00 Alaska Time": "9914025",
        "GMT-10:00 Hawaii-Aleutian Standard Time": "9914027",
        # dAgency.27 — Licensed Agency
        "Licensed": "9915009",
        # dContact.01 — Contact Type
        "EMS Agency Director/Chief/Lead Administrator/CEO": "9908013",
        "EMS Medical Director": "9908017",
        "EMS Quality/Performance Improvement Specialist": "9908021",
        "EMS Billing Contact": "9908003",
        "EMS Training Contact": "9908027",
        # dContact.13 — MD Degree
        "Doctor of Medicine": "9912001",
        "Doctor of Osteopathic Medicine": "9912003",
        "Physician Assistant": "9912005",
        "Nurse Practitioner": "9912007",
        # dContact.15 — Compensation
        "Compensated": "9911001",
        "Non-Compensated/Volunteer": "9911003",
        # dConfiguration.07 / eCrew.02 — EMS Cert Levels (9925xxx)
        "Emergency Medical Responder (EMR)": "9925001",
        "Emergency Medical Technician (EMT)": "9925005",
        "Advanced Emergency Medical Technician (AEMT)": "9925003",
        "Paramedic": "9925007",
        # eCrew.03 — Crew Member Response Role
        "Driver/Pilot-Response": "2403001",
        "Driver/Pilot-Transport": "2403003",
        "Other Patient Caregiver-At Scene": "2403007",
        "Other Patient Caregiver-Transport": "2403009",
        "Primary Patient Caregiver-At Scene": "2403011",
        "Primary Patient Caregiver-Transport": "2403013",
        # eResponse.05 — Type of Service Requested
        "Emergency Response (Primary Response Area)": "2205001",
        "Emergency Response (Intercept)": "2205003",
        "Emergency Response (Mutual Aid)": "2205005",
        "Non-Emergency Transport (Routine)": "2205007",
        "Standby": "2205009",
        # eResponse.07 — Unit Transport/Equipment
        "Ground Transport (ALS Equipped)": "2207015",
        "Ground Transport (BLS Equipped)": "2207017",
        "Ground Transport (Critical Care Equipped)": "2207019",
        "Air Transport-Fixed Wing": "2207001",
        "Air Transport-Rotor Craft": "2207003",
        # eResponse.08 — Type of Dispatch Delay
        "Incomplete Address Information Provided": "2208009",
        "Caller Disconnect before Dispatch": "2208003",
        "High Call Volume": "2208007",
        # eResponse.09 / .10 / .11 / .12 — Delay families (see element-scoped dict)
        "Directions/Unable to Locate": "2209003",
        "Distance": "2209005",
        "Weather": "2209027",
        # eResponse.23 — Response Mode
        "Emergent (Immediate Response)": "2223001",
        "Non-Emergent": "2223003",
        # eResponse.24 — Additional Response Mode Descriptors
        "Initial Lights and Sirens, Downgraded to No Lights or Sirens": "2224023",
        "Lights and Sirens": "2224005",
        "No Lights or Sirens": "2224007",
        "Initial No Lights or Sirens, Upgraded to Lights and Sirens": "2224009",
        # eDispatch.01 — Dispatch Reason
        "Allergic Reaction/Stings": "2301003",
        "Breathing Problem": "2301007",
        "Cardiac Arrest/Death": "2301011",
        "Chest Pain/Discomfort": "2301015",
        "Diabetic Problems": "2301019",
        "Falls": "2301023",
        "Head Injury": "2301031",
        "Heat/Cold Exposure": "2301033",
        "Mental Problems": "2301045",
        "Overdose/Poisoning/Ingestion": "2301049",
        "Psychiatric/Abnormal Behavior/Suicide Attempt": "2301055",
        "Seizures/Convulsions": "2301059",
        "Stroke/CVA": "2301063",
        "Traumatic Injury": "2301067",
        "Unknown Problem/Person Down": "2301069",
        "Unconscious/Fainting/Near-Fainting": "2301071",
        "Asthma/Respiratory Distress": "2301005",
        # eDispatch.05 — Dispatch Priority
        "Emergent": "2305003",
        "Lower Acuity": "2305001",
        # ePatient.14 — Race
        "American Indian or Alaska Native": "2514001",
        "Asian": "2514003",
        "Black or African American": "2514005",
        "Hispanic or Latino": "2514007",
        "Native Hawaiian or Other Pacific Islander": "2514009",
        "White": "2514011",
        "Multiple Races": "2514013",
        # ePatient.16 — Age Units
        "Years": "2516009",
        "Months": "2516007",
        "Days": "2516003",
        "Hours": "2516005",
        "Minutes": "2516001",
        # ePatient.25 — Gender
        "Female": "9919001",
        "Male": "9919003",
        "Unknown (Unable to Determine)": "9919009",
        "Transgender (Female to Male)": "9919007",
        "Transgender (Male to Female)": "9919005",
        "Non-Binary": "9919011",
        # ePayment.01 — Primary Method of Payment
        "Medicare": "2601001",
        "Medicaid": "2601003",
        "Private Insurance": "2601005",
        "Workmen's Compensation": "2601007",
        "VA": "2601009",
        "CHAMPUS": "2601011",
        "Champus": "2601011",
        "Self Pay": "2601013",
        "No Insurance Identified": "2601021",
        "Other Government": "2601015",
        # ePayment.08 — Patient Residence Status
        "Resident Within EMS Service Area": "2608001",
        "Not a Resident Within EMS Service Area": "2608003",
        # ePayment.40 — Patient Transport Assessment
        "Immediate": "2640001",
        "Delayed": "2640003",
        "Minor (Green)": "2640005",
        "Expectant (Black)": "2640007",
        # ePayment.50 — CMS Service Level
        "ALS, Level 1 Emergency": "2650003",
        "ALS, Level 2": "2650005",
        "ALS Assessment": "2650007",
        "BLS Emergency": "2650011",
        "Critical Care Transport (CCT)": "2650013",
        "Specialty Care Transport (SCT)": "2650015",
        "Non-Emergency Ambulance Transport": "2650017",
        # eScene.06 — Number of Patients at Scene
        "None": "2706001",
        "Single": "2707005",
        "Multiple": "2707007",
        # eSituation.03 — Complaint Type
        "Chief (Primary)": "2803001",
        "Secondary (Other)": "2803003",
        # eSituation.06 — Duration Units
        # (Minutes/Hours/Days already mapped above for ePatient.16 — conflict-free
        # within NEMSIS since codes differ only by element scope)
        "Weeks": "2806009",
        # eSituation.07 — Chief Complaint Anatomic Location
        "General/Global": "2807011",
        "Head": "2807013",
        "Arm": "2807001",
        "Chest": "2807007",
        "Abdomen": "2807003",
        "Back": "2807005",
        "Lower Extremity": "2807017",
        "Neck": "2807021",
        # eSituation.08 — Chief Complaint Organ System
        "Global/General": "2808011",
        "Cardiovascular": "2808005",
        "Endocrine/Metabolic": "2808007",
        "Gastrointestinal": "2808009",
        "Musculoskeletal": "2808013",
        "Nervous": "2808015",
        "Pulmonary": "2808017",
        "Skin": "2808019",
        # eSituation.13 — Patient Acuity
        "Critical (Red)": "2813001",
        "Emergent (Orange)": "2813003",
        "Lower Acuity (Green)": "2813005",
        "Non-Acute/Routine": "2813007",
        "Dead without Resuscitation Efforts (Black)": "2813009",
        # eInjury.02 — Mechanism of Injury
        "Blunt": "2902001",
        "Penetrating": "2902007",
        "Burn": "2902003",
        # eInjury.03 — Trauma Triage Step
        "Active bleeding requiring a tourniquet or wound packing with continuous pressure": "2903001",
        "Age >= 10 years: HR > SBP": "2903025",
        "Respiratory distress or need for respiratory support": "2903027",
        "Room-air pulse oximetry < 90%": "2903029",
        # eArrest.01 — Cardiac Arrest
        "Yes, Prior to Any EMS Arrival": "3001003",
        "Yes, After EMS Arrival": "3001005",
        # eHistory.01 — Barriers to Patient Care
        "None Noted": "3101009",
        "Language Barrier": "3101005",
        "Physical Obstruction": "3101011",
        "Uncooperative Patient": "3101013",
        # eHistory.05 — Advance Directives
        "DNR": "3105001",
        "Comfort Measures Only": "3105003",
        # eHistory.09 — Who Obtained History
        "Bystander/Other": "3109001",
        "Family Member": "3109003",
        "Healthcare Provider": "3109005",
        "Patient": "3109007",
        # eHistory.17 — Alcohol Use Indicators
        "Alcohol Containers/Paraphernalia at Scene": "3117001",
        "Bystander/Family Reports Alcohol Use": "3117003",
        # eHistory.18 — Drug Use Indicators
        "Drug Paraphernalia at Scene": "3118003",
        # eVitals.08 — Blood Pressure Method
        "Cuff-Automated": "3308005",
        "Cuff-Manual": "3308003",
        "Doppler": "3308007",
        "Auscultated": "3308001",
        # eVitals.11 — Heart Rate Method
        "Electronic Monitor - Pulse Oximeter": "3311007",
        "Electronic Monitor": "3311001",
        "Palpation": "3311005",
        # eVitals.15 — Respiratory Effort
        "Normal": "3315007",
        "Labored": "3315003",
        "Rapid": "3315009",
        "Shallow": "3315011",
        "Absent": "3315001",
        # eVitals.22 — GCS Score Qualifier
        "Initial GCS has legitimate values without interventions such as intubation and sedation": "3322003",
        "GCS is likely altered due to patient's clinical condition rather than severity of injury": "3322001",
        # eVitals.25 — Temperature Method
        "Tympanic": "3325013",
        "Axillary": "3325001",
        "Oral": "3325009",
        "Rectal": "3325011",
        "Temporal": "3325015",
        # eVitals.26 — AVPU
        "Alert": "3326001",
        "Verbal": "3326003",
        "Pain": "3326005",
        "Unresponsive": "3326007",
        # eExam select
        "Cyanotic": "3504001",
        "Flushed": "3504005",
        "Swelling": "3506053",
        "Generalized": "3510001",
        "Not Done": "3514029",
        "Bilateral": "3517001",
        "PERRL": "3518047",
        "Increased Respiratory Effort": "3523011",
        # eExam.15 — Extremity Assessment Location
        "Arm-Lower-Right": "3515015",
        "Arm-Upper-Right": "3515019",
        "Arm-Whole Arm and Hand-Left": "3515097",
        "Arm-Whole Arm and Hand-Right": "3515099",
        "Leg-Lower-Right": "3515059",
        "Leg-Upper-Right": "3515063",
        # eExam.24 — Back Location
        "General - Anterior": "3524009",
        "General - Posterior": "3524011",
        "General - Anterior/Posterior": "3524007",
        # eExam.13 — Spine Location
        "Back-General": "3513001",
        "Cervical": "3513003",
        "Thoracic": "3513007",
        "Lumbar": "3513005",
        # eProtocols.01
        "Medical-Allergic Reaction/Anaphylaxis": "9914111",
        "Medical-Behavioral/Psychiatric Disorder": "9914113",
        "Medical-Breathing Problem": "9914115",
        "Medical-Cardiac Arrest/Death": "9914117",
        "Medical-Chest Pain": "9914121",
        "Medical-Diabetic Problems": "9914131",
        "Medical-Seizure": "9914191",
        "Medical-Stroke/CVA": "9914197",
        "Trauma-Burn Injury": "9914201",
        "Trauma-Extremity Injury": "9914203",
        "Trauma-Head Injury": "9914207",
        "Trauma-Multiple Trauma": "9914211",
        "Trauma-Pediatric Trauma": "9914213",
        "Medical-Pediatric-Asthma": "9914165",
        "Medical-Asthma": "9914165",
        "General": "9914101",
        # eMedications.04 — Medication Administered Route
        "Auto Injector": "9927063",
        "Endotracheal Tube (ET)": "9927019",
        "Inhalation": "9927025",
        "Intraosseous (IO)": "9927029",
        "Intravenous (IV)": "9927031",
        "Intramuscular (IM)": "9927027",
        "Nasal": "9927037",
        "Non-Rebreather Mask": "9927039",
        "Subcutaneous (SQ)": "9927061",
        "Sublingual (SL)": "9927065",
        "Topical": "9927071",
        # eMedications.06 — Medication Dosage Units
        "Milligrams (mg)": "3706021",
        "Micrograms (mcg)": "3706015",
        "Grams (g)": "3706011",
        "Milliliters (mL)": "3706023",
        "Liters (L)": "3706019",
        "Liters Per Minute (LPM [gas])": "3706025",
        "Milliequivalents (mEq)": "3706017",
        "International Units (IU)": "3706013",
        "Units": "3706029",
        # eMedications.07 / eProcedures.08 — Patient Condition
        "Improved": "9916001",
        "Unchanged": "9916003",
        "Worse": "9916005",
        "Deceased": "9916007",
        # eMedications.08 — Medication Complication
        "Allergic Reaction": "3708001",
        "Hypotension": "3708009",
        # eMedications.10 / eProcedures.10 — Personnel Level (9905xxx)
        # Note: these overload the 9925xxx Cert Level labels.  Callers must
        # scope via element_id.
        # eMedications.11 / eProcedures.11 — Authorization Type
        "Protocol (Standing Order)": "9918005",
        "On-Line (Remote Verbal Order)": "9918003",
        "Off-Line (Offline Medical Direction/Protocol)": "9918001",
        # eProcedures.07 — Procedure Complications
        "Failed Procedure": "3907017",
        # eProcedures.13 — Extremity Assessment Location
        "Forearm-Left": "3913017",
        "Forearm-Right": "3913019",
        "Arm-Lower-Left": "3913013",
        # eAirway.01 — Reason for Airway Management
        "Adequate Airway Reflexes/Effort, Potential for Compromise": "4001001",
        "Airway-Failed": "4001003",
        "Airway-Obstruction/Foreign Body": "4001005",
        "Airway-Rapid Sequence Induction (RSI-Paralytic)": "4001007",
        "Airway-Sedation Assisted (Non-Paralytic)": "4001009",
        # eAirway.03 — Method of Airway Management
        "BVM": "4003001",
        "Endotracheal Intubation-Oral (ET)": "4003003",
        "Other-Invasive Airway": "4003005",
        "Supraglottic Airway": "4003007",
        "Nasal Airway (NPA)": "4003009",
        "Oral Airway (OPA)": "4003011",
        # eAirway.04 — Airway Device Placement Confirmed
        "Condensation in Tube": "4004007",
        "Endotracheal Tube Whistle (BAAM, etc.)": "4004005",
        "Waveform Capnography": "4004015",
        "Colorimetric ETCO2": "4004003",
        "Directly Visualized": "4004001",
        # eAirway.06 — Person Performing
        "Person Performing Intubation": "4006005",
        "Assisted in Intubation": "4006001",
        "Supervised Intubation": "4006003",
        # eAirway.09 — Airway Complications
        "Difficult Patient Airway Anatomy": "4009001",
        "Inability to Expose Vocal Cords": "4009003",
        "Medication Side Effect": "4009005",
        # eDisposition.13 / .15 — Transport Method
        "Assisted/Walk": "9909001",
        "Ambulatory": "9909003",
        "Carried": "9909005",
        "Stretcher": "9909007",
        "Wheelchair": "9909009",
        # eDisposition.14 — Position of Patient During Transport
        "Semi-Fowlers": "4214013",
        "Supine": "4214015",
        "Fowlers": "4214005",
        "Prone": "4214011",
        "Trendelenburg": "4214017",
        # eDisposition.16 — Type of Destination
        "Ground-Ambulance": "4216005",
        "Air-Rotor": "4216001",
        "Air-Fixed": "4216003",
        # eDisposition.17 — Hospital Capability
        "Non-Emergency": "4217003",
        # eDisposition.18 — Additional Transport Mode Descriptors
        "Speed-Enhanced per Local Policy": "4218007",
        "Lights and No Sirens": "4218005",
        # eDisposition.19 — Final Patient Acuity
        "Emergent (Yellow)": "4219003",
        "Non-Acute (Green)": "4219005",
        # eDisposition.20 — Reason for Choosing Destination
        "Protocol": "4220019",
        "Patient Request": "4220017",
        "On-Line Medical Direction": "4220015",
        "Closest Facility": "4220005",
        # eDisposition.21 — Type of Destination
        "Hospital-Emergency Department": "4221003",
        "Freestanding Emergency Department": "4221001",
        "Scene": "4221009",
        # eDisposition.27 — Unit Disposition
        "Patient Contact Made": "4227001",
        "No Patient Contact": "4227003",
        "Cancelled (Prior to Arrival at Scene)": "4227005",
        # eDisposition.28 — Patient Evaluation/Care
        "Patient Evaluated and Care Provided": "4228001",
        "Patient Evaluated, No Care Required": "4228003",
        "Patient Refused Evaluation/Care": "4228005",
        # eDisposition.29 — Crew Disposition
        "Initiated and Continued Primary Care": "4229001",
        "Transferred Care": "4229003",
        "Provided Assistance Only": "4229005",
        # eDisposition.30 — Transport Disposition
        "Transport by This EMS Unit (This Crew Only)": "4230001",
        "Transport by This EMS Unit, with a Member of Another Crew": "4230003",
        "Non-EMS Transport": "4230005",
        # eDisposition.32 — Crew Type
        # (Uses 4232xxx; overloads labels with 9917/9925 — callers scope via element_id)
        # eOutcome.03 — Hospital Transfer
        "Hospital-Receiving": "4303005",
    }
)


# ─────────────────────────────────────────────────────────────────────────────
# CodedValueSet
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CodedValueSet:
    """Immutable, versioned NEMSIS coded-value set.

    Each lookup method returns the canonical NEMSIS code for a human-readable
    label or raises :class:`UnknownCodedValueError`.  No method falls back to
    the input on miss — the caller must handle every ``UnknownCodedValueError``
    explicitly.
    """

    version: str
    source_url: str
    states: Mapping[str, str]
    countries: Mapping[str, str]
    counties: Mapping[str, str]
    cities: Mapping[str, str]
    nv_codes: Mapping[str, str]
    pn_codes: Mapping[str, str]
    phone_types: Mapping[str, str]
    email_types: Mapping[str, str]
    etco2_units: Mapping[str, str]
    distance_units: Mapping[str, str]
    general: Mapping[str, str]
    element_specific: Mapping[str, Mapping[str, str]]

    def state(self, label: str) -> str:
        """Return the FIPS state code for a U.S. state name.

        Args:
            label: Full state name, e.g. ``"Florida"``.

        Returns:
            Two-digit FIPS code, e.g. ``"12"``.

        Raises:
            UnknownCodedValueError: If ``label`` is not a known state.
        """

        try:
            return self.states[label]
        except KeyError as exc:
            raise UnknownCodedValueError("state", label) from exc

    def country(self, label: str) -> str:
        """Return the ISO 3166-1 alpha-2 country code.

        Args:
            label: Country name, e.g. ``"United States"``.

        Returns:
            Two-letter ISO country code.

        Raises:
            UnknownCodedValueError: If ``label`` is not a known country.
        """

        try:
            return self.countries[label]
        except KeyError as exc:
            raise UnknownCodedValueError("country", label) from exc

    def county(self, label: str) -> str:
        """Return the 5-digit FIPS county code.

        Args:
            label: County name, e.g. ``"Okaloosa County"``.

        Returns:
            Five-digit FIPS code, e.g. ``"12091"``.

        Raises:
            UnknownCodedValueError: If ``label`` is not mapped.
        """

        try:
            return self.counties[label]
        except KeyError as exc:
            raise UnknownCodedValueError("county", label) from exc

    def city(self, label: str) -> str:
        """Return the FIPS city / CDP code.

        Args:
            label: City or census-designated-place name.

        Returns:
            FIPS place code.

        Raises:
            UnknownCodedValueError: If ``label`` is not mapped.
        """

        try:
            return self.cities[label]
        except KeyError as exc:
            raise UnknownCodedValueError("city", label) from exc

    def nv(self, label: str) -> str:
        """Return the NEMSIS NV (Not-Value) code.

        Args:
            label: NV descriptor, e.g. ``"Not Applicable"``.

        Returns:
            7- or 8-digit NEMSIS code.

        Raises:
            UnknownCodedValueError: If ``label`` is not mapped.
        """

        try:
            return self.nv_codes[label]
        except KeyError as exc:
            raise UnknownCodedValueError("nv", label) from exc

    def pn(self, label: str) -> str:
        """Return the NEMSIS PN (Pertinent Negative) code.

        Args:
            label: PN descriptor.

        Returns:
            8-digit NEMSIS code.

        Raises:
            UnknownCodedValueError: If ``label`` is not mapped.
        """

        try:
            return self.pn_codes[label]
        except KeyError as exc:
            raise UnknownCodedValueError("pn", label) from exc

    def phone_type(self, label: str) -> str:
        """Return the NEMSIS phone-type code.

        Args:
            label: Phone-type descriptor, e.g. ``"Mobile"``.

        Returns:
            7-digit NEMSIS code.

        Raises:
            UnknownCodedValueError: If ``label`` is not mapped.
        """

        try:
            return self.phone_types[label]
        except KeyError as exc:
            raise UnknownCodedValueError("phone_type", label) from exc

    def email_type(self, label: str) -> str:
        """Return the NEMSIS email-type code.

        Args:
            label: Email-type descriptor, e.g. ``"Work"``.

        Returns:
            7-digit NEMSIS code.

        Raises:
            UnknownCodedValueError: If ``label`` is not mapped.
        """

        try:
            return self.email_types[label]
        except KeyError as exc:
            raise UnknownCodedValueError("email_type", label) from exc

    def etco2_unit(self, label: str) -> str:
        """Return the NEMSIS ETCO2 unit code.

        Args:
            label: Unit descriptor, e.g. ``"mmHg"``.

        Returns:
            7-digit NEMSIS code.

        Raises:
            UnknownCodedValueError: If ``label`` is not mapped.
        """

        try:
            return self.etco2_units[label]
        except KeyError as exc:
            raise UnknownCodedValueError("etco2_unit", label) from exc

    def distance_unit(self, label: str) -> str:
        """Return the NEMSIS distance-unit code.

        Args:
            label: Unit descriptor, e.g. ``"Miles"``.

        Returns:
            7-digit NEMSIS code.

        Raises:
            UnknownCodedValueError: If ``label`` is not mapped.
        """

        try:
            return self.distance_units[label]
        except KeyError as exc:
            raise UnknownCodedValueError("distance_unit", label) from exc

    def general_code(self, label: str) -> str:
        """Return the NEMSIS code for a general coded-value label.

        Args:
            label: Human-readable label from the HTML test case.

        Returns:
            NEMSIS code.

        Raises:
            UnknownCodedValueError: If ``label`` is not mapped.
        """

        try:
            return self.general[label]
        except KeyError as exc:
            raise UnknownCodedValueError("general", label) from exc

    def has_general(self, label: str) -> bool:
        """Check whether a label is mapped in the general coded-value table.

        Args:
            label: Human-readable label.

        Returns:
            ``True`` if mapped, ``False`` otherwise.  This method does **not**
            raise — it is the only non-raising helper and is provided for
            callers that need to compose conditional logic.
        """

        return label in self.general

    def has_element_specific(self, element_id: str) -> bool:
        """Check whether an element-specific lookup table exists for ``element_id``.

        Args:
            element_id: NEMSIS element identifier, e.g. ``"dAgency.09"``.

        Returns:
            ``True`` if an element-specific table is registered for this
            element, ``False`` otherwise.  Does not raise.
        """

        return element_id in self.element_specific

    def element_specific_code(self, element_id: str, label: str) -> str:
        """Return the NEMSIS code for ``label`` using the element-specific table.

        Args:
            element_id: NEMSIS element identifier, e.g. ``"dAgency.09"``.
            label: Human-readable label extracted from the HTML cell.

        Returns:
            Canonical NEMSIS code from the XSD-validated enumeration table.

        Raises:
            UnknownCodedValueError: If ``element_id`` has no registered table
                or ``label`` is not present in that table.
        """

        table = self.element_specific.get(element_id)
        if table is None:
            raise UnknownCodedValueError(f"element_specific[{element_id}]", label)
        try:
            return table[label]
        except KeyError as exc:
            raise UnknownCodedValueError(
                f"element_specific[{element_id}]", label
            ) from exc


# ─────────────────────────────────────────────────────────────────────────────
# Canonical 3.5.1 instance
# ─────────────────────────────────────────────────────────────────────────────

NEMSIS_V351_CODED_VALUES: CodedValueSet = CodedValueSet(
    version="3.5.1.251001CP2",
    source_url="https://nemsis.org/media/nemsis_v3/3.5.1.251001CP2/",
    states=_FIPS_STATES,
    countries=_ISO_COUNTRIES,
    counties=_FIPS_COUNTIES,
    cities=_FIPS_CITIES,
    nv_codes=_NV_CODES,
    pn_codes=_PN_CODES,
    phone_types=_PHONE_TYPES,
    email_types=_EMAIL_TYPES,
    etco2_units=_ETCO2_UNITS,
    distance_units=_DISTANCE_UNITS,
    general=_GENERAL_CODED,
    element_specific=_ELEMENT_SPECIFIC_FULL,
)
