"""In-memory credential vault for integration secrets.

Production should back this with Secret Manager; env vars are the local source.
Never log raw session tokens, API secrets, or AppKeys.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from threading import RLock
from typing import Any


@dataclass
class CredentialBundle:
    ref: str
    values: dict[str, str] = field(default_factory=dict)
    session: dict[str, Any] = field(default_factory=dict)


class CredentialVault:
    def __init__(self) -> None:
        self._lock = RLock()
        self._bundles: dict[str, CredentialBundle] = {}

    def load_from_env(self, ref: str, env_map: dict[str, str]) -> CredentialBundle:
        """Map vault keys → env var names and load non-empty values."""
        values: dict[str, str] = {}
        for key, env_name in env_map.items():
            raw = os.getenv(env_name, "").strip()
            if raw:
                values[key] = raw
        with self._lock:
            existing = self._bundles.get(ref)
            if existing:
                merged = dict(existing.values)
                merged.update(values)
                values = merged
            bundle = CredentialBundle(ref=ref, values=values)
            if existing and existing.session:
                bundle.session = dict(existing.session)
            self._bundles[ref] = bundle
        return bundle

    def get(self, ref: str) -> CredentialBundle | None:
        with self._lock:
            return self._bundles.get(ref)

    def put_session(self, ref: str, session: dict[str, Any]) -> None:
        with self._lock:
            bundle = self._bundles.setdefault(ref, CredentialBundle(ref=ref))
            safe = {
                k: v
                for k, v in session.items()
                if k
                in (
                    "session_token",
                    "api_session",
                    "customer_id",
                    "authenticated_at",
                    "expires_hint",
                )
            }
            bundle.session = safe

    def put_value(self, ref: str, key: str, value: str) -> None:
        with self._lock:
            bundle = self._bundles.setdefault(ref, CredentialBundle(ref=ref))
            bundle.values[key] = value

    def clear_session(self, ref: str) -> None:
        with self._lock:
            bundle = self._bundles.get(ref)
            if bundle:
                bundle.session = {}

    def has_required(self, ref: str, required: list[str]) -> bool:
        bundle = self.get(ref)
        if not bundle:
            return False
        return all(bundle.values.get(k) for k in required)


_vault = CredentialVault()

ICICI_DIRECT_CRED_REF = "icici_direct_breeze"
ICICI_DIRECT_ENV_MAP = {
    "api_key": "ICICI_DIRECT_API_KEY",
    "api_secret": "ICICI_DIRECT_API_SECRET",
    "session_token": "ICICI_DIRECT_SESSION_TOKEN",
    "public_ip": "ICICI_DIRECT_PUBLIC_IP",
}


def get_vault() -> CredentialVault:
    return _vault


def load_icici_direct_credentials() -> CredentialBundle:
    return _vault.load_from_env(ICICI_DIRECT_CRED_REF, ICICI_DIRECT_ENV_MAP)
