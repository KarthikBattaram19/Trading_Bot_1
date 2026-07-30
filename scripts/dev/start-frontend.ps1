#Requires -Version 5.1
<#
.SYNOPSIS
  Start Next.js frontend with native npm (no containers).
#>
$ErrorActionPreference = "Stop"
$Frontend = Resolve-Path (Join-Path $PSScriptRoot "..\..\frontend")
Set-Location $Frontend

if (-not (Test-Path "node_modules")) {
  Write-Host "Installing frontend dependencies (npm ci)..."
  npm ci
}

if (-not (Test-Path ".env.local") -and (Test-Path ".env.example")) {
  Copy-Item ".env.example" ".env.local"
  Write-Host "Created frontend/.env.local from .env.example"
}

Write-Host "Starting Next.js on http://127.0.0.1:3000 ..."
npm run dev
