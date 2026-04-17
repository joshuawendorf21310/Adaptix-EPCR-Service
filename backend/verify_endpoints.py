"""Live endpoint verification for NEMSIS pipeline routes."""
import asyncio
import sys
sys.path.insert(0, '.')
sys.path.insert(0, 'c:\\Users\\fusio\\Desktop\\FusionEMS-Core\\adaptix-platform\\adaptix-platform\\contracts')

from httpx import AsyncClient, ASGITransport
from epcr_app.main import app
from epcr_app.db import init_db

TENANT = 'test-tenant-001'
USER = 'test-user-001'

results = []

def chk(label, code, expected, extra=''):
    status = 'PASS' if code == expected else 'FAIL'
    results.append((status, label, code, expected, extra))
    print(f'{status}  {label:<55} HTTP {code}  {extra}')


async def run():
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://test') as c:
        h = {'X-Tenant-ID': TENANT}
        hw = {'X-Tenant-ID': TENANT, 'X-User-ID': USER}

        # Scenarios list
        r = await c.get('/api/v1/epcr/nemsis/scenarios/', headers=h)
        chk('GET /nemsis/scenarios/', r.status_code, 200, f'count={len(r.json())}')

        # Scenario detail
        r = await c.get('/api/v1/epcr/nemsis/scenarios/2026_DEM_1', headers=h)
        d = r.json()
        chk('GET /nemsis/scenarios/2026_DEM_1', r.status_code, 200, f'title={str(d.get("title",""))[:30]}')

        # Scenario 404
        r = await c.get('/api/v1/epcr/nemsis/scenarios/NONEXISTENT', headers=h)
        chk('GET /nemsis/scenarios/NONEXISTENT (404)', r.status_code, 404)

        # Generate XML
        r = await c.post('/api/v1/epcr/nemsis/scenarios/2026_EMS_1/generate', headers=h)
        d = r.json()
        chk('POST /nemsis/scenarios/2026_EMS_1/generate', r.status_code, 200, f'xml_size={d.get("xml_size_bytes","?")}')

        # Validate scenario
        r = await c.post('/api/v1/epcr/nemsis/scenarios/2026_EMS_2/validate', headers=h)
        d = r.json()
        chk('POST /nemsis/scenarios/2026_EMS_2/validate', r.status_code, 200, f'valid={d.get("valid","?")} skipped={d.get("validation_skipped","?")}')

        # Submit scenario (no TAC creds - will show pending)
        r = await c.post('/api/v1/epcr/nemsis/scenarios/2026_EMS_3/submit', headers=hw)
        d = r.json()
        chk('POST /nemsis/scenarios/2026_EMS_3/submit', r.status_code, 200, f'sub_status={d.get("submission_status","?")} soap={d.get("soap_result",{}).get("submitted","?")}')
        scenario_sub_id = d.get('submission_id', '')

        # Evidence
        r = await c.get('/api/v1/epcr/nemsis/scenarios/2026_EMS_3/evidence', headers=h)
        d = r.json()
        chk('GET /nemsis/scenarios/2026_EMS_3/evidence', r.status_code, 200, f'status={d.get("status","?")}')

        # Pack list
        r = await c.get('/api/v1/epcr/nemsis/packs/', headers=h)
        chk('GET /nemsis/packs/', r.status_code, 200, f'count={len(r.json())}')

        # Create pack
        r = await c.post('/api/v1/epcr/nemsis/packs/', headers=hw, json={'name': 'Test Pack', 'pack_type': 'national_xsd', 'nemsis_version': '3.5.1'})
        d = r.json()
        pack_id = d.get('id', '')
        chk('POST /nemsis/packs/', r.status_code, 201, f'pack_id={pack_id[:8] if pack_id else "ERR"} status={d.get("status","?")}')

        # Get pack
        if pack_id:
            r = await c.get(f'/api/v1/epcr/nemsis/packs/{pack_id}', headers=h)
            chk('GET /nemsis/packs/{pack_id}', r.status_code, 200, f'pack_type={r.json().get("pack_type","?")}')

        # Pack completeness
        if pack_id:
            r = await c.get(f'/api/v1/epcr/nemsis/packs/{pack_id}/completeness', headers=h)
            d = r.json()
            chk('GET /nemsis/packs/{pack_id}/completeness', r.status_code, 200, f'complete={d.get("is_complete","?")} missing={d.get("missing_roles",[])}')

        # Stage pack
        if pack_id:
            r = await c.post(f'/api/v1/epcr/nemsis/packs/{pack_id}/stage', headers=hw)
            chk('POST /nemsis/packs/{pack_id}/stage', r.status_code, 200, f'status={r.json().get("status","?")}')

        # Activate pack (no files - should fail with 400)
        if pack_id:
            r = await c.post(f'/api/v1/epcr/nemsis/packs/{pack_id}/activate', headers=hw)
            chk('POST /nemsis/packs/{pack_id}/activate (no files -> 400)', r.status_code, 400, f'detail={str(r.json().get("detail",""))[:40]}')

        # Archive pack
        if pack_id:
            r = await c.post(f'/api/v1/epcr/nemsis/packs/{pack_id}/archive', headers=hw)
            chk('POST /nemsis/packs/{pack_id}/archive', r.status_code, 200, f'status={r.json().get("status","?")}')

        # Pack files list
        if pack_id:
            r = await c.get(f'/api/v1/epcr/nemsis/packs/{pack_id}/files', headers=h)
            chk('GET /nemsis/packs/{pack_id}/files', r.status_code, 200, f'count={len(r.json())}')

        # Submissions list
        r = await c.get('/api/v1/epcr/nemsis/submissions/', headers=h)
        chk('GET /nemsis/submissions/', r.status_code, 200, f'count={len(r.json())}')

        # Create submission — returns 201
        r = await c.post('/api/v1/epcr/nemsis/submissions/', headers=hw, json={'chart_id': 'DEM1-CHART-0001'})
        d = r.json()
        sub_id = d.get('id', '')
        # Without SOAP configured, status will be "pending"
        chk('POST /nemsis/submissions/', r.status_code, 201, f'sub_id={sub_id[:8] if sub_id else "ERR"} status={d.get("submission_status","?")} soap={d.get("soap_result",{}).get("submitted","?")}')

        # Get submission
        if sub_id:
            r = await c.get(f'/api/v1/epcr/nemsis/submissions/{sub_id}', headers=h)
            chk('GET /nemsis/submissions/{sub_id}', r.status_code, 200, f'status={r.json().get("submission_status","?")}')

        # Submission history
        if sub_id:
            r = await c.get(f'/api/v1/epcr/nemsis/submissions/{sub_id}/history', headers=h)
            history = r.json()
            chk('GET /nemsis/submissions/{sub_id}/history', r.status_code, 200, f'rows={len(history)}')

        # Acknowledge pending -> 422 (correct state machine; submitted required first)
        if sub_id:
            r = await c.post(f'/api/v1/epcr/nemsis/submissions/{sub_id}/acknowledge', headers=hw, json={'note': 'ACK'})
            chk('POST /nemsis/submissions/{sub_id}/acknowledge (pending->422)', r.status_code, 422, f'detail={str(r.json().get("detail",""))[:50]}')

        # Retry pending submission (no SOAP -> stays pending, returns 200 with soap_result)
        if sub_id:
            r = await c.post(f'/api/v1/epcr/nemsis/submissions/{sub_id}/retry', headers=hw)
            d = r.json()
            chk('POST /nemsis/submissions/{sub_id}/retry (pending->SOAP unavail)', r.status_code, 200, f'status={d.get("submission_status","?")}')

        # Accept pending -> 422 (correct state machine)
        if sub_id:
            r = await c.post(f'/api/v1/epcr/nemsis/submissions/{sub_id}/accept', headers=hw, json={'note': 'Accepted'})
            chk('POST /nemsis/submissions/{sub_id}/accept (pending->422)', r.status_code, 422, f'detail={str(r.json().get("detail",""))[:50]}')

        # Second submission for reject path — also stays pending
        r = await c.post('/api/v1/epcr/nemsis/submissions/', headers=hw, json={'chart_id': 'EMS1-CHART-0001'})
        d = r.json()
        sub_id2 = d.get('id', '')
        chk('POST /nemsis/submissions/ (2nd)', r.status_code, 201, f'status={d.get("submission_status","?")}')

        # Reject pending -> 422 (correct: only submitted/acknowledged can be rejected)
        if sub_id2:
            r = await c.post(f'/api/v1/epcr/nemsis/submissions/{sub_id2}/reject', headers=hw, json={'rejection_reason': 'Missing required element'})
            chk('POST /nemsis/submissions/{sub_id}/reject (pending->422)', r.status_code, 422, f'detail={str(r.json().get("detail",""))[:50]}')

        # Retry sub_id2 (still pending) -> 200 with SOAP skip error
        if sub_id2:
            r = await c.post(f'/api/v1/epcr/nemsis/submissions/{sub_id2}/retry', headers=hw)
            d = r.json()
            chk('POST /nemsis/submissions/{sub_id}/retry (pending -> SOAP unavail)', r.status_code, 200, f'status={d.get("submission_status","?")} soap={d.get("soap_result",{}).get("submitted","?")}')

        # Validate route (missing chart -> 404)
        r = await c.post('/api/v1/epcr/nemsis/validate', params={'chart_id': 'no-chart'}, headers=h)
        chk('POST /nemsis/validate (no chart -> 404)', r.status_code, 404)

        # Readiness (missing chart -> 404)
        r = await c.get('/api/v1/epcr/nemsis/readiness', params={'chart_id': 'no-chart'}, headers=h)
        chk('GET /nemsis/readiness (no chart -> 404)', r.status_code, 404)

        # Mapping summary (missing chart -> 404)
        r = await c.get('/api/v1/epcr/nemsis/mapping-summary', params={'chart_id': 'no-chart'}, headers=h)
        chk('GET /nemsis/mapping-summary (no chart -> 404)', r.status_code, 404)

        # Export preview (missing chart -> 404)
        r = await c.get('/api/v1/epcr/nemsis/export-preview', params={'chart_id': 'no-chart'}, headers=h)
        chk('GET /nemsis/export-preview (no chart -> 404)', r.status_code, 404)

        # Missing X-Tenant-ID
        r = await c.get('/api/v1/epcr/nemsis/packs/')
        chk('GET /nemsis/packs/ (no tenant -> 400)', r.status_code, 400)

    # Summary
    passed = sum(1 for s,*_ in results if s == 'PASS')
    failed = sum(1 for s,*_ in results if s == 'FAIL')
    print(f'\n--- SUMMARY: {passed} PASS / {failed} FAIL / {len(results)} TOTAL ---')
    if failed > 0:
        print('FAILURES:')
        for s, label, code, exp, extra in results:
            if s == 'FAIL':
                print(f'  FAIL  {label}  got={code}  expected={exp}  {extra}')

asyncio.run(run())
