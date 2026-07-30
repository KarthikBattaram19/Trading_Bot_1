#!/usr/bin/env bash
# Remote start for Railway (Nixpacks) and GCP Cloud Run (Buildpacks).
# When Root Directory / source is `backend/`, files sit at $PWD (main.py, …)
# but the codebase imports `backend.*`. Shim a package parent on PYTHONPATH.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

if [[ -f "$APP_DIR/main.py" ]]; then
  SHIM="$(mktemp -d)"
  ln -sfn "$APP_DIR" "$SHIM/backend"
  export PYTHONPATH="${SHIM}${PYTHONPATH:+:$PYTHONPATH}"
fi

PORT="${PORT:-8080}"
exec uvicorn backend.main:app --host 0.0.0.0 --port "$PORT"
