# Local development — native Python + Node (no container runtime)
#
# This machine does **not** require Docker, Podman, or Compose.
# Phase 0–1 run with:
#   - Python 3.11+ (backend)
#   - Node 20+ (frontend)
#   - Optional native Postgres/Redis only when LOCAL_INFRA=native
#
# Paper: Railway Nixpacks builds `backend/` remotely.
# Live: Google Cloud Buildpacks via Cloud Build (asia-south1).
#
# Quick start (PowerShell, repo root):
#   .\scripts\dev\check-env.ps1
#   .\scripts\dev\start-backend.ps1
#   .\scripts\dev\start-frontend.ps1   # second terminal
#
# Full guide: Docs/LOCAL_DEV.md

Write-Host @"

Volatility Trading Bot — native local workflow
==============================================
See Docs/LOCAL_DEV.md

  check:    .\scripts\dev\check-env.ps1
  backend:  .\scripts\dev\start-backend.ps1
  frontend: .\scripts\dev\start-frontend.ps1

"@
