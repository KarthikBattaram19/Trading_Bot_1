"""ICICI Direct Breeze WebSocket Streaming 2.0 (rate-refresh) client — A2.

Vendor source of truth:
https://api.icicidirect.com/breezeapi/documents/index.html
SDK: https://github.com/Idirect-Tech/Breeze-Python-SDK

Auth (Socket.IO): decode ``session_token`` from ``customerdetails`` as
``base64(user_id:feed_token)`` → ``auth={"user": user_id, "token": feed_token}``.
Endpoint: ``https://livestream.icicidirect.com`` (quotes / rate refresh).

Architecture §8.9.2: one mode per token (quotes ``.1!`` only), shared connection,
exponential backoff reconnect, mark feeds stale on disconnect.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, Protocol

logger = logging.getLogger(__name__)

LIVE_STREAM_URL = "https://livestream.icicidirect.com"
LIVE_FEEDS_URL = "https://livefeeds.icicidirect.com"  # order notify (not used in A2)
LIVE_OHLC_STREAM_URL = "https://breezeapi.icicidirect.com"

# Prefer quotes mode only — conserves Breeze subscription quota (§8.9.2).
WS_MODE_QUOTES = "1"
WS_MODE_DEPTH = "2"

EXCHANGE_WS_PREFIX: dict[str, str] = {
    "BSE": "1.",
    "NSE": "4.",
    "NFO": "4.",
    "NDX": "13.",
    "MCX": "6.",
    "BFO": "8.",
}

MAX_SUBSCRIPTIONS = 1000
HEARTBEAT_INTERVAL_SEC = 30.0
DEFAULT_BACKOFF_BASE_SEC = 1.0
DEFAULT_BACKOFF_MAX_SEC = 60.0
USER_AGENT = "python-socketio[client]/socket"

TickHandler = Callable[[list[Any]], Awaitable[None] | None]
DisconnectHandler = Callable[[], Awaitable[None] | None]


class StreamTransport(Protocol):
    """Testable Socket.IO surface used by ``BreezeMarketStream``."""

    connected: bool

    async def connect(
        self,
        url: str,
        *,
        headers: dict[str, str],
        auth: dict[str, str],
        transports: list[str],
        wait_timeout: float,
    ) -> None: ...

    async def disconnect(self) -> None: ...

    async def emit(self, event: str, data: Any = None) -> None: ...

    def on(self, event: str, handler: Callable[..., Any]) -> None: ...


def decode_breeze_ws_auth(session_token_b64: str) -> tuple[str, str]:
    """Decode Breeze ``session_token`` → ``(user_id, feed_token)`` for Socket.IO auth."""
    raw = (session_token_b64 or "").strip()
    if not raw:
        raise ValueError("session_token is empty — authenticate via customerdetails first")
    try:
        decoded = base64.b64decode(raw.encode("ascii")).decode("ascii")
    except Exception as exc:  # noqa: BLE001
        raise ValueError("session_token is not valid base64") from exc
    if ":" not in decoded:
        raise ValueError("session_token decode missing user:token separator")
    user_id, feed_token = decoded.split(":", 1)
    if not user_id or not feed_token:
        raise ValueError("session_token decode produced empty user or feed token")
    return user_id, feed_token


def stock_token_for_quotes(exchange: str, symboltoken: str, *, mode: str = WS_MODE_QUOTES) -> str:
    """Build Breeze WS stock token, e.g. ``4.1!3045`` (NSE quotes)."""
    prefix = EXCHANGE_WS_PREFIX.get(exchange.upper())
    if not prefix:
        raise ValueError(f"Unsupported exchange for Breeze WS: {exchange}")
    token = str(symboltoken).strip()
    if not token:
        raise ValueError("symboltoken is required for WS subscribe")
    if mode not in {WS_MODE_QUOTES, WS_MODE_DEPTH}:
        raise ValueError(f"Unsupported WS mode: {mode}")
    return f"{prefix}{mode}!{token}"


def token_from_stock_symbol(stock_symbol: str) -> tuple[str | None, str | None]:
    """Parse ``4.1!3045`` → ``(exchange_guess, token)``."""
    if not stock_symbol or "!" not in stock_symbol:
        return None, None
    head, token = stock_symbol.split("!", 1)
    parts = head.split(".")
    if not parts:
        return None, token
    exch_code = parts[0]
    exchange = {
        "1": "BSE",
        "4": "NSE",  # also NFO — caller may override via subscription map
        "13": "NDX",
        "6": "MCX",
        "8": "BFO",
        "2": "BFO",
    }.get(exch_code)
    return exchange, token


class FakeStreamTransport:
    """In-memory transport for unit tests (no network)."""

    def __init__(self) -> None:
        self.connected = False
        self.emitted: list[tuple[str, Any]] = []
        self._handlers: dict[str, Callable[..., Any]] = {}
        self.connect_calls = 0
        self.fail_next_connect = False

    async def connect(
        self,
        url: str,
        *,
        headers: dict[str, str],
        auth: dict[str, str],
        transports: list[str],
        wait_timeout: float,
    ) -> None:
        self.connect_calls += 1
        if self.fail_next_connect:
            self.fail_next_connect = False
            raise ConnectionError("simulated connect failure")
        self.connected = True
        self.last_url = url
        self.last_auth = auth
        self.last_headers = headers

    async def disconnect(self) -> None:
        self.connected = False

    async def emit(self, event: str, data: Any = None) -> None:
        self.emitted.append((event, data))

    def on(self, event: str, handler: Callable[..., Any]) -> None:
        self._handlers[event] = handler

    async def simulate_stock(self, payload: list[Any]) -> None:
        handler = self._handlers.get("stock")
        if handler:
            result = handler(payload)
            if asyncio.iscoroutine(result):
                await result

    async def simulate_disconnect(self) -> None:
        self.connected = False
        handler = self._handlers.get("disconnect")
        if handler:
            result = handler()
            if asyncio.iscoroutine(result):
                await result


def _create_async_socketio_client() -> Any:
    import socketio

    return socketio.AsyncClient(logger=False, engineio_logger=False)


class BreezeMarketStream:
    """Single shared rate-refresh Socket.IO connection for market ticks."""

    def __init__(
        self,
        *,
        url: str = LIVE_STREAM_URL,
        transport: StreamTransport | None = None,
        on_tick: TickHandler | None = None,
        on_disconnect: DisconnectHandler | None = None,
        backoff_base_sec: float = DEFAULT_BACKOFF_BASE_SEC,
        backoff_max_sec: float = DEFAULT_BACKOFF_MAX_SEC,
        auto_reconnect: bool = True,
    ) -> None:
        self.url = url.rstrip("/")
        self._transport = transport
        self._owns_transport = transport is None
        self.on_tick = on_tick
        self.on_disconnect = on_disconnect
        self.backoff_base_sec = backoff_base_sec
        self.backoff_max_sec = backoff_max_sec
        self.auto_reconnect = auto_reconnect

        self._user_id: str | None = None
        self._feed_token: str | None = None
        self._subscriptions: set[str] = set()
        self._reconnect_attempts = 0
        self._reconnect_task: asyncio.Task[None] | None = None
        self._closing = False
        self.connected = False
        self.last_error: str | None = None
        self.connected_at: datetime | None = None
        self.last_message_at: datetime | None = None
        self.last_heartbeat_at: datetime | None = None

    @property
    def subscriptions(self) -> set[str]:
        return set(self._subscriptions)

    @property
    def subscription_count(self) -> int:
        return len(self._subscriptions)

    def _ensure_transport(self) -> StreamTransport:
        if self._transport is None:
            self._transport = _create_async_socketio_client()
            self._owns_transport = True
        return self._transport

    async def connect(self, *, session_token_b64: str) -> None:
        """Connect (or reconnect) using decoded Breeze session_token auth."""
        self._closing = False
        user_id, feed_token = decode_breeze_ws_auth(session_token_b64)
        self._user_id = user_id
        self._feed_token = feed_token
        await self._connect_once()

    async def _connect_once(self) -> None:
        if not self._user_id or not self._feed_token:
            raise ValueError("WS auth not set — call connect(session_token_b64=...) first")
        transport = self._ensure_transport()
        if transport.connected:
            self.connected = True
            return

        auth = {"user": self._user_id, "token": self._feed_token}
        headers = {"User-Agent": USER_AGENT}
        try:
            transport.on("stock", self._handle_stock)
            transport.on("disconnect", self._handle_disconnect)
            await transport.connect(
                self.url,
                headers=headers,
                auth=auth,
                transports=["websocket"],
                wait_timeout=3.0,
            )
            self.connected = True
            self.connected_at = datetime.now(timezone.utc)
            self.last_heartbeat_at = self.connected_at
            self.last_error = None
            self._reconnect_attempts = 0
            if self._subscriptions:
                await transport.emit("join", list(self._subscriptions))
            logger.info(
                "Breeze WS connected url=%s subscriptions=%s",
                self.url,
                len(self._subscriptions),
            )
        except Exception as exc:  # noqa: BLE001
            self.connected = False
            self.last_error = str(exc)
            logger.warning("Breeze WS connect failed: %s", exc)
            raise

    async def disconnect(self) -> None:
        self._closing = True
        self._cancel_reconnect()
        transport = self._transport
        if transport is not None and transport.connected:
            try:
                await transport.emit("disconnect", "transport close")
            except Exception:  # noqa: BLE001
                pass
            try:
                await transport.disconnect()
            except Exception as exc:  # noqa: BLE001
                logger.debug("WS disconnect error: %s", exc)
        self.connected = False
        logger.info("Breeze WS disconnected")

    async def subscribe(self, stock_tokens: list[str] | str) -> list[str]:
        tokens = [stock_tokens] if isinstance(stock_tokens, str) else list(stock_tokens)
        added: list[str] = []
        for token in tokens:
            if token in self._subscriptions:
                continue
            if len(self._subscriptions) >= MAX_SUBSCRIPTIONS:
                raise ValueError(
                    f"Breeze WS subscription quota exceeded ({MAX_SUBSCRIPTIONS})"
                )
            self._subscriptions.add(token)
            added.append(token)
        if added and self.connected:
            transport = self._ensure_transport()
            await transport.emit("join", added)
        return added

    async def unsubscribe(self, stock_tokens: list[str] | str) -> list[str]:
        tokens = [stock_tokens] if isinstance(stock_tokens, str) else list(stock_tokens)
        removed: list[str] = []
        for token in tokens:
            if token in self._subscriptions:
                self._subscriptions.discard(token)
                removed.append(token)
        if removed and self.connected:
            transport = self._ensure_transport()
            await transport.emit("leave", removed)
        return removed

    async def _handle_stock(self, data: Any) -> None:
        now = datetime.now(timezone.utc)
        self.last_message_at = now
        self.last_heartbeat_at = now
        if not isinstance(data, list):
            return
        if self.on_tick:
            result = self.on_tick(data)
            if asyncio.iscoroutine(result):
                await result

    async def _handle_disconnect(self, *_args: Any) -> None:
        was_connected = self.connected
        self.connected = False
        if self.on_disconnect:
            result = self.on_disconnect()
            if asyncio.iscoroutine(result):
                await result
        if was_connected and not self._closing and self.auto_reconnect:
            self._schedule_reconnect()

    def _cancel_reconnect(self) -> None:
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
        self._reconnect_task = None

    def _schedule_reconnect(self) -> None:
        self._cancel_reconnect()
        delay = min(
            self.backoff_max_sec,
            self.backoff_base_sec * (2**self._reconnect_attempts),
        )
        self._reconnect_attempts += 1
        logger.info(
            "Breeze WS reconnect scheduled in %.1fs (attempt %s)",
            delay,
            self._reconnect_attempts,
        )

        async def _run() -> None:
            try:
                await asyncio.sleep(delay)
                if self._closing:
                    return
                await self._connect_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.last_error = str(exc)
                logger.warning("Breeze WS reconnect failed: %s", exc)
                if not self._closing and self.auto_reconnect:
                    self._schedule_reconnect()

        try:
            loop = asyncio.get_running_loop()
            self._reconnect_task = loop.create_task(_run())
        except RuntimeError:
            logger.warning("No running loop — cannot schedule WS reconnect")

    def health(self) -> dict[str, Any]:
        age: float | None = None
        if self.last_message_at:
            age = max(
                0.0,
                (datetime.now(timezone.utc) - self.last_message_at).total_seconds(),
            )
        return {
            "connected": self.connected,
            "url": self.url,
            "subscription_count": self.subscription_count,
            "subscriptions": sorted(self._subscriptions)[:50],
            "reconnect_attempts": self._reconnect_attempts,
            "connected_at": self.connected_at.isoformat() if self.connected_at else None,
            "last_message_at": (
                self.last_message_at.isoformat() if self.last_message_at else None
            ),
            "last_message_age_sec": age,
            "last_heartbeat_at": (
                self.last_heartbeat_at.isoformat() if self.last_heartbeat_at else None
            ),
            "heartbeat_interval_sec": HEARTBEAT_INTERVAL_SEC,
            "last_error": self.last_error,
            "mode": "quotes",
        }
