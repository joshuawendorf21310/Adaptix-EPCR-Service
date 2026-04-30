import sqlite3
c = sqlite3.connect(r'backend/.local/cta_portal/epcr-local.db')
cid = '0deda819-ea1e-5524-9920-1c5c49cebfbb'
print("chart row:", c.execute("select id, tenant_id, call_number, status, incident_type from epcr_charts where id=?", (cid,)).fetchone())
print("patient_profile:", c.execute("select count(*) from epcr_patient_profiles where chart_id=?", (cid,)).fetchone()[0])
print("chart_address:", c.execute("select count(*) from epcr_chart_addresses where chart_id=?", (cid,)).fetchone()[0])
print("assessment:", c.execute("select count(*) from epcr_assessments where chart_id=?", (cid,)).fetchone()[0])
print("vitals:", c.execute("select count(*) from epcr_vitals where chart_id=?", (cid,)).fetchone()[0])
print("interventions:", c.execute("select count(*) from epcr_interventions where chart_id=?", (cid,)).fetchone()[0])
print("medications:", c.execute("select count(*) from epcr_medication_administrations where chart_id=?", (cid,)).fetchone()[0])
print("signatures:", c.execute("select count(*) from epcr_signature_artifacts where chart_id=?", (cid,)).fetchone()[0])
print("compliance:", c.execute("select count(*) from epcr_nemsis_compliance where chart_id=?", (cid,)).fetchone()[0])
print()
print("compliance row:", c.execute("select compliance_status, mandatory_fields_filled, mandatory_fields_required from epcr_nemsis_compliance where chart_id=?", (cid,)).fetchone())
