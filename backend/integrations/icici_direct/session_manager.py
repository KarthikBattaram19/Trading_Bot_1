"""ICICI Direct session lifecycle: Breeze API_Session → session_token (A0).

Daily login:
1. Customer portal: https://secure.icicidirect.com/customer/login
2. Breeze app login: https://api.icicidirect.com/apiuser/login?api_key=<AppKey>
3. Capture API_Session → set ICICI_DIRECT_SESSION_TOKEN → generate_session
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from backend.integrations.credential_vault import (
    ICICI_DIRECT_CRED_REF,
    get_vault,
    load_icici_direct_credentials,
)
from backend.integrations.icici_direct.client import (
    IciciDirectAPIError,
    IciciDirectClient,
    breeze_login_url,
)
from backend.integrations.icici_direct.models import IciciDirectSession

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


class SessionManager:
    """Manages Breeze session tokens without logging secrets."""

    REQUIRED = ["api_key", "api_secret", "session_token"]

    def __init__(self, credential_ref: str = ICICI_DIRECT_CRED_REF) -> None:
        self.credential_ref = credential_ref
        self._client: IciciDirectClient | None = None
        self._session: IciciDirectSession | None = None
        self.last_error: str | None = None

    @property
    def client(self) -> IciciDirectClient | None:
        return self._client

    @property
    def session(self) -> IciciDirectSession | None:
        return self._session

    def credentials_ready(self) -> bool:
        load_icici_direct_credentials()
        return get_vault().has_required(self.credential_ref, self.REQUIRED)

    def login_hint(self) -> str:
        bundle = load_icici_direct_credentials()
        api_key = bundle.values.get("api_key") or "<ICICI_DIRECT_API_KEY>"
        return (
            "Obtain a daily API_Session from Breeze login, then set ICICI_DIRECT_SESSION_TOKEN. "
            f"Breeze login: {breeze_login_url(api_key)} | "
            "Customer portal: https://secure.icicidirect.com/customer/login"
        )

    def _build_client(self) -> IciciDirectClient:
        bundle = load_icici_direct_credentials()
        missing = [k for k in self.REQUIRED if not bundle.values.get(k)]
        if missing:
            raise IciciDirectAPIError(
                f"Missing ICICI Direct credentials: {', '.join(missing)}. {self.login_hint()}"
            )
        for key in self.REQUIRED:
            value = bundle.values.get(key) or ""
            try:
                value.encode("ascii")
            except UnicodeEncodeError as exc:
                raise IciciDirectAPIError(
                    f"ICICI Direct credential '{key}' contains non-ASCII characters. "
                    "Replace placeholder values in .env with real Breeze secrets."
                ) from exc
        public_ip = bundle.values.get("public_ip") or None
        client = IciciDirectClient(
            api_key=bundle.values["api_key"],
            api_secret=bundle.values["api_secret"],
            public_ip=public_ip,
        )
        sess = bundle.session
        if sess.get("session_token"):
            client.set_session(
                session_token=sess["session_token"],
                api_session=sess.get("api_session") or bundle.values.get("session_token"),
                customer_id=sess.get("customer_id"),
            )
        self._client = client
        return client

    def _store_session(self, api_session: str) -> IciciDirectSession:
        assert self._client is not None
        if not self._client.session_token:
            raise IciciDirectAPIError("Session exchange did not produce session_token")
        session = IciciDirectSession(
            session_token=self._client.session_token,
            api_session=api_session,
            authenticated_at=datetime.now(timezone.utc),
            customer_id=self._client.customer_id,
        )
        get_vault().put_session(self.credential_ref, session.model_dump(mode="json"))
        self._session = session
        self.last_error = None
        logger.info(
            "ICICI Direct Breeze session established customer_id=%s",
            session.customer_id or "unknown",
        )
        return session

    async def authenticate(self, *, force: bool = False) -> IciciDirectSession:
        client = self._build_client()
        bundle = get_vault().get(self.credential_ref)
        assert bundle is not None

        if not force and self._session and client.session_token:
            return self._session

        api_session = bundle.values["session_token"]
        try:
            await client.generate_session(api_session)
            return self._store_session(api_session)
        except IciciDirectAPIError as exc:
            self.last_error = str(exc)
            raise

    async def ensure_session(self) -> IciciDirectClient:
        await self.authenticate()
        assert self._client is not None
        return self._client

    async def logout(self) -> None:
        if self._client:
            self._client.clear_session()
        get_vault().clear_session(self.credential_ref)
        self._session = None

    def needs_midnight_relogin(self, now: datetime | None = None) -> bool:
        """Breeze API_Session is day-scoped; force re-login after IST date change."""
        if not self._session:
            return True
        current = now or datetime.now(IST)
        auth_local = self._session.authenticated_at.astimezone(IST)
        return auth_local.date() < current.date()

    def health(self) -> dict[str, Any]:
        ready = self.credentials_ready()
        authenticated = bool(self._session and self._client and self._client.session_token)
        return {
            "provider": "icici_direct",
            "phase": "A0",
            "credentials_ready": ready,
            "authenticated": authenticated,
            "needs_relogin": self.needs_midnight_relogin() if authenticated else True,
            "last_error": self.last_error,
            "login_hint": self.login_hint() if ready else None,
            "authenticated_at": (
                self._session.authenticated_at.isoformat() if self._session else None
            ),
        }


_session_manager: SessionManager | None = None


def get_session_manager() -> SessionManager:
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager


def reset_session_manager_for_tests() -> None:
    """Test helper — drop singleton."""
    global _session_manager
    _session_manager = None
