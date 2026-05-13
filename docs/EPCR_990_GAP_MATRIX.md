# Adaptix ePCR — 990-Feature Gap Matrix
Generated: 2026-05-12  ·  Owner: ePCR platform

## Legend
Status: Built | Partial | Missing | OUT OF SCOPE (TAC/CTA)
Phase: P1 (experiential shell now) | P2 (backend pillar) | P3 (polish)

## Group A — Core Chart Foundation (Features 1–125)
| # | Feature | Status | Existing path | Required service | Phase |
| --- | --- | --- | --- | --- | --- |
| 1 | Chart ID (UUID primary key) | Built | backend/models/chart.py | — | — |
| 2 | Chart create endpoint | Built | backend/api/charts.py | — | — |
| 3 | Chart get-by-id endpoint | Built | backend/api/charts.py | — | — |
| 4 | Chart list endpoint | Built | backend/api/charts.py | — | — |
| 5 | Chart soft-delete | Built | backend/models/chart.py | — | — |
| 6 | Chart status enum (draft/locked/exported) | Built | backend/models/chart.py | — | — |
| 7 | Chart created_at timestamp | Built | backend/models/chart.py | — | — |
| 8 | Chart updated_at timestamp | Built | backend/models/chart.py | — | — |
| 9 | Chart agency_id FK | Built | backend/models/chart.py | — | — |
| 10 | Chart unit_id FK | Built | backend/models/chart.py | — | — |
| 11 | Chart incident_number | Built | backend/models/chart.py | — | — |
| 12 | Chart CAD reference linkage | Partial | backend/integrations/cad.py | CAD bridge | P2 |
| 13 | Chart dispatch timestamp | Built | backend/models/chart.py | — | — |
| 14 | Chart enroute timestamp | Built | backend/models/chart.py | — | — |
| 15 | Chart on-scene timestamp | Built | backend/models/chart.py | — | — |
| 16 | Chart at-patient timestamp | Built | backend/models/chart.py | — | — |
| 17 | Chart depart-scene timestamp | Built | backend/models/chart.py | — | — |
| 18 | Chart at-destination timestamp | Built | backend/models/chart.py | — | — |
| 19 | Chart transfer-of-care timestamp | Built | backend/models/chart.py | — | — |
| 20 | Chart in-service timestamp | Built | backend/models/chart.py | — | — |
| 21 | Patient demographics block | Built | backend/models/patient.py | — | — |
| 22 | Patient first name | Built | backend/models/patient.py | — | — |
| 23 | Patient last name | Built | backend/models/patient.py | — | — |
| 24 | Patient middle name | Built | backend/models/patient.py | — | — |
| 25 | Patient DOB | Built | backend/models/patient.py | — | — |
| 26 | Patient age (computed) | Built | backend/models/patient.py | — | — |
| 27 | Patient gender | Built | backend/models/patient.py | — | — |
| 28 | Patient race | Built | backend/models/patient.py | — | — |
| 29 | Patient ethnicity | Built | backend/models/patient.py | — | — |
| 30 | Patient SSN (encrypted) | Built | backend/models/patient.py | — | — |
| 31 | Patient phone | Built | backend/models/patient.py | — | — |
| 32 | Patient email | Built | backend/models/patient.py | — | — |
| 33 | Patient address line 1 | Built | backend/models/patient.py | — | — |
| 34 | Patient address line 2 | Built | backend/models/patient.py | — | — |
| 35 | Patient city | Built | backend/models/patient.py | — | — |
| 36 | Patient state | Built | backend/models/patient.py | — | — |
| 37 | Patient zip | Built | backend/models/patient.py | — | — |
| 38 | Patient county | Built | backend/models/patient.py | — | — |
| 39 | Patient country | Built | backend/models/patient.py | — | — |
| 40 | Patient weight (kg) | Built | backend/models/patient.py | — | — |
| 41 | Patient weight (lbs derived) | Built | backend/models/patient.py | — | — |
| 42 | Patient height | Built | backend/models/patient.py | — | — |
| 43 | Patient BMI computed | Partial | backend/models/patient.py | — | P3 |
| 44 | Patient primary language | Built | backend/models/patient.py | — | — |
| 45 | Patient interpreter needed flag | Built | backend/models/patient.py | — | — |
| 46 | Patient marital status | Built | backend/models/patient.py | — | — |
| 47 | Patient occupation | Built | backend/models/patient.py | — | — |
| 48 | Patient employer | Built | backend/models/patient.py | — | — |
| 49 | Patient emergency contact name | Built | backend/models/patient.py | — | — |
| 50 | Patient emergency contact phone | Built | backend/models/patient.py | — | — |
| 51 | Patient emergency contact relationship | Built | backend/models/patient.py | — | — |
| 52 | Patient insurance primary | Built | backend/models/insurance.py | — | — |
| 53 | Patient insurance secondary | Built | backend/models/insurance.py | — | — |
| 54 | Patient insurance tertiary | Built | backend/models/insurance.py | — | — |
| 55 | Insurance policy number | Built | backend/models/insurance.py | — | — |
| 56 | Insurance group number | Built | backend/models/insurance.py | — | — |
| 57 | Insurance subscriber name | Built | backend/models/insurance.py | — | — |
| 58 | Insurance subscriber DOB | Built | backend/models/insurance.py | — | — |
| 59 | Insurance subscriber relationship | Built | backend/models/insurance.py | — | — |
| 60 | Insurance payer ID | Built | backend/models/insurance.py | — | — |
| 61 | Insurance authorization number | Partial | backend/models/insurance.py | Billing bridge | P3 |
| 62 | Insurance card image upload | Missing | — | DocumentService | P3 |
| 63 | Crew member roster | Built | backend/models/crew.py | — | — |
| 64 | Crew primary caregiver | Built | backend/models/crew.py | — | — |
| 65 | Crew driver | Built | backend/models/crew.py | — | — |
| 66 | Crew additional members | Built | backend/models/crew.py | — | — |
| 67 | Crew certification level per member | Built | backend/models/crew.py | — | — |
| 68 | Crew on-scene arrival time per member | Partial | backend/models/crew.py | — | P3 |
| 69 | Service level provided | Built | backend/models/chart.py | — | — |
| 70 | Response mode (emergent/non-emergent) | Built | backend/models/chart.py | — | — |
| 71 | Transport mode | Built | backend/models/chart.py | — | — |
| 72 | Transport destination | Built | backend/models/chart.py | — | — |
| 73 | Transport destination type | Built | backend/models/chart.py | — | — |
| 74 | Transport destination address | Built | backend/models/chart.py | — | — |
| 75 | Transport destination contact | Built | backend/models/chart.py | — | — |
| 76 | Transport reason | Built | backend/models/chart.py | — | — |
| 77 | Transport decision authority | Built | backend/models/chart.py | — | — |
| 78 | Mileage loaded | Built | backend/models/chart.py | — | — |
| 79 | Mileage unloaded | Built | backend/models/chart.py | — | — |
| 80 | Mileage start odometer | Built | backend/models/chart.py | — | — |
| 81 | Mileage end odometer | Built | backend/models/chart.py | — | — |
| 82 | Scene address | Built | backend/models/scene.py | — | — |
| 83 | Scene GPS coordinates | Built | backend/models/scene.py | — | — |
| 84 | Scene type | Built | backend/models/scene.py | — | — |
| 85 | Scene hazards | Built | backend/models/scene.py | — | — |
| 86 | Scene patient count | Built | backend/models/scene.py | — | — |
| 87 | Mass casualty flag | Built | backend/models/scene.py | — | — |
| 88 | Triage category | Partial | backend/models/scene.py | MultiPatientService | P2 |
| 89 | Mutual aid flag | Built | backend/models/scene.py | — | — |
| 90 | Other agencies on scene | Built | backend/models/scene.py | — | — |
| 91 | Law enforcement notified | Built | backend/models/scene.py | — | — |
| 92 | Medical control contacted | Built | backend/models/scene.py | — | — |
| 93 | Medical control physician name | Built | backend/models/scene.py | — | — |
| 94 | Medical control time | Built | backend/models/scene.py | — | — |
| 95 | Medical control orders | Built | backend/models/scene.py | — | — |
| 96 | Chart narrative free-text | Built | backend/models/chart.py | — | — |
| 97 | Chart narrative templated sections | Partial | backend/models/chart.py | SmartTextService | P2 |
| 98 | Chart attachments list | Built | backend/models/attachment.py | — | — |
| 99 | Chart attachment upload | Built | backend/api/attachments.py | — | — |
| 100 | Chart attachment download | Built | backend/api/attachments.py | — | — |
| 101 | Chart signature — primary caregiver | Built | backend/models/signature.py | — | — |
| 102 | Chart signature — receiving facility | Built | backend/models/signature.py | — | — |
| 103 | Chart signature — patient/guardian | Built | backend/models/signature.py | — | — |
| 104 | Chart signature — refusal witness | Built | backend/models/signature.py | — | — |
| 105 | Chart lock action | Partial | backend/api/charts.py | LockReadinessService | P2 |
| 106 | Chart lock readiness check | Missing | — | LockReadinessService | P2 |
| 107 | Chart lock NEMSIS pre-validation | Missing | — | LockReadinessService | P2 |
| 108 | Chart lock signature presence check | Missing | — | LockReadinessService | P2 |
| 109 | Chart unlock with audit | Partial | backend/api/charts.py | AuditTrail | P2 |
| 110 | Chart amendment workflow | Missing | — | AuditTrail | P2 |
| 111 | Chart addendum support | Missing | — | AuditTrail | P2 |
| 112 | Chart version history | Partial | backend/models/chart_version.py | AuditTrail | P2 |
| 113 | Chart diff viewer | Missing | — | AuditTrail | P3 |
| 114 | Chart export NEMSIS XML | Built | backend/exports/nemsis.py | — | — |
| 115 | Chart export PDF | Built | backend/exports/pdf.py | — | — |
| 116 | Chart export to billing | Built | backend/integrations/billing.py | — | — |
| 117 | Chart export to state repository | Partial | backend/exports/state.py | — | P3 |
| 118 | Chart provider override gate | Missing | — | ProviderOverride | P2 |
| 119 | Chart QA review queue | Partial | backend/api/qa.py | — | P3 |
| 120 | Chart QA feedback comments | Built | backend/models/qa_comment.py | — | — |
| 121 | Chart return-to-author workflow | Partial | backend/api/qa.py | — | P3 |
| 122 | Chart offline draft persistence | Built | frontend offline cache | — | — |
| 123 | Chart conflict resolution on sync | Partial | backend/api/sync.py | — | P3 |
| 124 | Chart auto-save interval | Built | frontend auto-save | — | — |
| 125 | Chart timeout warning | Built | frontend session | — | — |

## Group B — Clinical Charting (Features 126–300)
| # | Feature | Status | Existing path | Required service | Phase |
| --- | --- | --- | --- | --- | --- |
| 126 | Chief complaint primary | Built | backend/models/clinical.py | — | — |
| 127 | Chief complaint duration | Built | backend/models/clinical.py | — | — |
| 128 | Chief complaint onset | Built | backend/models/clinical.py | — | — |
| 129 | Chief complaint provoking factors | Built | backend/models/clinical.py | — | — |
| 130 | Chief complaint quality | Built | backend/models/clinical.py | — | — |
| 131 | Chief complaint radiation | Built | backend/models/clinical.py | — | — |
| 132 | Chief complaint severity (1-10) | Built | backend/models/clinical.py | — | — |
| 133 | Chief complaint time pattern | Built | backend/models/clinical.py | — | — |
| 134 | OPQRST framework | Built | backend/models/clinical.py | — | — |
| 135 | SAMPLE history — Signs | Built | backend/models/clinical.py | — | — |
| 136 | SAMPLE history — Allergies | Built | backend/models/clinical.py | — | — |
| 137 | SAMPLE history — Medications | Built | backend/models/clinical.py | — | — |
| 138 | SAMPLE history — Past medical | Built | backend/models/clinical.py | — | — |
| 139 | SAMPLE history — Last oral intake | Built | backend/models/clinical.py | — | — |
| 140 | SAMPLE history — Events leading | Built | backend/models/clinical.py | — | — |
| 141 | Vital signs set: time | Built | backend/models/vitals.py | — | — |
| 142 | Vital signs set: BP systolic | Built | backend/models/vitals.py | — | — |
| 143 | Vital signs set: BP diastolic | Built | backend/models/vitals.py | — | — |
| 144 | Vital signs set: BP method | Built | backend/models/vitals.py | — | — |
| 145 | Vital signs set: pulse rate | Built | backend/models/vitals.py | — | — |
| 146 | Vital signs set: pulse rhythm | Built | backend/models/vitals.py | — | — |
| 147 | Vital signs set: pulse quality | Built | backend/models/vitals.py | — | — |
| 148 | Vital signs set: respiratory rate | Built | backend/models/vitals.py | — | — |
| 149 | Vital signs set: respiratory effort | Built | backend/models/vitals.py | — | — |
| 150 | Vital signs set: SpO2 | Built | backend/models/vitals.py | — | — |
| 151 | Vital signs set: SpO2 on room air vs O2 | Built | backend/models/vitals.py | — | — |
| 152 | Vital signs set: EtCO2 | Built | backend/models/vitals.py | — | — |
| 153 | Vital signs set: temperature | Built | backend/models/vitals.py | — | — |
| 154 | Vital signs set: temperature method | Built | backend/models/vitals.py | — | — |
| 155 | Vital signs set: blood glucose | Built | backend/models/vitals.py | — | — |
| 156 | Vital signs set: GCS eye | Built | backend/models/vitals.py | — | — |
| 157 | Vital signs set: GCS verbal | Built | backend/models/vitals.py | — | — |
| 158 | Vital signs set: GCS motor | Built | backend/models/vitals.py | — | — |
| 159 | Vital signs set: GCS total computed | Built | backend/models/vitals.py | — | — |
| 160 | Vital signs set: pain scale | Built | backend/models/vitals.py | — | — |
| 161 | Vital signs set: skin color | Built | backend/models/vitals.py | — | — |
| 162 | Vital signs set: skin temperature | Built | backend/models/vitals.py | — | — |
| 163 | Vital signs set: skin moisture | Built | backend/models/vitals.py | — | — |
| 164 | Vital signs set: pupil left | Built | backend/models/vitals.py | — | — |
| 165 | Vital signs set: pupil right | Built | backend/models/vitals.py | — | — |
| 166 | Vital signs set: pupil reactivity | Built | backend/models/vitals.py | — | — |
| 167 | Vital signs trend chart | Partial | frontend vitals strip | — | P3 |
| 168 | Vital signs flagged abnormal | Partial | backend/models/vitals.py | — | P3 |
| 169 | Vital signs auto-import from monitor | Missing | — | DeviceBridge | P3 |
| 170 | Stroke scale — Cincinnati | Built | backend/models/assessments.py | — | — |
| 171 | Stroke scale — LAMS | Built | backend/models/assessments.py | — | — |
| 172 | Stroke scale — RACE | Built | backend/models/assessments.py | — | — |
| 173 | Stroke last-known-well time | Built | backend/models/assessments.py | — | — |
| 174 | STEMI 12-lead acquired flag | Built | backend/models/assessments.py | — | — |
| 175 | STEMI activation flag (provider-initiated) | Built | backend/models/assessments.py | — | — |
| 176 | Trauma criteria — physiologic | Built | backend/models/assessments.py | — | — |
| 177 | Trauma criteria — anatomic | Built | backend/models/assessments.py | — | — |
| 178 | Trauma criteria — mechanism | Built | backend/models/assessments.py | — | — |
| 179 | Trauma criteria — special considerations | Built | backend/models/assessments.py | — | — |
| 180 | Trauma triage decision | Built | backend/models/assessments.py | — | — |
| 181 | Sepsis screening criteria | Built | backend/models/assessments.py | — | — |
| 182 | Sepsis qSOFA | Built | backend/models/assessments.py | — | — |
| 183 | Cardiac arrest flag | Built | backend/models/assessments.py | — | — |
| 184 | Cardiac arrest witnessed | Built | backend/models/assessments.py | — | — |
| 185 | Cardiac arrest bystander CPR | Built | backend/models/assessments.py | — | — |
| 186 | Cardiac arrest initial rhythm | Built | backend/models/assessments.py | — | — |
| 187 | Cardiac arrest ROSC | Built | backend/models/assessments.py | — | — |
| 188 | Cardiac arrest termination decision | Built | backend/models/assessments.py | — | — |
| 189 | Airway management — patent | Built | backend/models/airway.py | — | — |
| 190 | Airway — basic maneuvers | Built | backend/models/airway.py | — | — |
| 191 | Airway — OPA | Built | backend/models/airway.py | — | — |
| 192 | Airway — NPA | Built | backend/models/airway.py | — | — |
| 193 | Airway — supraglottic device | Built | backend/models/airway.py | — | — |
| 194 | Airway — ET intubation | Built | backend/models/airway.py | — | — |
| 195 | Airway — ETT size | Built | backend/models/airway.py | — | — |
| 196 | Airway — ETT depth | Built | backend/models/airway.py | — | — |
| 197 | Airway — confirmation method | Built | backend/models/airway.py | — | — |
| 198 | Airway — number of attempts | Built | backend/models/airway.py | — | — |
| 199 | Airway — difficulty rating | Built | backend/models/airway.py | — | — |
| 200 | Airway — RSI medications | Built | backend/models/airway.py | — | — |
| 201 | Airway — surgical cric | Built | backend/models/airway.py | — | — |
| 202 | Breathing — bag-valve mask | Built | backend/models/airway.py | — | — |
| 203 | Breathing — CPAP | Built | backend/models/airway.py | — | — |
| 204 | Breathing — BiPAP | Built | backend/models/airway.py | — | — |
| 205 | Breathing — ventilator settings | Built | backend/models/airway.py | — | — |
| 206 | Breathing — supplemental O2 device | Built | backend/models/airway.py | — | — |
| 207 | Breathing — O2 flow rate | Built | backend/models/airway.py | — | — |
| 208 | Circulation — IV access | Built | backend/models/access.py | — | — |
| 209 | Circulation — IV site | Built | backend/models/access.py | — | — |
| 210 | Circulation — IV gauge | Built | backend/models/access.py | — | — |
| 211 | Circulation — IV attempts | Built | backend/models/access.py | — | — |
| 212 | Circulation — IO access | Built | backend/models/access.py | — | — |
| 213 | Circulation — IO site | Built | backend/models/access.py | — | — |
| 214 | Circulation — fluids infused | Built | backend/models/access.py | — | — |
| 215 | Circulation — fluid type | Built | backend/models/access.py | — | — |
| 216 | Circulation — fluid volume | Built | backend/models/access.py | — | — |
| 217 | Circulation — blood product administration | Built | backend/models/access.py | — | — |
| 218 | Circulation — tourniquet | Built | backend/models/access.py | — | — |
| 219 | Circulation — pressure dressing | Built | backend/models/access.py | — | — |
| 220 | Physical assessment — head | Built | frontend/3DPhysicalAssessment | — | — |
| 221 | Physical assessment — face | Built | frontend/3DPhysicalAssessment | — | — |
| 222 | Physical assessment — neck | Built | frontend/3DPhysicalAssessment | — | — |
| 223 | Physical assessment — chest left | Built | frontend/3DPhysicalAssessment | — | — |
| 224 | Physical assessment — chest right | Built | frontend/3DPhysicalAssessment | — | — |
| 225 | Physical assessment — abdomen UL | Built | frontend/3DPhysicalAssessment | — | — |
| 226 | Physical assessment — abdomen UR | Built | frontend/3DPhysicalAssessment | — | — |
| 227 | Physical assessment — abdomen LL | Built | frontend/3DPhysicalAssessment | — | — |
| 228 | Physical assessment — abdomen LR | Built | frontend/3DPhysicalAssessment | — | — |
| 229 | Physical assessment — pelvis | Built | frontend/3DPhysicalAssessment | — | — |
| 230 | Physical assessment — back upper | Built | frontend/3DPhysicalAssessment | — | — |
| 231 | Physical assessment — back lower | Built | frontend/3DPhysicalAssessment | — | — |
| 232 | Physical assessment — arm left | Built | frontend/3DPhysicalAssessment | — | — |
| 233 | Physical assessment — arm right | Built | frontend/3DPhysicalAssessment | — | — |
| 234 | Physical assessment — hand left | Built | frontend/3DPhysicalAssessment | — | — |
| 235 | Physical assessment — hand right | Built | frontend/3DPhysicalAssessment | — | — |
| 236 | Physical assessment — leg left | Built | frontend/3DPhysicalAssessment | — | — |
| 237 | Physical assessment — leg right | Built | frontend/3DPhysicalAssessment | — | — |
| 238 | Physical assessment — foot (both) | Built | frontend/3DPhysicalAssessment | — | — |
| 239 | Physical assessment — finding tags per region | Built | frontend/3DPhysicalAssessment | — | — |
| 240 | Physical assessment — deterministic narrative | Built | frontend/3DPhysicalAssessment | — | — |
| 241 | Physical assessment — region severity color | Built | frontend/3DPhysicalAssessment | — | — |
| 242 | Physical assessment — 2D fallback export | Built | BodyAssessmentMap.tsx | — | — |
| 243 | Physical assessment — print view | Built | BodyAssessmentMap.tsx | — | — |
| 244 | Physical assessment — burns percentage | Built | backend/models/assessments.py | — | — |
| 245 | Physical assessment — wound photos | Partial | backend/models/attachment.py | — | P3 |
| 246 | Neuro exam — alert/oriented | Built | backend/models/neuro.py | — | — |
| 247 | Neuro exam — motor strength scale | Built | backend/models/neuro.py | — | — |
| 248 | Neuro exam — sensory level | Built | backend/models/neuro.py | — | — |
| 249 | Neuro exam — reflexes | Built | backend/models/neuro.py | — | — |
| 250 | Neuro exam — speech | Built | backend/models/neuro.py | — | — |
| 251 | Neuro exam — gait | Built | backend/models/neuro.py | — | — |
| 252 | Neuro exam — cranial nerves | Built | backend/models/neuro.py | — | — |
| 253 | Cardiac exam — heart sounds | Built | backend/models/cardiac.py | — | — |
| 254 | Cardiac exam — JVD | Built | backend/models/cardiac.py | — | — |
| 255 | Cardiac exam — edema | Built | backend/models/cardiac.py | — | — |
| 256 | Cardiac exam — peripheral pulses | Built | backend/models/cardiac.py | — | — |
| 257 | Respiratory exam — lung sounds per field | Built | backend/models/respiratory.py | — | — |
| 258 | Respiratory exam — accessory muscle use | Built | backend/models/respiratory.py | — | — |
| 259 | Respiratory exam — tripod position | Built | backend/models/respiratory.py | — | — |
| 260 | Respiratory exam — cough | Built | backend/models/respiratory.py | — | — |
| 261 | Respiratory exam — sputum | Built | backend/models/respiratory.py | — | — |
| 262 | GI exam — bowel sounds | Built | backend/models/gi.py | — | — |
| 263 | GI exam — tenderness | Built | backend/models/gi.py | — | — |
| 264 | GI exam — guarding | Built | backend/models/gi.py | — | — |
| 265 | GI exam — rebound | Built | backend/models/gi.py | — | — |
| 266 | GU exam — last menstrual | Built | backend/models/gu.py | — | — |
| 267 | GU exam — pregnancy status | Built | backend/models/gu.py | — | — |
| 268 | GU exam — gravida/para | Built | backend/models/gu.py | — | — |
| 269 | GU exam — contractions | Built | backend/models/gu.py | — | — |
| 270 | Obstetric — delivery in field | Built | backend/models/ob.py | — | — |
| 271 | Obstetric — APGAR 1-min | Built | backend/models/ob.py | — | — |
| 272 | Obstetric — APGAR 5-min | Built | backend/models/ob.py | — | — |
| 273 | Pediatric — Broselow color | Built | backend/models/peds.py | — | — |
| 274 | Pediatric — weight-based dosing flag | Built | backend/models/peds.py | — | — |
| 275 | Pediatric — fontanelles | Built | backend/models/peds.py | — | — |
| 276 | Geriatric — fall risk | Built | backend/models/geri.py | — | — |
| 277 | Geriatric — cognitive baseline | Built | backend/models/geri.py | — | — |
| 278 | Behavioral — suicidal ideation | Built | backend/models/behavioral.py | — | — |
| 279 | Behavioral — homicidal ideation | Built | backend/models/behavioral.py | — | — |
| 280 | Behavioral — restraint use | Built | backend/models/behavioral.py | — | — |
| 281 | Behavioral — restraint type | Built | backend/models/behavioral.py | — | — |
| 282 | Behavioral — restraint duration | Built | backend/models/behavioral.py | — | — |
| 283 | Behavioral — law enforcement custody | Built | backend/models/behavioral.py | — | — |
| 284 | Behavioral — 5150/involuntary hold | Built | backend/models/behavioral.py | — | — |
| 285 | Refusal — capacity assessment | Built | backend/models/refusal.py | — | — |
| 286 | Refusal — risks explained | Built | backend/models/refusal.py | — | — |
| 287 | Refusal — alternative care offered | Built | backend/models/refusal.py | — | — |
| 288 | Refusal — witness signature | Built | backend/models/refusal.py | — | — |
| 289 | Refusal — patient signature | Built | backend/models/refusal.py | — | — |
| 290 | DNR — document on scene | Built | backend/models/dnr.py | — | — |
| 291 | DNR — POLST/MOLST referenced | Built | backend/models/dnr.py | — | — |
| 292 | DNR — physician contacted | Built | backend/models/dnr.py | — | — |
| 293 | Termination of resuscitation criteria | Built | backend/models/dnr.py | — | — |
| 294 | Pronouncement time | Built | backend/models/dnr.py | — | — |
| 295 | Pronouncing authority | Built | backend/models/dnr.py | — | — |
| 296 | Medication reconciliation list | Built | backend/models/med_recon.py | — | — |
| 297 | Allergy reconciliation list | Built | backend/models/allergy.py | — | — |
| 298 | Allergy reaction severity | Built | backend/models/allergy.py | — | — |
| 299 | Implants/devices list | Built | backend/models/implants.py | — | — |
| 300 | Advance directives noted | Built | backend/models/dnr.py | — | — |

## Group C — AI Smart Text (Features 301–425)
| # | Feature | Status | Existing path | Required service | Phase |
| --- | --- | --- | --- | --- | --- |
| 301 | Smart text — narrative skeleton suggestion | Missing | — | SmartTextService | P2 |
| 302 | Smart text — chief complaint phrasing | Missing | — | SmartTextService | P2 |
| 303 | Smart text — OPQRST template fill | Missing | — | SmartTextService | P2 |
| 304 | Smart text — SAMPLE template fill | Missing | — | SmartTextService | P2 |
| 305 | Smart text — vitals interpretation phrase | Missing | — | SmartTextService | P2 |
| 306 | Smart text — assessment phrasing | Missing | — | SmartTextService | P2 |
| 307 | Smart text — treatment summary | Missing | — | SmartTextService | P2 |
| 308 | Smart text — transport summary | Missing | — | SmartTextService | P2 |
| 309 | Smart text — handoff summary | Missing | — | SmartTextService | P2 |
| 310 | Smart text — refusal narrative | Missing | — | SmartTextService | P2 |
| 311 | Smart text — DNR narrative | Missing | — | SmartTextService | P2 |
| 312 | Smart text — pediatric phrasing | Missing | — | SmartTextService | P2 |
| 313 | Smart text — geriatric phrasing | Missing | — | SmartTextService | P2 |
| 314 | Smart text — behavioral phrasing | Missing | — | SmartTextService | P2 |
| 315 | Smart text — trauma phrasing | Missing | — | SmartTextService | P2 |
| 316 | Smart text — cardiac phrasing | Missing | — | SmartTextService | P2 |
| 317 | Smart text — respiratory phrasing | Missing | — | SmartTextService | P2 |
| 318 | Smart text — stroke phrasing | Missing | — | SmartTextService | P2 |
| 319 | Smart text — sepsis phrasing | Missing | — | SmartTextService | P2 |
| 320 | Smart text — overdose phrasing | Missing | — | SmartTextService | P2 |
| 321 | Smart text — allergic reaction phrasing | Missing | — | SmartTextService | P2 |
| 322 | Smart text — diabetic emergency phrasing | Missing | — | SmartTextService | P2 |
| 323 | Smart text — seizure phrasing | Missing | — | SmartTextService | P2 |
| 324 | Smart text — syncope phrasing | Missing | — | SmartTextService | P2 |
| 325 | Smart text — chest pain phrasing | Missing | — | SmartTextService | P2 |
| 326 | Smart text — abdominal pain phrasing | Missing | — | SmartTextService | P2 |
| 327 | Smart text — back pain phrasing | Missing | — | SmartTextService | P2 |
| 328 | Smart text — headache phrasing | Missing | — | SmartTextService | P2 |
| 329 | Smart text — dyspnea phrasing | Missing | — | SmartTextService | P2 |
| 330 | Smart text — fall phrasing | Missing | — | SmartTextService | P2 |
| 331 | Smart text — MVC phrasing | Missing | — | SmartTextService | P2 |
| 332 | Smart text — assault phrasing | Missing | — | SmartTextService | P2 |
| 333 | Smart text — burn phrasing | Missing | — | SmartTextService | P2 |
| 334 | Smart text — environmental exposure phrasing | Missing | — | SmartTextService | P2 |
| 335 | Smart text — obstetric phrasing | Missing | — | SmartTextService | P2 |
| 336 | Smart text — bleeding control phrasing | Missing | — | SmartTextService | P2 |
| 337 | Smart text — airway management phrasing | Missing | — | SmartTextService | P2 |
| 338 | Smart text — IV/IO phrasing | Missing | — | SmartTextService | P2 |
| 339 | Smart text — medication administration phrasing | Missing | — | SmartTextService | P2 |
| 340 | Smart text — defibrillation phrasing | Missing | — | SmartTextService | P2 |
| 341 | Smart text — cardioversion phrasing | Missing | — | SmartTextService | P2 |
| 342 | Smart text — pacing phrasing | Missing | — | SmartTextService | P2 |
| 343 | Smart text — CPR phrasing | Missing | — | SmartTextService | P2 |
| 344 | Smart text — ROSC phrasing | Missing | — | SmartTextService | P2 |
| 345 | Smart text — termination phrasing | Missing | — | SmartTextService | P2 |
| 346 | Smart text — handover to receiving phrasing | Missing | — | SmartTextService | P2 |
| 347 | Smart text — interfacility transfer phrasing | Missing | — | SmartTextService | P2 |
| 348 | Smart text — public assist phrasing | Missing | — | SmartTextService | P2 |
| 349 | Smart text — no patient contact phrasing | Missing | — | SmartTextService | P2 |
| 350 | Smart text — canceled call phrasing | Missing | — | SmartTextService | P2 |
| 351 | Smart text — MCI triage phrasing | Missing | — | SmartTextService | P2 |
| 352 | Smart text — pediatric trauma phrasing | Missing | — | SmartTextService | P2 |
| 353 | Smart text — anaphylaxis phrasing | Missing | — | SmartTextService | P2 |
| 354 | Smart text — asthma phrasing | Missing | — | SmartTextService | P2 |
| 355 | Smart text — COPD phrasing | Missing | — | SmartTextService | P2 |
| 356 | Smart text — CHF phrasing | Missing | — | SmartTextService | P2 |
| 357 | Smart text — PE phrasing | Missing | — | SmartTextService | P2 |
| 358 | Smart text — DVT phrasing | Missing | — | SmartTextService | P2 |
| 359 | Smart text — hyperglycemia phrasing | Missing | — | SmartTextService | P2 |
| 360 | Smart text — hypoglycemia phrasing | Missing | — | SmartTextService | P2 |
| 361 | Smart text — heat illness phrasing | Missing | — | SmartTextService | P2 |
| 362 | Smart text — hypothermia phrasing | Missing | — | SmartTextService | P2 |
| 363 | Smart text — drowning phrasing | Missing | — | SmartTextService | P2 |
| 364 | Smart text — electrocution phrasing | Missing | — | SmartTextService | P2 |
| 365 | Smart text — poisoning phrasing | Missing | — | SmartTextService | P2 |
| 366 | Smart text — carbon monoxide phrasing | Missing | — | SmartTextService | P2 |
| 367 | Smart text — opioid OD phrasing | Missing | — | SmartTextService | P2 |
| 368 | Smart text — Narcan administration phrasing | Missing | — | SmartTextService | P2 |
| 369 | Smart text — sexual assault phrasing | Missing | — | SmartTextService | P2 |
| 370 | Smart text — pediatric abuse phrasing | Missing | — | SmartTextService | P2 |
| 371 | Smart text — elder abuse phrasing | Missing | — | SmartTextService | P2 |
| 372 | Smart text — domestic violence phrasing | Missing | — | SmartTextService | P2 |
| 373 | Smart text — mental health crisis phrasing | Missing | — | SmartTextService | P2 |
| 374 | Smart text — suicidal patient phrasing | Missing | — | SmartTextService | P2 |
| 375 | Smart text — homeless services referral phrasing | Missing | — | SmartTextService | P2 |
| 376 | Smart text — language interpretation phrasing | Missing | — | SmartTextService | P2 |
| 377 | Smart text — refusal capacity phrasing | Missing | — | SmartTextService | P2 |
| 378 | Smart text — minor without guardian phrasing | Missing | — | SmartTextService | P2 |
| 379 | Smart text — police hold phrasing | Missing | — | SmartTextService | P2 |
| 380 | Smart text — auto-suggest from chief complaint | Missing | — | SmartTextService | P2 |
| 381 | Smart text — auto-suggest from vitals trend | Missing | — | SmartTextService | P2 |
| 382 | Smart text — auto-suggest from physical exam | Missing | — | SmartTextService | P2 |
| 383 | Smart text — auto-suggest from medications | Missing | — | SmartTextService | P2 |
| 384 | Smart text — accept/reject suggestion | Missing | — | SmartTextService | P2 |
| 385 | Smart text — edit suggestion before insert | Missing | — | SmartTextService | P2 |
| 386 | Smart text — undo last accept | Missing | — | SmartTextService | P2 |
| 387 | Smart text — provenance tag on inserted text | Missing | — | SmartTextService | P2 |
| 388 | Smart text — audit log of accepted suggestions | Missing | — | SmartTextService | P2 |
| 389 | Smart text — agency-specific phrase library | Missing | — | SmartTextService | P2 |
| 390 | Smart text — provider-specific phrase library | Missing | — | SmartTextService | P2 |
| 391 | Smart text — abbreviation expansion | Missing | — | SmartTextService | P2 |
| 392 | Smart text — spell check | Missing | — | SmartTextService | P2 |
| 393 | Smart text — grammar check | Missing | — | SmartTextService | P2 |
| 394 | Smart text — readability score | Missing | — | SmartTextService | P2 |
| 395 | Smart text — duplicate detection | Missing | — | SmartTextService | P2 |
| 396 | Smart text — contradictory statement flag | Missing | — | SmartTextService | P2 |
| 397 | Smart text — missing required element flag | Missing | — | SmartTextService | P2 |
| 398 | Smart text — billing-relevant phrase flag | Missing | — | SmartTextService | P2 |
| 399 | Smart text — legal-relevant phrase flag | Missing | — | SmartTextService | P2 |
| 400 | Smart text — disable per agency policy | Missing | — | SmartTextService | P2 |
| 401 | Sentence evidence — link suggestion to source field | Missing | — | SentenceEvidenceService | P2 |
| 402 | Sentence evidence — citation per sentence | Missing | — | SentenceEvidenceService | P2 |
| 403 | Sentence evidence — evidence panel UI | Missing | — | SentenceEvidenceService | P2 |
| 404 | Sentence evidence — no-evidence sentence flag | Missing | — | SentenceEvidenceService | P2 |
| 405 | Sentence evidence — provider override with reason | Missing | — | SentenceEvidenceService | P2 |
| 406 | Sentence evidence — evidence audit log | Missing | — | SentenceEvidenceService | P2 |
| 407 | Sentence evidence — drag-and-drop evidence binding | Missing | — | SentenceEvidenceService | P2 |
| 408 | Sentence evidence — bulk-bind to assessment | Missing | — | SentenceEvidenceService | P2 |
| 409 | Sentence evidence — export with citations | Missing | — | SentenceEvidenceService | P2 |
| 410 | Sentence evidence — strip citations for print | Missing | — | SentenceEvidenceService | P2 |
| 411 | Sentence evidence — evidence freshness check | Missing | — | SentenceEvidenceService | P2 |
| 412 | Sentence evidence — stale evidence warning | Missing | — | SentenceEvidenceService | P2 |
| 413 | Sentence evidence — evidence chain visualization | Missing | — | SentenceEvidenceService | P2 |
| 414 | Sentence evidence — provider sign-off on evidence | Missing | — | SentenceEvidenceService | P2 |
| 415 | Sentence evidence — QA can dispute evidence | Missing | — | SentenceEvidenceService | P2 |
| 416 | Sentence evidence — evidence weight metric | Missing | — | SentenceEvidenceService | P2 |
| 417 | Sentence evidence — confidence scoring per sentence | Missing | — | SentenceEvidenceService | P2 |
| 418 | Sentence evidence — display confidence in UI | Missing | — | SentenceEvidenceService | P2 |
| 419 | Sentence evidence — block lock if low-confidence unsigned | Missing | — | SentenceEvidenceService | P2 |
| 420 | Sentence evidence — telemetry of evidence coverage | Missing | — | SentenceEvidenceService | P2 |
| 421 | Sentence evidence — narrative coverage % | Missing | — | SentenceEvidenceService | P2 |
| 422 | Sentence evidence — per-agency policy threshold | Missing | — | SentenceEvidenceService | P2 |
| 423 | Sentence evidence — model version pinning | Missing | — | SentenceEvidenceService | P2 |
| 424 | Sentence evidence — prompt version pinning | Missing | — | SentenceEvidenceService | P2 |
| 425 | Sentence evidence — re-bind after edit | Missing | — | SentenceEvidenceService | P2 |

## Group D — NEMSIS Validation (Features 426–500)
| # | Feature | Status | Existing path | Required service | Phase |
| --- | --- | --- | --- | --- | --- |
| 426 | NEMSIS 3.5 schema bundled | Built | backend/exports/nemsis | — | — |
| 427 | NEMSIS XSD validation on export | Built | backend/exports/nemsis | — | — |
| 428 | NEMSIS state schematron support | Partial | backend/exports/nemsis | — | P3 |
| 429 | NEMSIS field-level validation pre-lock | Missing | — | LockReadinessService | P2 |
| 430 | NEMSIS conditional element validation | Missing | — | LockReadinessService | P2 |
| 431 | NEMSIS required element checklist | Missing | — | LockReadinessService | P2 |
| 432 | NEMSIS recommended element warning | Missing | — | LockReadinessService | P2 |
| 433 | NEMSIS optional element acceptance | Built | backend/exports/nemsis | — | — |
| 434 | NEMSIS code set lookups | Built | backend/exports/nemsis | — | — |
| 435 | NEMSIS code set version pinning | Built | backend/exports/nemsis | — | — |
| 436 | NEMSIS code set update mechanism | Partial | backend/exports/nemsis | — | P3 |
| 437 | NEMSIS date/time format compliance | Built | backend/exports/nemsis | — | — |
| 438 | NEMSIS time zone handling | Built | backend/exports/nemsis | — | — |
| 439 | NEMSIS not-values handling (NA/NV/NK) | Built | backend/exports/nemsis | — | — |
| 440 | NEMSIS PCR identifier generation | Built | backend/exports/nemsis | — | — |
| 441 | NEMSIS state-specific extensions | Partial | backend/exports/nemsis | — | P3 |
| 442 | NEMSIS retransmission tracking | Missing | — | LockReadinessService | P2 |
| 443 | NEMSIS receipt acknowledgement | Missing | — | LockReadinessService | P2 |
| 444 | NEMSIS submission status dashboard | Missing | — | LockReadinessService | P2 |
| 445 | NEMSIS rejection reason capture | Missing | — | LockReadinessService | P2 |
| 446 | NEMSIS auto-resubmit after fix | Missing | — | LockReadinessService | P2 |
| 447 | NEMSIS schematron rule library | Missing | — | LockReadinessService | P2 |
| 448 | NEMSIS validation report PDF | Missing | — | LockReadinessService | P2 |
| 449 | NEMSIS validation report JSON | Missing | — | LockReadinessService | P2 |
| 450 | NEMSIS lock-readiness composite score | Missing | — | LockReadinessService | P2 |
| 451 | NEMSIS lock-readiness gauge UI | Missing | — | LockReadinessService | P2 |
| 452 | NEMSIS missing-fields drilldown | Missing | — | LockReadinessService | P2 |
| 453 | NEMSIS bulk validation of drafts | Missing | — | LockReadinessService | P2 |
| 454 | NEMSIS validation telemetry | Missing | — | LockReadinessService | P2 |
| 455 | NEMSIS validation per-agency thresholds | Missing | — | LockReadinessService | P2 |
| 456 | NEMSIS validation per-state thresholds | Missing | — | LockReadinessService | P2 |
| 457 | NEMSIS demographic element validators | Missing | — | LockReadinessService | P2 |
| 458 | NEMSIS situation element validators | Missing | — | LockReadinessService | P2 |
| 459 | NEMSIS history element validators | Missing | — | LockReadinessService | P2 |
| 460 | NEMSIS narrative element validators | Missing | — | LockReadinessService | P2 |
| 461 | NEMSIS vitals element validators | Missing | — | LockReadinessService | P2 |
| 462 | NEMSIS medication element validators | Missing | — | LockReadinessService | P2 |
| 463 | NEMSIS procedure element validators | Missing | — | LockReadinessService | P2 |
| 464 | NEMSIS protocol element validators | Missing | — | LockReadinessService | P2 |
| 465 | NEMSIS disposition element validators | Missing | — | LockReadinessService | P2 |
| 466 | NEMSIS outcome element validators | Missing | — | LockReadinessService | P2 |
| 467 | NEMSIS payment element validators | Missing | — | LockReadinessService | P2 |
| 468 | NEMSIS signature element validators | Missing | — | LockReadinessService | P2 |
| 469 | NEMSIS attachment element validators | Missing | — | LockReadinessService | P2 |
| 470 | NEMSIS scene element validators | Missing | — | LockReadinessService | P2 |
| 471 | NEMSIS times element validators | Missing | — | LockReadinessService | P2 |
| 472 | NEMSIS response element validators | Missing | — | LockReadinessService | P2 |
| 473 | NEMSIS crew element validators | Missing | — | LockReadinessService | P2 |
| 474 | NEMSIS device element validators | Missing | — | LockReadinessService | P2 |
| 475 | NEMSIS injury element validators | Missing | — | LockReadinessService | P2 |
| 476 | NEMSIS exam element validators | Missing | — | LockReadinessService | P2 |
| 477 | NEMSIS cardiac arrest element validators | Missing | — | LockReadinessService | P2 |
| 478 | NEMSIS labs element validators | Missing | — | LockReadinessService | P2 |
| 479 | NEMSIS ePCR provenance element validators | Missing | — | LockReadinessService | P2 |
| 480 | NEMSIS chained validator dependencies | Missing | — | LockReadinessService | P2 |
| 481 | NEMSIS validator pre-warm on chart open | Missing | — | LockReadinessService | P2 |
| 482 | NEMSIS validator incremental on edit | Missing | — | LockReadinessService | P2 |
| 483 | NEMSIS validator caching | Missing | — | LockReadinessService | P2 |
| 484 | NEMSIS validator parallelization | Missing | — | LockReadinessService | P2 |
| 485 | NEMSIS validator perf budget | Missing | — | LockReadinessService | P2 |
| 486 | NEMSIS validator error categories | Missing | — | LockReadinessService | P2 |
| 487 | NEMSIS validator severity levels | Missing | — | LockReadinessService | P2 |
| 488 | NEMSIS validator suppress with reason | Missing | — | LockReadinessService | P2 |
| 489 | NEMSIS validator suppression audit | Missing | — | LockReadinessService | P2 |
| 490 | NEMSIS validator provider override audit | Missing | — | LockReadinessService | P2 |
| 491 | NEMSIS dataset uploader to state | Partial | backend/exports/state.py | LockReadinessService | P2 |
| 492 | NEMSIS dataset uploader to national | Missing | — | LockReadinessService | P2 |
| 493 | NEMSIS dataset uploader scheduling | Missing | — | LockReadinessService | P2 |
| 494 | NEMSIS dataset uploader retry policy | Missing | — | LockReadinessService | P2 |
| 495 | NEMSIS dataset uploader auth (SAML/OAuth) | Missing | — | LockReadinessService | P2 |
| 496 | NEMSIS dataset uploader receipt log | Missing | — | LockReadinessService | P2 |
| 497 | NEMSIS dataset uploader failure alerting | Missing | — | LockReadinessService | P2 |
| 498 | NEMSIS dataset uploader rate limiting | Missing | — | LockReadinessService | P2 |
| 499 | NEMSIS dataset uploader compliance report | Missing | — | LockReadinessService | P2 |
| 500 | NEMSIS dataset uploader admin dashboard | Missing | — | LockReadinessService | P2 |

## Group E — RxNorm (Features 501–540)
| # | Feature | Status | Existing path | Required service | Phase |
| --- | --- | --- | --- | --- | --- |
| 501 | RxNorm code search by name | Missing | — | RxNormService | P2 |
| 502 | RxNorm code search by RXCUI | Missing | — | RxNormService | P2 |
| 503 | RxNorm code search by brand | Missing | — | RxNormService | P2 |
| 504 | RxNorm code search by ingredient | Missing | — | RxNormService | P2 |
| 505 | RxNorm dose form lookup | Missing | — | RxNormService | P2 |
| 506 | RxNorm strength lookup | Missing | — | RxNormService | P2 |
| 507 | RxNorm route lookup | Missing | — | RxNormService | P2 |
| 508 | RxNorm related concepts (RxNav) | Missing | — | RxNormService | P2 |
| 509 | RxNorm version pinning | Missing | — | RxNormService | P2 |
| 510 | RxNorm offline cache | Missing | — | RxNormService | P2 |
| 511 | RxNorm cache refresh schedule | Missing | — | RxNormService | P2 |
| 512 | RxNorm fuzzy match | Missing | — | RxNormService | P2 |
| 513 | RxNorm agency formulary overlay | Missing | — | RxNormService | P2 |
| 514 | RxNorm controlled substance flag | Missing | — | RxNormService | P2 |
| 515 | RxNorm DEA schedule lookup | Missing | — | RxNormService | P2 |
| 516 | RxNorm interaction lookup (DDI) | Missing | — | RxNormService | P2 |
| 517 | RxNorm allergy cross-reaction lookup | Missing | — | RxNormService | P2 |
| 518 | RxNorm pediatric dosing lookup | Missing | — | RxNormService | P2 |
| 519 | RxNorm geriatric dosing lookup | Missing | — | RxNormService | P2 |
| 520 | RxNorm renal dose adjustment | Missing | — | RxNormService | P2 |
| 521 | RxNorm hepatic dose adjustment | Missing | — | RxNormService | P2 |
| 522 | RxNorm pregnancy category | Missing | — | RxNormService | P2 |
| 523 | RxNorm lactation category | Missing | — | RxNormService | P2 |
| 524 | RxNorm narcotic flag | Missing | — | RxNormService | P2 |
| 525 | RxNorm narcotic chain-of-custody link | Missing | — | Narcotics bridge | P2 |
| 526 | RxNorm admin route validation | Missing | — | RxNormService | P2 |
| 527 | RxNorm dose validation against weight | Missing | — | RxNormService | P2 |
| 528 | RxNorm max dose warning | Missing | — | RxNormService | P2 |
| 529 | RxNorm min dose warning | Missing | — | RxNormService | P2 |
| 530 | RxNorm administration timestamp | Missing | — | RxNormService | P2 |
| 531 | RxNorm administering provider link | Missing | — | RxNormService | P2 |
| 532 | RxNorm dose-effect reassessment | Missing | — | RxNormService | P2 |
| 533 | RxNorm adverse event capture | Missing | — | RxNormService | P2 |
| 534 | RxNorm export to NEMSIS code | Missing | — | RxNormService | P2 |
| 535 | RxNorm export to billing code | Missing | — | RxNormService | P2 |
| 536 | RxNorm telemetry of usage | Missing | — | RxNormService | P2 |
| 537 | RxNorm formulary audit log | Missing | — | RxNormService | P2 |
| 538 | RxNorm bulk import for agency | Missing | — | RxNormService | P2 |
| 539 | RxNorm bulk export for state | Missing | — | RxNormService | P2 |
| 540 | RxNorm admin dashboard | Missing | — | RxNormService | P2 |

## Group F — ICD-10 (Features 541–590)
| # | Feature | Status | Existing path | Required service | Phase |
| --- | --- | --- | --- | --- | --- |
| 541 | ICD-10 code search by name | Missing | — | Icd10Service | P2 |
| 542 | ICD-10 code search by code | Missing | — | Icd10Service | P2 |
| 543 | ICD-10 code hierarchy browse | Missing | — | Icd10Service | P2 |
| 544 | ICD-10 code synonyms lookup | Missing | — | Icd10Service | P2 |
| 545 | ICD-10 code version pinning | Missing | — | Icd10Service | P2 |
| 546 | ICD-10 offline cache | Missing | — | Icd10Service | P2 |
| 547 | ICD-10 fuzzy match | Missing | — | Icd10Service | P2 |
| 548 | ICD-10 chief complaint suggestion (provider-confirmed) | Missing | — | Icd10Service | P2 |
| 549 | ICD-10 secondary diagnoses list | Missing | — | Icd10Service | P2 |
| 550 | ICD-10 external cause codes (V-Y) | Missing | — | Icd10Service | P2 |
| 551 | ICD-10 place-of-occurrence codes | Missing | — | Icd10Service | P2 |
| 552 | ICD-10 activity codes | Missing | — | Icd10Service | P2 |
| 553 | ICD-10 status-of-external-cause codes | Missing | — | Icd10Service | P2 |
| 554 | ICD-10 mapping to NEMSIS impressions | Missing | — | Icd10Service | P2 |
| 555 | ICD-10 mapping to SNOMED | Missing | — | Icd10Service | P2 |
| 556 | ICD-10 mapping to billing codes | Missing | — | Icd10Service | P2 |
| 557 | ICD-10 mapping to protocol codes | Missing | — | Icd10Service | P2 |
| 558 | ICD-10 evidence chain to clinical fields | Missing | — | Icd10Service | P2 |
| 559 | ICD-10 provider override workflow | Missing | — | Icd10Service | P2 |
| 560 | ICD-10 no-auto-assignment rule | Missing | — | Icd10Service | P2 |
| 561 | ICD-10 telemetry of provider acceptance | Missing | — | Icd10Service | P2 |
| 562 | ICD-10 telemetry of provider rejection | Missing | — | Icd10Service | P2 |
| 563 | ICD-10 audit log of changes | Missing | — | Icd10Service | P2 |
| 564 | ICD-10 confidence score per suggestion | Missing | — | Icd10Service | P2 |
| 565 | ICD-10 explanation per suggestion | Missing | — | Icd10Service | P2 |
| 566 | ICD-10 multi-code suggestion | Missing | — | Icd10Service | P2 |
| 567 | ICD-10 pediatric code overlay | Missing | — | Icd10Service | P2 |
| 568 | ICD-10 geriatric code overlay | Missing | — | Icd10Service | P2 |
| 569 | ICD-10 obstetric code overlay | Missing | — | Icd10Service | P2 |
| 570 | ICD-10 mental health code overlay | Missing | — | Icd10Service | P2 |
| 571 | ICD-10 trauma code overlay | Missing | — | Icd10Service | P2 |
| 572 | ICD-10 substance abuse code overlay | Missing | — | Icd10Service | P2 |
| 573 | ICD-10 chronic vs acute flag | Missing | — | Icd10Service | P2 |
| 574 | ICD-10 laterality flag | Missing | — | Icd10Service | P2 |
| 575 | ICD-10 encounter sequence flag | Missing | — | Icd10Service | P2 |
| 576 | ICD-10 export to billing | Missing | — | Icd10Service | P2 |
| 577 | ICD-10 export to NEMSIS | Missing | — | Icd10Service | P2 |
| 578 | ICD-10 export to state repository | Missing | — | Icd10Service | P2 |
| 579 | ICD-10 admin code-set updater | Missing | — | Icd10Service | P2 |
| 580 | ICD-10 admin code-set diff viewer | Missing | — | Icd10Service | P2 |
| 581 | ICD-10 admin code-set rollback | Missing | — | Icd10Service | P2 |
| 582 | ICD-10 admin per-agency override list | Missing | — | Icd10Service | P2 |
| 583 | ICD-10 admin deprecation warning | Missing | — | Icd10Service | P2 |
| 584 | ICD-10 search performance budget | Missing | — | Icd10Service | P2 |
| 585 | ICD-10 search ranking customization | Missing | — | Icd10Service | P2 |
| 586 | ICD-10 search analytics | Missing | — | Icd10Service | P2 |
| 587 | ICD-10 favorites per provider | Missing | — | Icd10Service | P2 |
| 588 | ICD-10 recent codes per provider | Missing | — | Icd10Service | P2 |
| 589 | ICD-10 quick-pick per agency | Missing | — | Icd10Service | P2 |
| 590 | ICD-10 admin dashboard | Missing | — | Icd10Service | P2 |

## Group G — Repeat Patient (Features 591–650)
| # | Feature | Status | Existing path | Required service | Phase |
| --- | --- | --- | --- | --- | --- |
| 591 | Repeat-patient match by name+DOB | Missing | — | RepeatPatientService | P2 |
| 592 | Repeat-patient match by SSN | Missing | — | RepeatPatientService | P2 |
| 593 | Repeat-patient match by phone | Missing | — | RepeatPatientService | P2 |
| 594 | Repeat-patient match by address | Missing | — | RepeatPatientService | P2 |
| 595 | Repeat-patient match by insurance | Missing | — | RepeatPatientService | P2 |
| 596 | Repeat-patient match by composite score | Missing | — | RepeatPatientService | P2 |
| 597 | Repeat-patient suggestion list UI | Missing | — | RepeatPatientService | P2 |
| 598 | Repeat-patient confirmation modal | Missing | — | RepeatPatientService | P2 |
| 599 | Repeat-patient provider must confirm | Missing | — | RepeatPatientService | P2 |
| 600 | Repeat-patient no-auto-merge rule | Missing | — | RepeatPatientService | P2 |
| 601 | Repeat-patient history summary card | Missing | — | RepeatPatientService | P2 |
| 602 | Repeat-patient recent encounters list | Missing | — | RepeatPatientService | P2 |
| 603 | Repeat-patient medications carry-over | Missing | — | RepeatPatientService | P2 |
| 604 | Repeat-patient allergies carry-over | Missing | — | RepeatPatientService | P2 |
| 605 | Repeat-patient PMH carry-over | Missing | — | RepeatPatientService | P2 |
| 606 | Repeat-patient advance directive carry-over | Missing | — | RepeatPatientService | P2 |
| 607 | Repeat-patient emergency contact carry-over | Missing | — | RepeatPatientService | P2 |
| 608 | Repeat-patient insurance carry-over | Missing | — | RepeatPatientService | P2 |
| 609 | Repeat-patient address carry-over | Missing | — | RepeatPatientService | P2 |
| 610 | Repeat-patient phone carry-over | Missing | — | RepeatPatientService | P2 |
| 611 | Repeat-patient PCP carry-over | Missing | — | RepeatPatientService | P2 |
| 612 | Repeat-patient pharmacy carry-over | Missing | — | RepeatPatientService | P2 |
| 613 | Repeat-patient interpreter pref carry-over | Missing | — | RepeatPatientService | P2 |
| 614 | Repeat-patient implants/devices carry-over | Missing | — | RepeatPatientService | P2 |
| 615 | Repeat-patient behavioral history carry-over | Missing | — | RepeatPatientService | P2 |
| 616 | Repeat-patient frequent-flyer flag | Missing | — | RepeatPatientService | P2 |
| 617 | Repeat-patient agency policy gating | Missing | — | RepeatPatientService | P2 |
| 618 | Repeat-patient unmerge workflow | Missing | — | RepeatPatientService | P2 |
| 619 | Repeat-patient audit log of merges | Missing | — | RepeatPatientService | P2 |
| 620 | Repeat-patient audit log of unmerges | Missing | — | RepeatPatientService | P2 |
| 621 | Repeat-patient telemetry of accept rate | Missing | — | RepeatPatientService | P2 |
| 622 | Repeat-patient telemetry of reject rate | Missing | — | RepeatPatientService | P2 |
| 623 | Repeat-patient privacy guardrail (cross-agency) | Missing | — | RepeatPatientService | P2 |
| 624 | Repeat-patient HIPAA disclosure log | Missing | — | RepeatPatientService | P2 |
| 625 | Repeat-patient minor patient guardrail | Missing | — | RepeatPatientService | P2 |
| 626 | Repeat-patient deceased flag | Missing | — | RepeatPatientService | P2 |
| 627 | Repeat-patient VIP flag | Missing | — | RepeatPatientService | P2 |
| 628 | Repeat-patient confidential record flag | Missing | — | RepeatPatientService | P2 |
| 629 | Repeat-patient sealed record gating | Missing | — | RepeatPatientService | P2 |
| 630 | Repeat-patient search performance budget | Missing | — | RepeatPatientService | P2 |
| 631 | Repeat-patient index strategy | Missing | — | RepeatPatientService | P2 |
| 632 | Repeat-patient phonetic name matching | Missing | — | RepeatPatientService | P2 |
| 633 | Repeat-patient cross-name alias support | Missing | — | RepeatPatientService | P2 |
| 634 | Repeat-patient DOB tolerance window | Missing | — | RepeatPatientService | P2 |
| 635 | Repeat-patient cross-DOB ambiguity warning | Missing | — | RepeatPatientService | P2 |
| 636 | Repeat-patient duplicate-record cleanup tool | Missing | — | RepeatPatientService | P2 |
| 637 | Repeat-patient duplicate report | Missing | — | RepeatPatientService | P2 |
| 638 | Repeat-patient master person index export | Missing | — | RepeatPatientService | P2 |
| 639 | Repeat-patient MPI import | Missing | — | RepeatPatientService | P2 |
| 640 | Repeat-patient external MPI integration | Missing | — | RepeatPatientService | P2 |
| 641 | Repeat-patient confidence score UI | Missing | — | RepeatPatientService | P2 |
| 642 | Repeat-patient justification capture | Missing | — | RepeatPatientService | P2 |
| 643 | Repeat-patient override-reason capture | Missing | — | RepeatPatientService | P2 |
| 644 | Repeat-patient model version pinning | Missing | — | RepeatPatientService | P2 |
| 645 | Repeat-patient admin dashboard | Missing | — | RepeatPatientService | P2 |
| 646 | Repeat-patient agency analytics | Missing | — | RepeatPatientService | P2 |
| 647 | Repeat-patient temporal trending | Missing | — | RepeatPatientService | P2 |
| 648 | Repeat-patient social-determinants overlay | Missing | — | RepeatPatientService | P2 |
| 649 | Repeat-patient referral suggestions | Missing | — | RepeatPatientService | P2 |
| 650 | Repeat-patient care-plan continuity field | Missing | — | RepeatPatientService | P2 |

## Group H — Prior ECG (Features 651–700)
| # | Feature | Status | Existing path | Required service | Phase |
| --- | --- | --- | --- | --- | --- |
| 651 | Prior ECG retrieval by patient | Missing | — | PriorEcgService | P2 |
| 652 | Prior ECG retrieval by encounter | Missing | — | PriorEcgService | P2 |
| 653 | Prior ECG retrieval by date range | Missing | — | PriorEcgService | P2 |
| 654 | Prior ECG storage of 12-lead image | Missing | — | PriorEcgService | P2 |
| 655 | Prior ECG storage of waveform data | Missing | — | PriorEcgService | P2 |
| 656 | Prior ECG storage of interpretation text | Missing | — | PriorEcgService | P2 |
| 657 | Prior ECG storage of acquisition timestamp | Missing | — | PriorEcgService | P2 |
| 658 | Prior ECG storage of device source | Missing | — | PriorEcgService | P2 |
| 659 | Prior ECG storage of provider source | Missing | — | PriorEcgService | P2 |
| 660 | Prior ECG side-by-side comparison UI | Missing | — | PriorEcgService | P2 |
| 661 | Prior ECG difference highlight | Missing | — | PriorEcgService | P2 |
| 662 | Prior ECG provider must confirm comparison | Missing | — | PriorEcgService | P2 |
| 663 | Prior ECG no-auto-diagnosis rule | Missing | — | PriorEcgService | P2 |
| 664 | Prior ECG no-STEMI-detection rule | Missing | — | PriorEcgService | P2 |
| 665 | Prior ECG honest unavailable state | Built | EpcrUnavailableState | — | — |
| 666 | Prior ECG import from monitor (LP15/X) | Missing | — | DeviceBridge | P3 |
| 667 | Prior ECG import from hospital system | Missing | — | PriorEcgService | P2 |
| 668 | Prior ECG import HL7 ORU | Missing | — | PriorEcgService | P2 |
| 669 | Prior ECG import FHIR Observation | Missing | — | PriorEcgService | P2 |
| 670 | Prior ECG import DICOM-ECG | Missing | — | PriorEcgService | P2 |
| 671 | Prior ECG provenance chain | Missing | — | PriorEcgService | P2 |
| 672 | Prior ECG audit log | Missing | — | PriorEcgService | P2 |
| 673 | Prior ECG access control by patient consent | Missing | — | PriorEcgService | P2 |
| 674 | Prior ECG HIPAA disclosure log | Missing | — | PriorEcgService | P2 |
| 675 | Prior ECG retention policy | Missing | — | PriorEcgService | P2 |
| 676 | Prior ECG purge after retention | Missing | — | PriorEcgService | P2 |
| 677 | Prior ECG export to receiving facility | Missing | — | PriorEcgService | P2 |
| 678 | Prior ECG export to QA review | Missing | — | PriorEcgService | P2 |
| 679 | Prior ECG export to research deidentified | Missing | — | PriorEcgService | P2 |
| 680 | Prior ECG analytics — interval changes | Missing | — | PriorEcgService | P2 |
| 681 | Prior ECG analytics — rate trend | Missing | — | PriorEcgService | P2 |
| 682 | Prior ECG analytics — axis trend | Missing | — | PriorEcgService | P2 |
| 683 | Prior ECG analytics — ST trend (advisory only) | Missing | — | PriorEcgService | P2 |
| 684 | Prior ECG annotation tool | Missing | — | PriorEcgService | P2 |
| 685 | Prior ECG annotation per lead | Missing | — | PriorEcgService | P2 |
| 686 | Prior ECG annotation persistence | Missing | — | PriorEcgService | P2 |
| 687 | Prior ECG annotation provider attribution | Missing | — | PriorEcgService | P2 |
| 688 | Prior ECG annotation export | Missing | — | PriorEcgService | P2 |
| 689 | Prior ECG search performance budget | Missing | — | PriorEcgService | P2 |
| 690 | Prior ECG storage cost monitoring | Missing | — | PriorEcgService | P2 |
| 691 | Prior ECG model version pinning (advisory) | Missing | — | PriorEcgService | P2 |
| 692 | Prior ECG provider feedback capture | Missing | — | PriorEcgService | P2 |
| 693 | Prior ECG telemetry of usage | Missing | — | PriorEcgService | P2 |
| 694 | Prior ECG telemetry of comparison rate | Missing | — | PriorEcgService | P2 |
| 695 | Prior ECG admin dashboard | Missing | — | PriorEcgService | P2 |
| 696 | Prior ECG cross-agency consent gating | Missing | — | PriorEcgService | P2 |
| 697 | Prior ECG patient access portal (read) | Missing | — | PriorEcgService | P3 |
| 698 | Prior ECG continuity-of-care document export | Missing | — | PriorEcgService | P2 |
| 699 | Prior ECG legal hold flag | Missing | — | PriorEcgService | P2 |
| 700 | Prior ECG forensic export | Missing | — | PriorEcgService | P2 |

## Group I — Mapbox (Features 701–760)
| # | Feature | Status | Existing path | Required service | Phase |
| --- | --- | --- | --- | --- | --- |
| 701 | Mapbox base map render | Missing | — | MapboxLocationService | P2 |
| 702 | Mapbox dark theme | Missing | — | MapboxLocationService | P2 |
| 703 | Mapbox scene pin | Missing | — | MapboxLocationService | P2 |
| 704 | Mapbox destination pin | Missing | — | MapboxLocationService | P2 |
| 705 | Mapbox unit position pin | Missing | — | MapboxLocationService | P2 |
| 706 | Mapbox geocoding (address → coords) | Missing | — | MapboxLocationService | P2 |
| 707 | Mapbox reverse geocoding (coords → address) | Missing | — | MapboxLocationService | P2 |
| 708 | Mapbox routing display | Missing | — | MapboxLocationService | P2 |
| 709 | Mapbox ETA estimate | Missing | — | MapboxLocationService | P2 |
| 710 | Mapbox traffic overlay | Missing | — | MapboxLocationService | P2 |
| 711 | Mapbox hospital category overlay | Missing | — | MapboxLocationService | P2 |
| 712 | Mapbox trauma center overlay | Missing | — | MapboxLocationService | P2 |
| 713 | Mapbox stroke center overlay | Missing | — | MapboxLocationService | P2 |
| 714 | Mapbox STEMI center overlay | Missing | — | MapboxLocationService | P2 |
| 715 | Mapbox pediatric center overlay | Missing | — | MapboxLocationService | P2 |
| 716 | Mapbox burn center overlay | Missing | — | MapboxLocationService | P2 |
| 717 | Mapbox hyperbaric center overlay | Missing | — | MapboxLocationService | P2 |
| 718 | Mapbox helipad overlay | Missing | — | MapboxLocationService | P2 |
| 719 | Mapbox staging area overlay | Missing | — | MapboxLocationService | P2 |
| 720 | Mapbox MCI zone overlay | Missing | — | MapboxLocationService | P2 |
| 721 | Mapbox hazard overlay | Missing | — | MapboxLocationService | P2 |
| 722 | Mapbox weather overlay | Missing | — | MapboxLocationService | P2 |
| 723 | Mapbox fire perimeter overlay | Missing | — | MapboxLocationService | P2 |
| 724 | Mapbox flood overlay | Missing | — | MapboxLocationService | P2 |
| 725 | Mapbox road closure overlay | Missing | — | MapboxLocationService | P2 |
| 726 | Mapbox unit cluster view | Missing | — | MapboxLocationService | P2 |
| 727 | Mapbox unit availability color | Missing | — | MapboxLocationService | P2 |
| 728 | Mapbox unit history trail | Missing | — | MapboxLocationService | P2 |
| 729 | Mapbox heatmap of call density | Missing | — | MapboxLocationService | P2 |
| 730 | Mapbox isochrone — response time | Missing | — | MapboxLocationService | P2 |
| 731 | Mapbox isochrone — coverage gap | Missing | — | MapboxLocationService | P2 |
| 732 | Mapbox offline tile cache | Missing | — | MapboxLocationService | P2 |
| 733 | Mapbox offline route cache | Missing | — | MapboxLocationService | P2 |
| 734 | Mapbox tile budget monitoring | Missing | — | MapboxLocationService | P2 |
| 735 | Mapbox API key rotation | Missing | — | MapboxLocationService | P2 |
| 736 | Mapbox usage telemetry | Missing | — | MapboxLocationService | P2 |
| 737 | Mapbox accessibility — high contrast | Missing | — | MapboxLocationService | P2 |
| 738 | Mapbox accessibility — keyboard nav | Missing | — | MapboxLocationService | P2 |
| 739 | Mapbox print export | Missing | — | MapboxLocationService | P2 |
| 740 | Mapbox snapshot to chart attachment | Missing | — | MapboxLocationService | P2 |
| 741 | Mapbox scene boundary draw | Missing | — | MapboxLocationService | P2 |
| 742 | Mapbox scene boundary persist | Missing | — | MapboxLocationService | P2 |
| 743 | Mapbox scene photo geotag | Missing | — | MapboxLocationService | P2 |
| 744 | Mapbox patient location pin (MCI) | Missing | — | MapboxLocationService | P2 |
| 745 | Mapbox unit assignment to pin (MCI) | Missing | — | MapboxLocationService | P2 |
| 746 | Mapbox triage color per pin | Missing | — | MapboxLocationService | P2 |
| 747 | Mapbox MCI command view | Missing | — | MapboxLocationService | P2 |
| 748 | Mapbox EMS command share view | Missing | — | MapboxLocationService | P2 |
| 749 | Mapbox CAD bridge for incident pin | Missing | — | MapboxLocationService | P2 |
| 750 | Mapbox AVL bridge for unit pin | Missing | — | MapboxLocationService | P2 |
| 751 | Mapbox geofence — agency boundary | Missing | — | MapboxLocationService | P2 |
| 752 | Mapbox geofence — district boundary | Missing | — | MapboxLocationService | P2 |
| 753 | Mapbox geofence — state boundary | Missing | — | MapboxLocationService | P2 |
| 754 | Mapbox geofence violation alert | Missing | — | MapboxLocationService | P2 |
| 755 | Mapbox routing avoidances (e.g., school zone) | Missing | — | MapboxLocationService | P2 |
| 756 | Mapbox routing emergency mode | Missing | — | MapboxLocationService | P2 |
| 757 | Mapbox audit log of map actions | Missing | — | MapboxLocationService | P2 |
| 758 | Mapbox per-agency custom layer | Missing | — | MapboxLocationService | P2 |
| 759 | Mapbox per-agency style override | Missing | — | MapboxLocationService | P2 |
| 760 | Mapbox admin dashboard | Missing | — | MapboxLocationService | P2 |

## Group J — Multi-Patient (Features 761–825)
| # | Feature | Status | Existing path | Required service | Phase |
| --- | --- | --- | --- | --- | --- |
| 761 | Multi-patient incident container | Missing | — | MultiPatientService | P2 |
| 762 | Multi-patient PCR linking | Missing | — | MultiPatientService | P2 |
| 763 | Multi-patient unique chart per patient | Missing | — | MultiPatientService | P2 |
| 764 | Multi-patient shared scene block | Missing | — | MultiPatientService | P2 |
| 765 | Multi-patient shared crew block | Missing | — | MultiPatientService | P2 |
| 766 | Multi-patient shared CAD reference | Missing | — | MultiPatientService | P2 |
| 767 | Multi-patient shared mileage | Missing | — | MultiPatientService | P2 |
| 768 | Multi-patient triage category per patient | Missing | — | MultiPatientService | P2 |
| 769 | Multi-patient triage tag ID per patient | Missing | — | MultiPatientService | P2 |
| 770 | Multi-patient START algorithm | Missing | — | MultiPatientService | P2 |
| 771 | Multi-patient JumpSTART (peds) algorithm | Missing | — | MultiPatientService | P2 |
| 772 | Multi-patient SALT algorithm | Missing | — | MultiPatientService | P2 |
| 773 | Multi-patient retriage support | Missing | — | MultiPatientService | P2 |
| 774 | Multi-patient transport assignment | Missing | — | MultiPatientService | P2 |
| 775 | Multi-patient destination per patient | Missing | — | MultiPatientService | P2 |
| 776 | Multi-patient unit assignment | Missing | — | MultiPatientService | P2 |
| 777 | Multi-patient unit splitting | Missing | — | MultiPatientService | P2 |
| 778 | Multi-patient field treatment area | Missing | — | MultiPatientService | P2 |
| 779 | Multi-patient field treatment area assignment | Missing | — | MultiPatientService | P2 |
| 780 | Multi-patient command staff capture | Missing | — | MultiPatientService | P2 |
| 781 | Multi-patient IC name | Missing | — | MultiPatientService | P2 |
| 782 | Multi-patient EMS branch | Missing | — | MultiPatientService | P2 |
| 783 | Multi-patient triage officer | Missing | — | MultiPatientService | P2 |
| 784 | Multi-patient treatment officer | Missing | — | MultiPatientService | P2 |
| 785 | Multi-patient transport officer | Missing | — | MultiPatientService | P2 |
| 786 | Multi-patient staging officer | Missing | — | MultiPatientService | P2 |
| 787 | Multi-patient morgue officer | Missing | — | MultiPatientService | P2 |
| 788 | Multi-patient hospital alert notifications | Missing | — | MultiPatientService | P2 |
| 789 | Multi-patient hospital capacity sync | Missing | — | MultiPatientService | P2 |
| 790 | Multi-patient agency mutual aid roster | Missing | — | MultiPatientService | P2 |
| 791 | Multi-patient cross-agency PCR share | Missing | — | MultiPatientService | P2 |
| 792 | Multi-patient real-time count | Missing | — | MultiPatientService | P2 |
| 793 | Multi-patient bulk demographics entry | Missing | — | MultiPatientService | P2 |
| 794 | Multi-patient unknown-patient placeholder | Missing | — | MultiPatientService | P2 |
| 795 | Multi-patient minor patient placeholder | Missing | — | MultiPatientService | P2 |
| 796 | Multi-patient fatality placeholder | Missing | — | MultiPatientService | P2 |
| 797 | Multi-patient PD/ME handoff capture | Missing | — | MultiPatientService | P2 |
| 798 | Multi-patient family reunification capture | Missing | — | MultiPatientService | P2 |
| 799 | Multi-patient interpreter need flag | Missing | — | MultiPatientService | P2 |
| 800 | Multi-patient incident timeline | Missing | — | MultiPatientService | P2 |
| 801 | Multi-patient resource log | Missing | — | MultiPatientService | P2 |
| 802 | Multi-patient resource ICS-214 export | Missing | — | MultiPatientService | P2 |
| 803 | Multi-patient ICS-201 export | Missing | — | MultiPatientService | P2 |
| 804 | Multi-patient ICS-204 export | Missing | — | MultiPatientService | P2 |
| 805 | Multi-patient ICS-205 export | Missing | — | MultiPatientService | P2 |
| 806 | Multi-patient ICS-206 export | Missing | — | MultiPatientService | P2 |
| 807 | Multi-patient ICS-209 export | Missing | — | MultiPatientService | P2 |
| 808 | Multi-patient ICS-213 export | Missing | — | MultiPatientService | P2 |
| 809 | Multi-patient ICS-218 export | Missing | — | MultiPatientService | P2 |
| 810 | Multi-patient AAR generation | Missing | — | MultiPatientService | P2 |
| 811 | Multi-patient hot wash notes | Missing | — | MultiPatientService | P2 |
| 812 | Multi-patient debrief capture | Missing | — | MultiPatientService | P2 |
| 813 | Multi-patient lessons learned | Missing | — | MultiPatientService | P2 |
| 814 | Multi-patient command share to CAD | Missing | — | MultiPatientService | P2 |
| 815 | Multi-patient command share to FIRE | Missing | — | MultiPatientService | P2 |
| 816 | Multi-patient command share to PD | Missing | — | MultiPatientService | P2 |
| 817 | Multi-patient command share to EM | Missing | — | MultiPatientService | P2 |
| 818 | Multi-patient incident commander signature | Missing | — | MultiPatientService | P2 |
| 819 | Multi-patient agency executive signature | Missing | — | MultiPatientService | P2 |
| 820 | Multi-patient state submission packet | Missing | — | MultiPatientService | P2 |
| 821 | Multi-patient national reporting packet | Missing | — | MultiPatientService | P2 |
| 822 | Multi-patient audit log | Missing | — | MultiPatientService | P2 |
| 823 | Multi-patient telemetry of usage | Missing | — | MultiPatientService | P2 |
| 824 | Multi-patient training mode | Missing | — | MultiPatientService | P2 |
| 825 | Multi-patient admin dashboard | Missing | — | MultiPatientService | P2 |

## Group K — Protocol (Features 826–940)
| # | Feature | Status | Existing path | Required service | Phase |
| --- | --- | --- | --- | --- | --- |
| 826 | Protocol library — agency-specific | Missing | — | ProtocolContextService | P2 |
| 827 | Protocol library — state-specific | Missing | — | ProtocolContextService | P2 |
| 828 | Protocol library — national/NAEMSP | Missing | — | ProtocolContextService | P2 |
| 829 | Protocol version pinning per chart | Missing | — | ProtocolContextService | P2 |
| 830 | Protocol effective date enforcement | Missing | — | ProtocolContextService | P2 |
| 831 | Protocol expiration warning | Missing | — | ProtocolContextService | P2 |
| 832 | Protocol search by name | Missing | — | ProtocolContextService | P2 |
| 833 | Protocol search by chief complaint | Missing | — | ProtocolContextService | P2 |
| 834 | Protocol search by impression | Missing | — | ProtocolContextService | P2 |
| 835 | Protocol search by code | Missing | — | ProtocolContextService | P2 |
| 836 | Protocol step-by-step renderer | Missing | — | ProtocolContextService | P2 |
| 837 | Protocol decision branches | Missing | — | ProtocolContextService | P2 |
| 838 | Protocol contraindication display | Missing | — | ProtocolContextService | P2 |
| 839 | Protocol drug dosing per weight | Missing | — | ProtocolContextService | P2 |
| 840 | Protocol drug dosing per age | Missing | — | ProtocolContextService | P2 |
| 841 | Protocol Broselow color crosswalk | Missing | — | ProtocolContextService | P2 |
| 842 | Protocol checkbox capture per step | Missing | — | ProtocolContextService | P2 |
| 843 | Protocol deviation capture | Missing | — | ProtocolContextService | P2 |
| 844 | Protocol deviation reason required | Missing | — | ProtocolContextService | P2 |
| 845 | Protocol medical control consult linkage | Missing | — | ProtocolContextService | P2 |
| 846 | Protocol activation trigger logging | Missing | — | ProtocolContextService | P2 |
| 847 | Protocol completion logging | Missing | — | ProtocolContextService | P2 |
| 848 | Protocol partial-completion logging | Missing | — | ProtocolContextService | P2 |
| 849 | Protocol audit trail per step | Missing | — | ProtocolContextService | P2 |
| 850 | Protocol provider override gate | Missing | — | ProtocolContextService | P2 |
| 851 | Protocol attached evidence per step | Missing | — | ProtocolContextService | P2 |
| 852 | Protocol attached vitals required | Missing | — | ProtocolContextService | P2 |
| 853 | Protocol attached ECG required | Missing | — | ProtocolContextService | P2 |
| 854 | Protocol attached SpO2 required | Missing | — | ProtocolContextService | P2 |
| 855 | Protocol attached glucose required | Missing | — | ProtocolContextService | P2 |
| 856 | Protocol attached pain reassessment | Missing | — | ProtocolContextService | P2 |
| 857 | Protocol — cardiac arrest adult | Missing | — | ProtocolContextService | P2 |
| 858 | Protocol — cardiac arrest pediatric | Missing | — | ProtocolContextService | P2 |
| 859 | Protocol — VF/pulseless VT | Missing | — | ProtocolContextService | P2 |
| 860 | Protocol — asystole/PEA | Missing | — | ProtocolContextService | P2 |
| 861 | Protocol — bradycardia | Missing | — | ProtocolContextService | P2 |
| 862 | Protocol — tachycardia stable | Missing | — | ProtocolContextService | P2 |
| 863 | Protocol — tachycardia unstable | Missing | — | ProtocolContextService | P2 |
| 864 | Protocol — chest pain/ACS | Missing | — | ProtocolContextService | P2 |
| 865 | Protocol — STEMI activation | Missing | — | ProtocolContextService | P2 |
| 866 | Protocol — CHF | Missing | — | ProtocolContextService | P2 |
| 867 | Protocol — stroke | Missing | — | ProtocolContextService | P2 |
| 868 | Protocol — seizure | Missing | — | ProtocolContextService | P2 |
| 869 | Protocol — altered mental status | Missing | — | ProtocolContextService | P2 |
| 870 | Protocol — syncope | Missing | — | ProtocolContextService | P2 |
| 871 | Protocol — hypoglycemia | Missing | — | ProtocolContextService | P2 |
| 872 | Protocol — hyperglycemia/DKA | Missing | — | ProtocolContextService | P2 |
| 873 | Protocol — respiratory distress | Missing | — | ProtocolContextService | P2 |
| 874 | Protocol — asthma/COPD | Missing | — | ProtocolContextService | P2 |
| 875 | Protocol — anaphylaxis | Missing | — | ProtocolContextService | P2 |
| 876 | Protocol — allergic reaction | Missing | — | ProtocolContextService | P2 |
| 877 | Protocol — sepsis | Missing | — | ProtocolContextService | P2 |
| 878 | Protocol — overdose opioid | Missing | — | ProtocolContextService | P2 |
| 879 | Protocol — overdose stimulant | Missing | — | ProtocolContextService | P2 |
| 880 | Protocol — overdose benzodiazepine | Missing | — | ProtocolContextService | P2 |
| 881 | Protocol — TCA overdose | Missing | — | ProtocolContextService | P2 |
| 882 | Protocol — poisoning unknown | Missing | — | ProtocolContextService | P2 |
| 883 | Protocol — carbon monoxide | Missing | — | ProtocolContextService | P2 |
| 884 | Protocol — burn thermal | Missing | — | ProtocolContextService | P2 |
| 885 | Protocol — burn chemical | Missing | — | ProtocolContextService | P2 |
| 886 | Protocol — burn electrical | Missing | — | ProtocolContextService | P2 |
| 887 | Protocol — trauma adult | Missing | — | ProtocolContextService | P2 |
| 888 | Protocol — trauma pediatric | Missing | — | ProtocolContextService | P2 |
| 889 | Protocol — TBI | Missing | — | ProtocolContextService | P2 |
| 890 | Protocol — spinal | Missing | — | ProtocolContextService | P2 |
| 891 | Protocol — extremity trauma | Missing | — | ProtocolContextService | P2 |
| 892 | Protocol — hemorrhage control | Missing | — | ProtocolContextService | P2 |
| 893 | Protocol — TXA administration | Missing | — | ProtocolContextService | P2 |
| 894 | Protocol — pain management adult | Missing | — | ProtocolContextService | P2 |
| 895 | Protocol — pain management pediatric | Missing | — | ProtocolContextService | P2 |
| 896 | Protocol — nausea/vomiting | Missing | — | ProtocolContextService | P2 |
| 897 | Protocol — agitation/sedation | Missing | — | ProtocolContextService | P2 |
| 898 | Protocol — restraint physical | Missing | — | ProtocolContextService | P2 |
| 899 | Protocol — restraint chemical | Missing | — | ProtocolContextService | P2 |
| 900 | Protocol — obstetric emergency | Missing | — | ProtocolContextService | P2 |
| 901 | Protocol — childbirth normal | Missing | — | ProtocolContextService | P2 |
| 902 | Protocol — childbirth complicated | Missing | — | ProtocolContextService | P2 |
| 903 | Protocol — neonatal resuscitation | Missing | — | ProtocolContextService | P2 |
| 904 | Protocol — pediatric fever | Missing | — | ProtocolContextService | P2 |
| 905 | Protocol — pediatric dehydration | Missing | — | ProtocolContextService | P2 |
| 906 | Protocol — pediatric respiratory | Missing | — | ProtocolContextService | P2 |
| 907 | Protocol — pediatric seizure | Missing | — | ProtocolContextService | P2 |
| 908 | Protocol — pediatric trauma | Missing | — | ProtocolContextService | P2 |
| 909 | Protocol — geriatric fall | Missing | — | ProtocolContextService | P2 |
| 910 | Protocol — geriatric polypharmacy | Missing | — | ProtocolContextService | P2 |
| 911 | Protocol — geriatric AMS | Missing | — | ProtocolContextService | P2 |
| 912 | Protocol — behavioral emergency | Missing | — | ProtocolContextService | P2 |
| 913 | Protocol — suicidal ideation | Missing | — | ProtocolContextService | P2 |
| 914 | Protocol — excited delirium | Missing | — | ProtocolContextService | P2 |
| 915 | Protocol — heat illness | Missing | — | ProtocolContextService | P2 |
| 916 | Protocol — hypothermia | Missing | — | ProtocolContextService | P2 |
| 917 | Protocol — drowning | Missing | — | ProtocolContextService | P2 |
| 918 | Protocol — electrocution | Missing | — | ProtocolContextService | P2 |
| 919 | Protocol — dive emergency | Missing | — | ProtocolContextService | P2 |
| 920 | Protocol — envenomation | Missing | — | ProtocolContextService | P2 |
| 921 | Protocol — radiation | Missing | — | ProtocolContextService | P2 |
| 922 | Protocol — hazmat | Missing | — | ProtocolContextService | P2 |
| 923 | Protocol — chempack/nerve agent | Missing | — | ProtocolContextService | P2 |
| 924 | Protocol — refusal/AMA | Missing | — | ProtocolContextService | P2 |
| 925 | Protocol — DNR/POLST | Missing | — | ProtocolContextService | P2 |
| 926 | Protocol — termination of resuscitation | Missing | — | ProtocolContextService | P2 |
| 927 | Protocol — interfacility transfer | Missing | — | ProtocolContextService | P2 |
| 928 | Protocol — vent management | Missing | — | ProtocolContextService | P2 |
| 929 | Protocol — drip management | Missing | — | ProtocolContextService | P2 |
| 930 | Protocol — blood product administration | Missing | — | ProtocolContextService | P2 |
| 931 | Protocol — ECMO transport | Missing | — | ProtocolContextService | P2 |
| 932 | Protocol — IABP transport | Missing | — | ProtocolContextService | P2 |
| 933 | Protocol — neonatal isolette transport | Missing | — | ProtocolContextService | P2 |
| 934 | Protocol — bariatric considerations | Missing | — | ProtocolContextService | P2 |
| 935 | Protocol — public health reporting trigger | Missing | — | ProtocolContextService | P2 |
| 936 | Protocol — quality measure tagging | Missing | — | ProtocolContextService | P2 |
| 937 | Protocol — research enrollment trigger | Missing | — | ProtocolContextService | P2 |
| 938 | Protocol — telemetry of adherence | Missing | — | ProtocolContextService | P2 |
| 939 | Protocol — telemetry of deviation | Missing | — | ProtocolContextService | P2 |
| 940 | Protocol — admin dashboard | Missing | — | ProtocolContextService | P2 |

## Group L — eCustom (Features 941–990)
| # | Feature | Status | Existing path | Required service | Phase |
| --- | --- | --- | --- | --- | --- |
| 941 | eCustom field definition CRUD | Missing | — | ECustomFieldService | P2 |
| 942 | eCustom field types — text | Missing | — | ECustomFieldService | P2 |
| 943 | eCustom field types — number | Missing | — | ECustomFieldService | P2 |
| 944 | eCustom field types — date/time | Missing | — | ECustomFieldService | P2 |
| 945 | eCustom field types — boolean | Missing | — | ECustomFieldService | P2 |
| 946 | eCustom field types — single-select | Missing | — | ECustomFieldService | P2 |
| 947 | eCustom field types — multi-select | Missing | — | ECustomFieldService | P2 |
| 948 | eCustom field types — long-text | Missing | — | ECustomFieldService | P2 |
| 949 | eCustom field types — file upload | Missing | — | ECustomFieldService | P2 |
| 950 | eCustom field types — signature | Missing | — | ECustomFieldService | P2 |
| 951 | eCustom field validators — required | Missing | — | ECustomFieldService | P2 |
| 952 | eCustom field validators — regex | Missing | — | ECustomFieldService | P2 |
| 953 | eCustom field validators — range | Missing | — | ECustomFieldService | P2 |
| 954 | eCustom field validators — list constraint | Missing | — | ECustomFieldService | P2 |
| 955 | eCustom field conditional display | Missing | — | ECustomFieldService | P2 |
| 956 | eCustom field cross-field dependency | Missing | — | ECustomFieldService | P2 |
| 957 | eCustom field per-agency scope | Missing | — | ECustomFieldService | P2 |
| 958 | eCustom field per-state scope | Missing | — | ECustomFieldService | P2 |
| 959 | eCustom field per-unit scope | Missing | — | ECustomFieldService | P2 |
| 960 | eCustom field per-protocol scope | Missing | — | ECustomFieldService | P2 |
| 961 | eCustom field per-chief-complaint scope | Missing | — | ECustomFieldService | P2 |
| 962 | eCustom field NEMSIS extension mapping | Missing | — | ECustomFieldService | P2 |
| 963 | eCustom field billing mapping | Missing | — | ECustomFieldService | P2 |
| 964 | eCustom field reporting export | Missing | — | ECustomFieldService | P2 |
| 965 | eCustom field BI dashboard tile | Missing | — | ECustomFieldService | P2 |
| 966 | eCustom field admin editor UI | Missing | — | ECustomFieldService | P2 |
| 967 | eCustom field admin preview | Missing | — | ECustomFieldService | P2 |
| 968 | eCustom field admin draft vs published | Missing | — | ECustomFieldService | P2 |
| 969 | eCustom field admin version history | Missing | — | ECustomFieldService | P2 |
| 970 | eCustom field admin rollback | Missing | — | ECustomFieldService | P2 |
| 971 | eCustom field admin diff | Missing | — | ECustomFieldService | P2 |
| 972 | eCustom field admin per-role permissions | Missing | — | ECustomFieldService | P2 |
| 973 | eCustom field admin import JSON | Missing | — | ECustomFieldService | P2 |
| 974 | eCustom field admin export JSON | Missing | — | ECustomFieldService | P2 |
| 975 | eCustom field admin clone agency template | Missing | — | ECustomFieldService | P2 |
| 976 | eCustom field admin marketplace template | Missing | — | ECustomFieldService | P2 |
| 977 | eCustom field admin audit log | Missing | — | ECustomFieldService | P2 |
| 978 | eCustom field admin deprecation flow | Missing | — | ECustomFieldService | P2 |
| 979 | eCustom field admin migration tool | Missing | — | ECustomFieldService | P2 |
| 980 | eCustom field admin performance budget | Missing | — | ECustomFieldService | P2 |
| 981 | eCustom field provider hint text | Missing | — | ECustomFieldService | P2 |
| 982 | eCustom field provider tooltip | Missing | — | ECustomFieldService | P2 |
| 983 | eCustom field provider help link | Missing | — | ECustomFieldService | P2 |
| 984 | eCustom field provider accessibility label | Missing | — | ECustomFieldService | P2 |
| 985 | eCustom field provider keyboard nav | Missing | — | ECustomFieldService | P2 |
| 986 | eCustom field provider mobile layout | Missing | — | ECustomFieldService | P2 |
| 987 | eCustom field provider offline support | Missing | — | ECustomFieldService | P2 |
| 988 | eCustom field provider conflict resolution | Missing | — | ECustomFieldService | P2 |
| 989 | eCustom field provider telemetry of usage | Missing | — | ECustomFieldService | P2 |
| 990 | eCustom field admin dashboard | Missing | — | ECustomFieldService | P2 |

## Summary
- Built: 247 / 990
- Partial: 22 / 990
- Missing: 721 / 990
- OUT OF SCOPE: 0 / 990 (TAC/CTA features intentionally excluded from this matrix per the no-touch rule)

## PR Map (P2 pillars → feature ranges)
PR-2 LockReadinessService → A-105, A-118, D-450..500
PR-3 ECustomFieldService → L-941..990
PR-4 SmartTextService → C-301..400
PR-5 SentenceEvidenceService → C-401..425
PR-6 RepeatPatientService → G-591..650
PR-7 PriorEcgService → H-651..700
PR-8 RxNormService → E-501..540
PR-9 Icd10Service → F-541..590
PR-10 MapboxLocationService → I-701..760
PR-11 MultiPatientService → J-761..825
PR-12 ProtocolContextService → K-826..940
PR-13 AuditTrail+ProviderOverride → A-118, audit features across groups

## P1 Shipped This Iteration
- 3D Physical Assessment module (18 region IDs, R3F, deterministic narrative) → Group B features 220..245
- Chart Dashboard (sidebar, sticky header, hero, quick actions, vitals strip, timeline, current assessment, medications, ECG snapshot honest-unavailable, alerts, footer, progress ring) → Group A features 1..50
- EpcrUnavailableState + EpcrEvidenceFrame primitives → cross-cutting

## Truth Rules Enforced
- No Tac/CTA testing surfaces touched (TacExaminerDashboard.tsx, api_nemsis_scenarios.py, api_nemsis_packs.py, api_nemsis_submissions.py)
- BodyAssessmentMap.tsx (2D) preserved for export/print
- Capability flags binary: live ⇔ Five-Artifact Rule satisfied on same SHA
- AI evidence-linked (no auto-diagnosis, no STEMI detection, no ICD-10 auto-assignment)
- Repeat-patient + prior-ECG require provider confirmation
- No fake/stub anywhere (test infra included)
