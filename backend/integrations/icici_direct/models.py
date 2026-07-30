"""Pydantic DTOs for ICICI Direct Breeze API payloads."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class IciciDirectCredentials(BaseModel):
    api_key: str
    api_secret: str
    session_token: str  # Daily API_Session from Breeze login redirect
    public_ip: str | None = None


class IciciDirectSession(BaseModel):
    session_token: str  # Post-customerdetails session token for X-SessionToken
    api_session: str  # Original API_Session from login
    authenticated_at: datetime
    customer_id: str | None = None
    expires_hint: str | None = "daily_session_login"


class InstrumentRecord(BaseModel):
    exchange: str
    tradingsymbol: str
    symboltoken: str  # Breeze stock_code / token identity
    name: str | None = None
    instrumenttype: str | None = None
    expiry: str | None = None
    strike: float | None = None
    lotsize: int = 1
    tick_size: float = 0.05
    stock_code: str | None = None  # Breeze short stock code when distinct


class NormalizedTick(BaseModel):
    provider: str = "icici_direct"
    exchange: str
    symbol: str
    provider_symbol_id: str
    ltp: float
    bid: float | None = None
    ask: float | None = None
    ts: datetime
    stale: bool = False


class PlaceOrderPayload(BaseModel):
    """Breeze place-order body (NSE / BSE / NFO)."""

    stock_code: str
    exchange_code: str
    product: str = "cash"
    action: str  # buy / sell
    order_type: str = "limit"
    quantity: str
    price: str = "0"
    validity: str = "day"
    validity_date: str | None = None
    disclosed_quantity: str = "0"
    expiry_date: str | None = None
    right: str | None = None
    strike_price: str | None = None
    stoploss: str = "0"
    user_remark: str | None = None
    order_id: str | None = None

    def to_api_dict(self) -> dict[str, Any]:
        data = self.model_dump(exclude_none=True)
        return data


class IciciDirectConnectionConfig(BaseModel):
    connection_id: str = "icici_direct_01"
    provider: str = "icici_direct"
    mode: str = "live"  # connection capability; EXECUTION_MODE gates submit
    enabled: bool = True
    credential_ref: str = "icici_direct_breeze"
    default_for_execution: bool = True
    static_ipv4: str | None = None
    exchanges_enabled: list[str] = Field(default_factory=lambda: ["NSE", "BSE", "NFO"])
    product_default: str = "margin"  # F&O default; cash for equity
    order_rate_limit_per_sec: float = 9.0  # Breeze hard cap ~10 combined ops/sec
    ws_modes: list[str] = Field(default_factory=lambda: ["quotes"])  # A2: quotes (.1!) only
    market_session: str = "NSE_EQ_FO"
    customer_login_url: str = "https://secure.icicidirect.com/customer/login"
    breeze_login_url: str = "https://api.icicidirect.com/apiuser/login"
    breeze_docs_url: str = "https://api.icicidirect.com/breezeapi/documents/index.html"
