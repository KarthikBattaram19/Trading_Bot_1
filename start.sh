#!/usr/bin/env bash
# Railway monorepo entrypoint (repo root).
# Prefer Root Directory=backend → use scripts/start_remote.sh there instead.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$ROOT/backend/scripts/start_remote.sh"
