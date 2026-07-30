#!/usr/bin/env bash
# Railway entry when Root Directory = backend/ (see backend/railway.toml).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$ROOT/scripts/start_remote.sh"
