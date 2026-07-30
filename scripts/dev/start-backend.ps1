#Requires -Version 5.1
<#
.SYNOPSIS
  Start FastAPI backend with native uvicorn (no containers).
#>
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root

$env:PYTHONPATH = $Root
if (-not $env:EXECUTION_MODE) { $env:EXECUTION_MODE = "shadow" }
if (-not $env:LOCAL_INFRA) { $env:LOCAL_INFRA = "none" }
if (-not $env:CHROMA_PERSIST_DIRECTORY) {
  $env:CHROMA_PERSIST_DIRECTORY = Join-Path $Root "backend\data\chroma"
}

Write-Host "PYTHONPATH=$env:PYTHONPATH"
Write-Host "EXECUTION_MODE=$env:EXECUTION_MODE  LOCAL_INFRA=$env:LOCAL_INFRA"
Write-Host "Starting uvicorn on http://127.0.0.1:8000 ..."
Write-Host "Health: http://127.0.0.1:8000/health"
Write-Host ""

python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
