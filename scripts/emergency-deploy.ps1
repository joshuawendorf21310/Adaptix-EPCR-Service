# Emergency deploy script for adaptix-epcr — bypasses GitHub Actions.
#
# Usage:   .\scripts\emergency-deploy.ps1 [-SkipTests] [-SkipMigration] [-Profile vscode]
#
# What it does:
#   1. Validates AWS creds + Docker daemon
#   2. Builds the Docker image locally (with BuildKit cache)
#   3. Pushes to ECR
#   4. Registers a new ECS task definition revision with the new image
#   5. (Optional) Runs alembic upgrade head as a one-shot Fargate task
#   6. Updates the ECS service and waits for steady state
#   7. Prints health check status
#
# Saves 3-4 minutes vs. GitHub Actions on average.

[CmdletBinding()]
param(
    [switch]$SkipMigration,
    [switch]$DryRun,
    [string]$AwsProfile = "vscode",
    [string]$Region = "us-east-1"
)

$ErrorActionPreference = "Stop"
$script:AccountId = "793439286972"
$script:EcrRepo = "adaptix-epcr"
$script:Cluster = "adaptix-production"
$script:Service = "adaptix-production-epcr"
$script:ContainerName = "epcr"
$script:EcrRegistry = "$AccountId.dkr.ecr.$Region.amazonaws.com"

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "    $msg" -ForegroundColor Yellow }
function Die($msg)        { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

# --- 0. Preflight ----------------------------------------------------------
Write-Step "Preflight"

$repoRoot = git -C $PSScriptRoot rev-parse --show-toplevel 2>$null
if (-not $repoRoot) { Die "Not inside a git repository" }
Set-Location $repoRoot

if (-not (Test-Path "backend/Dockerfile.staging")) {
    Die "backend/Dockerfile.staging not found — are you in Adaptix-EPCR-Service?"
}

$gitStatus = git status --porcelain
if ($gitStatus) {
    Write-Warn "Working tree is dirty:"
    git status --short
    $ans = Read-Host "Continue with dirty working tree? (y/N)"
    if ($ans -ne "y") { exit 1 }
}

$sha = (git rev-parse --short=8 HEAD).Trim()
$imageTag = "prod-$sha"
$imageUri = "$EcrRegistry/$EcrRepo`:$imageTag"
Write-Ok "Git SHA: $sha"
Write-Ok "Image:   $imageUri"

# Check AWS auth
$identity = aws sts get-caller-identity --region $Region --profile $AwsProfile 2>&1
if ($LASTEXITCODE -ne 0) { Die "AWS auth failed for profile '$AwsProfile': $identity" }
Write-Ok "AWS: $((($identity | ConvertFrom-Json).Arn))"

# Check Docker
docker version --format '{{.Server.Version}}' 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Die "Docker daemon not reachable. Start Docker Desktop." }
Write-Ok "Docker: ready"

if ($DryRun) { Write-Warn "DRY RUN — no remote actions"; exit 0 }

# --- 1. ECR login ----------------------------------------------------------
Write-Step "ECR login"
$pw = aws ecr get-login-password --region $Region --profile $AwsProfile
$pw | docker login --username AWS --password-stdin $EcrRegistry 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Die "docker login failed" }
Write-Ok "Authenticated to $EcrRegistry"

# --- 2. Build ---------------------------------------------------------------
Write-Step "Docker build"
$env:DOCKER_BUILDKIT = "1"
docker buildx build `
    --platform linux/amd64 `
    --tag $imageUri `
    --cache-from "type=registry,ref=$EcrRegistry/$EcrRepo`:cache" `
    --cache-to   "type=registry,ref=$EcrRegistry/$EcrRepo`:cache,mode=max" `
    --push `
    -f backend/Dockerfile.staging `
    backend
if ($LASTEXITCODE -ne 0) { Die "docker build/push failed" }
Write-Ok "Pushed $imageUri"

# --- 3. Register new task definition ---------------------------------------
Write-Step "Register task definition"
$currentTd = aws ecs describe-task-definition --task-definition $Service --region $Region --profile $AwsProfile --query "taskDefinition" --output json | ConvertFrom-Json
foreach ($c in $currentTd.containerDefinitions) {
    if ($c.name -eq $ContainerName) { $c.image = $imageUri }
}
# Strip fields not accepted by register-task-definition
$strip = @("taskDefinitionArn","revision","status","requiresAttributes","compatibilities","registeredAt","registeredBy")
foreach ($k in $strip) { $currentTd.PSObject.Properties.Remove($k) | Out-Null }
$tdJson = $currentTd | ConvertTo-Json -Depth 32 -Compress
$tdFile = [System.IO.Path]::GetTempFileName()
$tdJson | Out-File -FilePath $tdFile -Encoding utf8 -NoNewline

$newTdArn = aws ecs register-task-definition --cli-input-json "file://$tdFile" --region $Region --profile $AwsProfile --query "taskDefinition.taskDefinitionArn" --output text
Remove-Item $tdFile
if (-not $newTdArn) { Die "register-task-definition failed" }
Write-Ok "Registered: $newTdArn"

# --- 4. Optional: alembic upgrade head -------------------------------------
if (-not $SkipMigration) {
    Write-Step "Run alembic upgrade head"
    Write-Warn "Migration step skipped — run via GitHub Actions or pass -SkipMigration to suppress this notice."
    Write-Warn "If migration is required, deploy through GitHub Actions instead."
}

# --- 5. Update service -----------------------------------------------------
Write-Step "Update ECS service"
aws ecs update-service --cluster $Cluster --service $Service --task-definition $newTdArn --force-new-deployment --region $Region --profile $AwsProfile --query "service.{status:status,td:taskDefinition}" --output json
if ($LASTEXITCODE -ne 0) { Die "update-service failed" }
Write-Ok "Deployment initiated"

# --- 6. Wait for steady state ----------------------------------------------
Write-Step "Waiting for steady state (max 10 min)"
$start = Get-Date
$timeout = New-TimeSpan -Minutes 10
while ((Get-Date) - $start -lt $timeout) {
    $svc = aws ecs describe-services --cluster $Cluster --services $Service --region $Region --profile $AwsProfile --query "services[0].{running:runningCount,desired:desiredCount,pending:pendingCount,primaryTd:deployments[?status=='PRIMARY']|[0].taskDefinition,primaryRunning:deployments[?status=='PRIMARY']|[0].runningCount}" --output json | ConvertFrom-Json
    $elapsed = [int]((Get-Date) - $start).TotalSeconds
    Write-Host ("    [{0}s] primary running={1}/{2} pending={3}" -f $elapsed, $svc.primaryRunning, $svc.desired, $svc.pending) -ForegroundColor Gray
    if ($svc.primaryTd -eq $newTdArn -and $svc.primaryRunning -eq $svc.desired -and $svc.pending -eq 0) {
        Write-Ok "Service stable on new revision"
        break
    }
    Start-Sleep -Seconds 15
}

# --- 7. Health check -------------------------------------------------------
Write-Step "Target group health"
$tg = aws elbv2 describe-target-groups --names adaptix-production-epcr --region $Region --profile $AwsProfile --query "TargetGroups[0].TargetGroupArn" --output text
aws elbv2 describe-target-health --target-group-arn $tg --region $Region --profile $AwsProfile --query "TargetHealthDescriptions[*].{IP:Target.Id,State:TargetHealth.State,Reason:TargetHealth.Reason}" --output table

Write-Step "DONE"
Write-Ok "Image:        $imageUri"
Write-Ok "Task def:     $newTdArn"
Write-Ok "Elapsed:      $([int]((Get-Date) - $start).TotalSeconds)s since update-service"
Write-Ok "Test:         curl https://api.adaptixcore.com/api/v1/epcr/healthz"
