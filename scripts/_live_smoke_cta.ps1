param([string]$Token = $env:ADX_TOKEN)
$ErrorActionPreference = 'Continue'
$H = @{ Authorization = "Bearer $Token"; 'Content-Type' = 'application/json' }
$base = 'https://app.adaptixcore.com/api/v1/epcr/internal/cta-testing'

function Invoke-Adx($method, $url, $body) {
    try {
        if ($body) {
            $r = Invoke-WebRequest -Uri $url -Method $method -Headers $H -Body $body -TimeoutSec 90 -UseBasicParsing -ErrorAction Stop
        } else {
            $r = Invoke-WebRequest -Uri $url -Method $method -Headers $H -TimeoutSec 90 -UseBasicParsing -ErrorAction Stop
        }
        return @{ ok = $true; status = $r.StatusCode; body = $r.Content }
    } catch {
        $code = $null; $bd = ''
        try { $code = $_.Exception.Response.StatusCode.value__ } catch {}
        try { $sr = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream()); $bd = $sr.ReadToEnd() } catch {}
        return @{ ok = $false; status = $code; body = $bd }
    }
}

Write-Host "=== STEP 1: list test cases ==="
$rTC = Invoke-Adx 'GET' "$base/test-cases" $null
Write-Host "  status=$($rTC.status)"
$jTC = $rTC.body | ConvertFrom-Json
Write-Host "  cases=$($jTC.test_cases.Count) nemsis=$($jTC.nemsis_version) asset=$($jTC.nemsis_asset_version)"

$cases = @('2025-DEM1','2025-EMS 1-Allergy','2025-EMS 2-Heat Stroke','2025-EMS 3-Pediatric Asthma','2025-EMS 4-Arm Trauma','2025-EMS 5-Mental Health Crisis')
$runs = @()
Write-Host "=== STEP 2-7: validation-runs (fixture_xml) for all 6 cases ==="
foreach ($tc in $cases) {
    $body = @{ test_case_id = $tc; mode = 'fixture_xml'; use_deployed_assets = $true } | ConvertTo-Json -Compress
    $r = Invoke-Adx 'POST' "$base/validation-runs" $body
    if ($r.ok) {
        $j = $r.body | ConvertFrom-Json
        $runs += [pscustomobject]@{ tc = $tc; run_id = $j.validation_run_id; status = $r.status; xsd = $j.xsd_valid; sch = $j.schematron_valid; skip = $j.validation_skipped; asset = $j.validator_asset_version; nemsis = $j.nemsis_version; ms = $j.execution_ms; blk = $j.blocking_reason; xsd_err = $j.xsd_errors.Count; sch_err = $j.schematron_errors.Count; sch_warn = $j.schematron_warnings.Count }
    } else {
        $runs += [pscustomobject]@{ tc = $tc; run_id = ''; status = $r.status; xsd = ''; sch = ''; skip = ''; asset = ''; nemsis = ''; ms = ''; blk = $r.body.Substring(0,[Math]::Min(160,$r.body.Length)); xsd_err = ''; sch_err = ''; sch_warn = '' }
    }
}
$runs | Format-Table tc, status, xsd, sch, skip, asset, nemsis, ms, xsd_err, sch_err, sch_warn -AutoSize | Out-String -Width 240 | Write-Host

# Use the first successful run for downstream steps
$picked = $runs | Where-Object { $_.run_id } | Select-Object -First 1
if (-not $picked) { Write-Host 'NO SUCCESSFUL RUN; aborting'; exit 1 }
$runId = $picked.run_id
Write-Host "PICKED_RUN=$runId  case=$($picked.tc)"

Write-Host "=== STEP 8: GET validation-run by id ==="
$rGet = Invoke-Adx 'GET' "$base/validation-runs/$runId" $null
Write-Host "  status=$($rGet.status)"
$pre = ($rGet.body | ConvertFrom-Json)

Write-Host "=== STEP 9: POST ai-review ==="
$rAI = Invoke-Adx 'POST' "$base/validation-runs/$runId/ai-review" '{}'
Write-Host "  status=$($rAI.status)"
$ai = $rAI.body | ConvertFrom-Json
Write-Host "  ai_status=$($ai.status) provider=$($ai.provider)"
Write-Host "  summary=$($ai.summary)"

Write-Host "=== STEP 10: re-fetch run; verify Bedrock did NOT mutate verdicts ==="
$rGet2 = Invoke-Adx 'GET' "$base/validation-runs/$runId" $null
$post = $rGet2.body | ConvertFrom-Json
$mutated = ($pre.xsd_valid -ne $post.xsd_valid) -or ($pre.schematron_valid -ne $post.schematron_valid)
Write-Host "  pre  xsd=$($pre.xsd_valid) sch=$($pre.schematron_valid)"
Write-Host "  post xsd=$($post.xsd_valid) sch=$($post.schematron_valid)"
Write-Host "  MUTATED=$mutated  (must be False)"

Write-Host "=== STEP 11: evidence packet ==="
$bodyEP = @{ validation_run_id = $runId; include_ai_review = $true } | ConvertTo-Json -Compress
$rEP = Invoke-Adx 'POST' "$base/evidence-packets" $bodyEP
Write-Host "  status=$($rEP.status)"
if ($rEP.ok) {
    $ep = $rEP.body | ConvertFrom-Json
    Write-Host "  packet_id=$($ep.evidence_packet_id)"
    Write-Host "  nemsis=$($ep.nemsis_version) asset=$($ep.asset_version) registry_version=$($ep.registry_version) source_commit=$($ep.source_commit)"
    Write-Host "  resubmission_ready=$($ep.resubmission_ready) xsd=$($ep.xsd_valid) sch=$($ep.schematron_valid) blocking=$($ep.blocking_reason)"
    Write-Host "  bedrock_summary=$($ep.bedrock_summary)"
} else { Write-Host "  body=$($rEP.body.Substring(0,[Math]::Min(300,$rEP.body.Length)))" }

Write-Host "=== STEP 12: tenant isolation - cross-tenant lookup must NOT succeed ==="
# Use a random UUID — no token from another tenant available; verify 404 on garbage id.
$rNF = Invoke-Adx 'GET' "$base/validation-runs/00000000-0000-0000-0000-000000000000" $null
Write-Host "  garbage_id_status=$($rNF.status)  (must be 404)"

Write-Host "=== STEP 13: anonymous request must be 401 ==="
try { $r = Invoke-WebRequest -Uri "$base/test-cases" -TimeoutSec 15 -UseBasicParsing -ErrorAction Stop; Write-Host "  status=$($r.StatusCode)  UNEXPECTED" } catch { Write-Host "  status=$($_.Exception.Response.StatusCode.value__)  (expected 401)" }

Write-Host "=== STEP 14: invalid mode rejected ==="
$rBad = Invoke-Adx 'POST' "$base/validation-runs" '{"test_case_id":"2025-DEM1","mode":"bogus_mode"}'
Write-Host "  status=$($rBad.status)  (expected 422)"

Write-Host "=== STEP 15: chart_id required for generated_chart_xml ==="
$rNoChart = Invoke-Adx 'POST' "$base/validation-runs" '{"test_case_id":"2025-DEM1","mode":"generated_chart_xml"}'
Write-Host "  status=$($rNoChart.status)  (expected 400 or 422)"

Write-Host "=== STEP 16: unsupported test_case_id rejected ==="
$rBadTC = Invoke-Adx 'POST' "$base/validation-runs" '{"test_case_id":"not-a-real-case","mode":"fixture_xml"}'
Write-Host "  status=$($rBadTC.status)  (expected 400 or 404)"

Write-Host "=== STEP 17: list 6 cases asserts fixture_available all true ==="
$allFixtures = ($jTC.test_cases | Where-Object { -not $_.fixture_available }).Count
Write-Host "  cases_missing_fixture=$allFixtures  (must be 0)"

Write-Host "=== STEP 18: NEMSIS contract metadata invariants ==="
Write-Host "  test_cases_count=$($jTC.test_cases.Count)  (must be 6)"
Write-Host "  nemsis_version=$($jTC.nemsis_version)  (must be 3.5.1)"
Write-Host "  asset_version=$($jTC.nemsis_asset_version)  (must be 3.5.1.250403CP1)"

Write-Host "=== STEP 19: XSD verdict authority (validator owns xsd_valid) ==="
$auth_ok = ($post.xsd_valid -is [bool]) -and ($post.schematron_valid -is [bool])
Write-Host "  verdict_types_bool=$auth_ok"

Write-Host "=== STEP 20: validator_asset_version present and matches contract ==="
Write-Host "  run.validator_asset_version=$($post.validator_asset_version)  (expected 3.5.1.250403CP1 if XSD assets deployed)"

Write-Host "=== STEP 21: AI review returns advisory only, never alters verdicts ==="
Write-Host "  ai.status=$($ai.status)  ai.provider=$($ai.provider)  mutated=$mutated  (must be False)"

Write-Host "=== STEP 22: evidence packet carries registry baseline ==="
if ($rEP.ok) {
    Write-Host "  registry_version=$($ep.registry_version)  source_commit=$($ep.source_commit)"
} else { Write-Host "  evidence packet step failed earlier" }

Write-Host "=== STEP 23: full run summary table ==="
$runs | Format-Table tc, status, xsd, sch, skip, xsd_err, sch_err, sch_warn -AutoSize | Out-String -Width 220 | Write-Host

Write-Host "=== DONE ==="
