#Requires -Version 5.1
<#
.SYNOPSIS
  Link this repo to the Railway paper project (after `npx @railway/cli login`).
.DESCRIPTION
  Project: 69b6e84b-a5e7-41c4-8206-e44bace54e40
  Docs:    Docs/RAILWAY_DEPLOY.md
#>
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root

$ProjectId = "69b6e84b-a5e7-41c4-8206-e44bace54e40"
$EnvironmentId = "c8d802bb-ce4f-4098-b041-ec332b0442f6"

Write-Host "Repo: $Root"
Write-Host "Linking to Railway project $ProjectId ..."
Write-Host "If prompted, choose the backend service (e.g. trading-bot-api)."
Write-Host ""

npx --yes @railway/cli@latest whoami
if ($LASTEXITCODE -ne 0) {
  Write-Host ""
  Write-Host "Not logged in. Run:"
  Write-Host "  npx @railway/cli login"
  Write-Host "Then re-run this script."
  exit 1
}

npx --yes @railway/cli@latest link -p $ProjectId -e $EnvironmentId
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Linked. Deploy with:"
Write-Host "  npx @railway/cli up --detach"
Write-Host ""
Write-Host "Or connect GitHub in the dashboard (see Docs/RAILWAY_DEPLOY.md)."
