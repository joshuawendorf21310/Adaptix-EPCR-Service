$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$runtime = Join-Path $repoRoot ".github\scripts\agent_governance_runtime.py"
$configPath = Join-Path $repoRoot ".github\hooks\agent-governance.json"

if (-not (Test-Path $python)) {
    $python = "python"
}

$emptyIn = Join-Path $env:TEMP "adaptix-hook-empty-stdin.json"
$stderrEmpty = Join-Path $env:TEMP "adaptix-hook-empty-stderr.txt"
$stderrValid = Join-Path $env:TEMP "adaptix-hook-valid-stderr.txt"
$stderrInvalid = Join-Path $env:TEMP "adaptix-hook-invalid-stderr.txt"
Set-Content -Path $emptyIn -Value "" -NoNewline
Remove-Item $stderrEmpty, $stderrValid, $stderrInvalid -ErrorAction SilentlyContinue

$emptyOut = Get-Content -Path $emptyIn -Raw | & $python $runtime 2> $stderrEmpty
$emptyExit = $LASTEXITCODE
$validOut = '{"hookEventName":"SessionStart","prompt":"build fullstack"}' | & $python $runtime 2> $stderrValid
$validExit = $LASTEXITCODE
$invalidOut = '{invalid json' | & $python $runtime 2> $stderrInvalid
$invalidExit = $LASTEXITCODE

$emptyJson = $emptyOut | ConvertFrom-Json
$validJson = $validOut | ConvertFrom-Json
$invalidJson = $invalidOut | ConvertFrom-Json
$config = Get-Content $configPath -Raw | ConvertFrom-Json
$expectedHooks = @("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PreCompact", "TaskComplete")
$hookNames = @($config.hooks.PSObject.Properties.Name)
$hookFiles = @(Get-ChildItem (Join-Path $repoRoot ".github\hooks") -Filter "*.json")
$hookContent = ($hookFiles | ForEach-Object { Get-Content $_.FullName -Raw }) -join "`n"

$hookChecks = foreach ($hookName in $expectedHooks) {
    $entry = $config.hooks.$hookName[0]
    [PSCustomObject]@{
        Hook = $hookName
        Exists = $hookNames -contains $hookName
        PointsToRuntime = $entry.windows -eq "python .github\scripts\agent_governance_runtime.py"
        Timeout15 = $entry.timeout -eq 15
        TypeCommand = $entry.type -eq "command"
        HasLinux = $entry.PSObject.Properties.Name -contains "linux"
        HasOsx = $entry.PSObject.Properties.Name -contains "osx"
    }
}

$summary = [PSCustomObject]@{
    EmptyExit0 = $emptyExit -eq 0
    ValidExit0 = $validExit -eq 0
    InvalidExit0 = $invalidExit -eq 0
    EmptyJsonOnly = $null -ne $emptyJson.cancel -and $null -ne $emptyJson.contextModification -and $null -ne $emptyJson.errorMessage
    ValidJsonOnly = $null -ne $validJson.cancel -and $validJson.contextModification.Contains("SESSIONSTART HOOK DIRECTIVE") -and $null -ne $validJson.errorMessage
    InvalidJsonOnly = $null -ne $invalidJson.cancel -and $invalidJson.errorMessage.Contains("Invalid JSON input")
    EmptyNoStderr = (Get-Item $stderrEmpty).Length -eq 0
    ValidNoStderr = (Get-Item $stderrValid).Length -eq 0
    InvalidNoStderr = (Get-Item $stderrInvalid).Length -eq 0
    ConfigValidJson = $null -ne $config.hooks
    HooksExactlyExpected = -not [bool](Compare-Object $expectedHooks $hookNames)
    NoLinuxCommands = $hookContent -notmatch '"linux"'
    NoOsxCommands = $hookContent -notmatch '"osx"'
    NoStopHook = $hookContent -notmatch '"Stop"'
    HookFileCount = $hookFiles.Count
    HookChecks = $hookChecks
}

$summary | ConvertTo-Json -Compress -Depth 4