"""Low-level ICICI Direct Breeze API HTTP client.

Async httpx wrapper around Breeze REST:
https://api.icicidirect.com/breezeapi/documents/index.html
SDK reference: https://github.com/Idirect-Tech/Breeze-Python-SDK
Customer login: https://secure.icicidirect.com/customer/login
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

import httpx

logger = logging.getLogger(__name__)

ROOT_URL = "https://api.icicidirect.com/breezeapi/api/v1"
CUSTOMER_LOGIN_URL = "https://secure.icicidirect.com/customer/login"
BREEZE_LOGIN_URL = "https://api.icicidirect.com/apiuser/login"
IPIFY_URL = "https://api.ipify.org"

# Public security-master zip used by Breeze SDK for instrument identity
SECURITY_MASTER_ZIP_URL = (
    "https://directlink.icicidirect.com/NewSecurityMaster/SecurityMaster.zip"
)

ROUTES = {
    "customerdetails": "/customerdetails",
    "funds": "/funds",
    "portfolioholdings": "/portfolioholdings",
    "portfoliopositions": "/portfoliopositions",
    "quotes": "/quotes",
    "historicalcharts": "/historicalcharts",
    "order": "/order",
    "trade": "/trades",
    "optionchain": "/optionchain",
}


class IciciDirectAPIError(Exception):
    def __init__(self, message: str, *, payload: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.payload = payload or {}


def breeze_login_url(api_key: str) -> str:
    """URL to obtain a daily API_Session (session_token input for generate_session)."""
    return f"{BREEZE_LOGIN_URL}?api_key={quote_plus(api_key)}"


class IciciDirectClient:
    """Async HTTP wrapper around Breeze REST endpoints (checksum auth)."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        public_ip: str | None = None,
        timeout: float = 20.0,
        root_url: str = ROOT_URL,
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.root_url = root_url.rstrip("/")
        self.timeout = timeout
        self._public_ip_override = public_ip
        self.public_ip = public_ip or "127.0.0.1"
        self._public_ip_resolved = bool(public_ip)
        self.api_session: str | None = None  # daily login API_Session
        self.session_token: str | None = None  # post-customerdetails token
        self.customer_id: str | None = None

    def set_session(
        self,
        *,
        session_token: str,
        api_session: str | None = None,
        customer_id: str | None = None,
    ) -> None:
        self.session_token = session_token
        if api_session:
            self.api_session = api_session
        if customer_id:
            self.customer_id = customer_id

    def clear_session(self) -> None:
        self.session_token = None
        self.api_session = None
        self.customer_id = None

    async def ensure_public_ip(self) -> str:
        if self._public_ip_resolved:
            return self.public_ip
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(IPIFY_URL)
                response.raise_for_status()
                ip = response.text.strip()
                if ip:
                    self.public_ip = ip
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not resolve public IP via ipify: %s", exc)
        self._public_ip_resolved = True
        return self.public_ip

    @staticmethod
    def _timestamp() -> str:
        # ISO8601 UTC with 0 milliseconds, as required by Breeze checksum
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    def _checksum(self, timestamp: str, body: str) -> str:
        raw = f"{timestamp}{body}{self.api_secret}"
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return f"token {digest}"

    def _headers(self, timestamp: str, body: str, *, authenticated: bool = True) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-AppKey": self.api_key,
            "X-Timestamp": timestamp,
            "X-Checksum": self._checksum(timestamp, body),
        }
        if authenticated and self.session_token:
            headers["X-SessionToken"] = self.session_token
        return headers

    async def request(
        self,
        method: str,
        route_key: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        authenticated: bool = True,
    ) -> dict[str, Any]:
        await self.ensure_public_ip()
        path = ROUTES[route_key]
        url = f"{self.root_url}{path}"
        body_obj = json_body if json_body is not None else {}
        # Breeze checksum is over the exact JSON string posted
        body_str = json.dumps(body_obj, separators=(",", ":"), ensure_ascii=False)
        timestamp = self._timestamp()
        headers = self._headers(timestamp, body_str, authenticated=authenticated)

        # Breeze expects a JSON body on GET as well (see breeze_connect.make_request).
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(
                method.upper(),
                url,
                headers=headers,
                content=body_str.encode("utf-8"),
                params=params,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise IciciDirectAPIError(
                f"Non-JSON response ({response.status_code})",
                payload={"text": response.text[:500]},
            ) from exc

        if response.status_code >= 400:
            raise IciciDirectAPIError(
                f"HTTP {response.status_code}: {payload.get('Error') or payload.get('message') or payload}",
                payload=payload if isinstance(payload, dict) else {},
            )

        if isinstance(payload, dict):
            err = payload.get("Error") or payload.get("Status")
            if err and str(err).lower() not in {"", "none", "success", "0"} and payload.get("Success") in (None, False):
                # Some endpoints return Status != 200 with Error string
                if payload.get("Success") is None and payload.get("Error"):
                    raise IciciDirectAPIError(str(payload.get("Error")), payload=payload)

        return payload if isinstance(payload, dict) else {"Success": payload}

    async def generate_session(self, api_session: str) -> dict[str, Any]:
        """
        Exchange daily API_Session (from Breeze login redirect) for session_token.

        Login flow (matches breeze_connect.api_util):
        1. Open https://api.icicidirect.com/apiuser/login?api_key=<AppKey>
        2. Capture API_Session from redirect
        3. GET customerdetails with JSON body {SessionToken, AppKey} (no checksum)
        """
        self.api_session = api_session
        payload = await self._customerdetails_exchange(api_session)
        success = payload.get("Success") or {}
        if not isinstance(success, dict):
            raise IciciDirectAPIError(
                "Unexpected customerdetails payload",
                payload=payload if isinstance(payload, dict) else {},
            )
        token = success.get("session_token") or success.get("SessionToken")
        if not token:
            err = payload.get("Error") or "customerdetails missing session_token"
            raise IciciDirectAPIError(
                f"{err} — re-login via Breeze API login URL",
                payload=payload,
            )
        customer_id = success.get("idirect_userid") or success.get("customer_id")
        self.set_session(
            session_token=str(token),
            api_session=api_session,
            customer_id=str(customer_id) if customer_id else None,
        )
        return payload

    async def _customerdetails_exchange(self, api_session: str) -> dict[str, Any]:
        """Unsigned GET+JSON body — same shape as official Breeze SDK api_util."""
        await self.ensure_public_ip()
        url = f"{self.root_url}{ROUTES['customerdetails']}"
        body_obj = {"SessionToken": api_session, "AppKey": self.api_key}
        body_str = json.dumps(body_obj, separators=(",", ":"), ensure_ascii=False)
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(
                "GET",
                url,
                headers=headers,
                content=body_str.encode("utf-8"),
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise IciciDirectAPIError(
                f"Non-JSON customerdetails ({response.status_code})",
                payload={"text": response.text[:500]},
            ) from exc
        if response.status_code >= 400:
            raise IciciDirectAPIError(
                f"customerdetails HTTP {response.status_code}",
                payload=payload if isinstance(payload, dict) else {},
            )
        if isinstance(payload, dict):
            err = payload.get("Error")
            if err and payload.get("Success") in (None, False, ""):
                raise IciciDirectAPIError(str(err), payload=payload)
            return payload
        return {"Success": payload}

    async def get_customer_details(self) -> dict[str, Any]:
        if not self.api_session:
            raise IciciDirectAPIError("No API_Session — authenticate first")
        return await self._customerdetails_exchange(self.api_session)

    async def get_funds(self) -> dict[str, Any]:
        return await self.request("GET", "funds", json_body={})

    async def get_positions(self) -> dict[str, Any]:
        return await self.request("GET", "portfoliopositions", json_body={})

    async def get_holdings(self) -> dict[str, Any]:
        return await self.request("GET", "portfolioholdings", json_body={})

    async def get_quotes(
        self,
        *,
        stock_code: str,
        exchange_code: str,
        product_type: str = "cash",
        expiry_date: str = "",
        right: str = "",
        strike_price: str = "",
    ) -> dict[str, Any]:
        body = {
            "stock_code": stock_code,
            "exchange_code": exchange_code,
            "product_type": product_type,
            "expiry_date": expiry_date,
            "right": right,
            "strike_price": strike_price,
        }
        return await self.request("GET", "quotes", json_body=body)

    async def get_option_chain(
        self,
        *,
        stock_code: str,
        exchange_code: str = "NFO",
        expiry_date: str = "",
        product_type: str = "options",
        right: str = "",
        strike_price: str = "",
    ) -> dict[str, Any]:
        """Breeze GetOptionChain — full chain quotes for one expiry.

        Authority: https://api.icicidirect.com/breezeapi/documents/index.html#optionchain
        """
        body = {
            "stock_code": stock_code,
            "exchange_code": exchange_code,
            "expiry_date": expiry_date,
            "product_type": product_type,
            "right": right,
            "strike_price": strike_price,
        }
        return await self.request("GET", "optionchain", json_body=body)

    async def get_historical_charts(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self.request("GET", "historicalcharts", json_body=params)

    async def get_order_list(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self.request("GET", "order", json_body=params or {})

    async def place_order(self, params: dict[str, Any]) -> dict[str, Any]:
        """Blocked through Phase 4. Phase 5 requires live mode + ALLOW_LIVE_PLACE_ORDER."""
        from backend.integrations.registry import place_order_enabled

        if not place_order_enabled():
            raise IciciDirectAPIError(
                "Breeze place_order disabled "
                "(Phase 0–4: EXECUTION_MODE≠live or ALLOW_LIVE_PLACE_ORDER not set)"
            )
        return await self.request("POST", "order", json_body=params)

    async def cancel_order(self, params: dict[str, Any]) -> dict[str, Any]:
        from backend.integrations.registry import place_order_enabled

        if not place_order_enabled():
            raise IciciDirectAPIError(
                "Breeze cancel_order disabled "
                "(Phase 0–4: EXECUTION_MODE≠live or ALLOW_LIVE_PLACE_ORDER not set)"
            )
        return await self.request("DELETE", "order", json_body=params)

    async def modify_order(self, params: dict[str, Any]) -> dict[str, Any]:
        from backend.integrations.registry import place_order_enabled

        if not place_order_enabled():
            raise IciciDirectAPIError(
                "Breeze modify_order disabled "
                "(Phase 0–4: EXECUTION_MODE≠live or ALLOW_LIVE_PLACE_ORDER not set)"
            )
        return await self.request("PUT", "order", json_body=params)

    async def fetch_security_master_zip(self) -> bytes:
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            response = await client.get(SECURITY_MASTER_ZIP_URL)
            response.raise_for_status()
            return response.content
