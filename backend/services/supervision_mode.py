"""Shared SUPERVISION_MODE read — Docs/architecture.md §6.2.2 (supervised | semi_autonomous | fully_autonomous)."""

from __future__ import annotations

import os


def get_supervision_mode() -> str:
    return os.getenv("SUPERVISION_MODE", "supervised").strip().lower()
