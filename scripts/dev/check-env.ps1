#Requires -Version 5.1
<#
.SYNOPSIS
  Verify local toolchain (native Python + Node; no container runtime).
  Phase 0 item 0.1 — Docs/LOCAL_DEV.md / implementation_plan.md
#>
$ErrorActionPreference = "Continue"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root

Write-Host "Repo: $Root"
Write-Host "Phase 0 local toolchain check (native - no Docker/Podman)"
Write-Host ""

function Test-Cmd($Name) {
  $cmd = Get-Command $Name -ErrorAction SilentlyContinue
  if ($cmd) {
    Write-Host ("  OK   {0}  -> {1}" -f $Name, $cmd.Source)
    return $true
  }
  Write-Host ("  MISS {0}" -f $Name)
  return $false
}

Write-Host "Required (Phase 0):"
$okPy = Test-Cmd "python"
$okNode = Test-Cmd "node"
$okNpm = Test-Cmd "npm"
Write-Host ""

Write-Host "Optional (LOCAL_INFRA=native later):"
[void](Test-Cmd "psql")
[void](Test-Cmd "redis-cli")
Write-Host ""

Write-Host "Not required on this machine:"
Write-Host "  Docker / Podman / Compose  (local = native; paper = Railway Nixpacks; live = Cloud Buildpacks)"
Write-Host ""

if (-not (Test-Path (Join-Path $Root ".env"))) {
  Write-Host "Hint: copy .env.example -> .env and fill ANGEL_ONE_* secrets."
} else {
  Write-Host "Found .env"
}

$chroma = Join-Path $Root "backend\data\chroma"
if (-not (Test-Path $chroma)) {
  New-Item -ItemType Directory -Path $chroma -Force | Out-Null
  Write-Host "Created $chroma (embedded Chroma dir)"
}

if ($okPy -and $okNode -and $okNpm) {
  Write-Host ""
  Write-Host "Ready for Phase 0 local smoke:"
  Write-Host "  .\scripts\dev\start-backend.ps1"
  Write-Host "  .\scripts\dev\start-frontend.ps1"
  Write-Host "  GET http://127.0.0.1:8000/health  (local_containers_required: false)"
  exit 0
}

Write-Host ""
Write-Host "Install missing tools, then re-run. See Docs/LOCAL_DEV.md"
exit 1
