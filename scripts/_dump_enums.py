import json
from pathlib import Path
d = json.load(open('artifact/generated/2025/.xsd_enums.json', encoding='utf-8'))
st = d['simple_types']
types = [
    'TypeOfService', 'StateCertificationLicensureLevels', 'OrganizationStatus',
    'OrganizationalType', 'AgencyOrganizationalTaxStatus', 'AgencyContactType',
    'AgencyMedicalDirectorBoardCertificationType', 'ProtocolsUsed', 'VehicleType',
    'PersonnelHighestEducationalDegree', 'PersonnelDegreeFieldofStudy',
    'PhoneNumberType', 'NV', 'PN', 'ANSIStateCode',
]
out = {t: st.get(t, {}) for t in types}
Path('artifact/generated/2025/.critical_enums.json').write_text(
    json.dumps(out, indent=2, ensure_ascii=True), encoding='utf-8'
)
print("wrote critical enums")
for t in types:
    print(f"--- {t} ({len(out[t])} entries) ---")
    for code, label in list(out[t].items())[:30]:
        print(f"  {code} = {label}")
    if len(out[t]) > 30:
        print(f"  ... and {len(out[t]) - 30} more")
