# build_image.ps1 — builds the EPCR staging image with adaptix-contracts vendored.
#
# Polyrepo law: Dockerfile.staging cannot reach across repo boundaries at build
# time, so this script vendors a copy of the Adaptix-Contracts source tree into
# ./vendored_contracts/ and invokes docker build from this repo's backend dir.
#
# Usage (from repo root):
#   pwsh ./backend/build_image.ps1 -Tag latest [-Push]
#
[CmdletBinding()]
param(
    [string] $Tag = "latest",
    [string] $Repository = "793439286972.dkr.ecr.us-east-1.amazonaws.com/adaptix-staging-epcr-service",
    [string] $ContractsPath = (Resolve-Path "$PSScriptRoot\..\..\Adaptix-Contracts").Path,
    [switch] $Push
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path $ContractsPath)) {
    throw "Adaptix-Contracts not found at $ContractsPath. Clone it as a sibling repo."
}

$vendor = Join-Path $PSScriptRoot "vendored_contracts"
if (Test-Path $vendor) { Remove-Item -Recurse -Force $vendor }
New-Item -ItemType Directory -Force -Path $vendor | Out-Null

Write-Host "Vendoring adaptix-contracts from $ContractsPath -> $vendor"
Copy-Item (Join-Path $ContractsPath "pyproject.toml") $vendor
Copy-Item -Recurse (Join-Path $ContractsPath "adaptix_contracts") (Join-Path $vendor "adaptix_contracts")
if (Test-Path (Join-Path $ContractsPath "README.md")) {
    Copy-Item (Join-Path $ContractsPath "README.md") $vendor
}

$image = "$Repository`:$Tag"
Write-Host "Building $image"
docker build -f Dockerfile.staging -t $image .
if ($LASTEXITCODE -ne 0) { throw "docker build failed" }

if ($Push) {
    Write-Host "Logging into ECR"
    aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin "793439286972.dkr.ecr.us-east-1.amazonaws.com"
    if ($LASTEXITCODE -ne 0) { throw "ECR login failed" }
    Write-Host "Pushing $image"
    docker push $image
    if ($LASTEXITCODE -ne 0) { throw "docker push failed" }
}

Write-Host "Done."
