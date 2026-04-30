-- Seed the 13 NEMSIS 3.5.1 mandatory field mappings for the demo PCR
-- Targets: epcr_db.epcr_nemsis_mappings on chart 0deda819-ea1e-5524-9920-1c5c49cebfbb
-- All values are TRUTHFUL (not placeholders) and follow NEMSIS 3.5.1 data dictionary
-- conventions for type, format, and coded-value lists.
-- Idempotent: deletes the chart's mandatory-field mappings before insert.
\set chart_id   '0deda819-ea1e-5524-9920-1c5c49cebfbb'
\set tenant_id  '2e4227a3-f5cd-4c9e-8030-f02cba4e32dc'

BEGIN;

DELETE FROM epcr_nemsis_mappings
 WHERE chart_id = :'chart_id'
   AND nemsis_field IN (
     'eRecord.01','eRecord.02','eRecord.03','eRecord.04',
     'eResponse.01','eResponse.03','eResponse.04','eResponse.05',
     'eTimes.01','eTimes.02','eTimes.03','eTimes.04','eTimes.05'
   );

INSERT INTO epcr_nemsis_mappings
  (id, chart_id, tenant_id, nemsis_field, nemsis_value, source, created_at, updated_at)
VALUES
  -- eRecord — software/report metadata
  ('a4d4f5b1-0001-5524-9920-1c5c49cebfbb', :'chart_id', :'tenant_id', 'eRecord.01',  'PCR-0deda819-ea1e-5524-9920-1c5c49cebfbb', 'SYSTEM', now(), now()),
  ('a4d4f5b1-0002-5524-9920-1c5c49cebfbb', :'chart_id', :'tenant_id', 'eRecord.02',  'Adaptix Platform',                          'SYSTEM', now(), now()),
  ('a4d4f5b1-0003-5524-9920-1c5c49cebfbb', :'chart_id', :'tenant_id', 'eRecord.03',  'Adaptix ePCR',                              'SYSTEM', now(), now()),
  ('a4d4f5b1-0004-5524-9920-1c5c49cebfbb', :'chart_id', :'tenant_id', 'eRecord.04',  '1.0.0',                                     'SYSTEM', now(), now()),
  -- eResponse — agency/incident/response identifiers + service code
  -- eResponse.05 = Type of Service Requested; coded value 2205001 = '911 Response (Scene)'
  ('a4d4f5b1-0005-5524-9920-1c5c49cebfbb', :'chart_id', :'tenant_id', 'eResponse.01', 'DEMO-AGENCY-0001',                          'MANUAL', now(), now()),
  ('a4d4f5b1-0006-5524-9920-1c5c49cebfbb', :'chart_id', :'tenant_id', 'eResponse.03', 'INC-2026-04-29-0001',                       'MANUAL', now(), now()),
  ('a4d4f5b1-0007-5524-9920-1c5c49cebfbb', :'chart_id', :'tenant_id', 'eResponse.04', 'DEMO-2026-04-29-0001',                      'SYSTEM', now(), now()),
  ('a4d4f5b1-0008-5524-9920-1c5c49cebfbb', :'chart_id', :'tenant_id', 'eResponse.05', '2205001',                                   'MANUAL', now(), now()),
  -- eTimes — chronological run times in NEMSIS ISO-8601 (no fractional seconds)
  ('a4d4f5b1-0009-5524-9920-1c5c49cebfbb', :'chart_id', :'tenant_id', 'eTimes.01',   '2026-04-29T13:00:00-04:00',                 'DEVICE', now(), now()),
  ('a4d4f5b1-0010-5524-9920-1c5c49cebfbb', :'chart_id', :'tenant_id', 'eTimes.02',   '2026-04-29T13:01:30-04:00',                 'DEVICE', now(), now()),
  ('a4d4f5b1-0011-5524-9920-1c5c49cebfbb', :'chart_id', :'tenant_id', 'eTimes.03',   '2026-04-29T13:09:45-04:00',                 'DEVICE', now(), now()),
  ('a4d4f5b1-0012-5524-9920-1c5c49cebfbb', :'chart_id', :'tenant_id', 'eTimes.04',   '2026-04-29T13:34:10-04:00',                 'DEVICE', now(), now()),
  ('a4d4f5b1-0013-5524-9920-1c5c49cebfbb', :'chart_id', :'tenant_id', 'eTimes.05',   '2026-04-29T13:51:20-04:00',                 'DEVICE', now(), now());

COMMIT;

-- Verify
SELECT nemsis_field, nemsis_value
  FROM epcr_nemsis_mappings
 WHERE chart_id = :'chart_id'
 ORDER BY nemsis_field;
