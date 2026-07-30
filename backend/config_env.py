"""Load project .env into process env (local/dev)."""

from __future__ import annotations

from pathlib import Path

_LOADED = False


def load_project_env() -> Path | None:
    """Load repo-root `.env` once. Safe if python-dotenv is missing."""
    global _LOADED
    if _LOADED:
        return None
    _LOADED = True
    root = Path(__file__).resolve().parents[1]
    env_path = root / ".env"
    try:
        from dotenv import load_dotenv
    except ImportError:
        return env_path if env_path.exists() else None
    if env_path.exists():
        load_dotenv(env_path, override=True)
        return env_path
    load_dotenv(override=True)
    return None
