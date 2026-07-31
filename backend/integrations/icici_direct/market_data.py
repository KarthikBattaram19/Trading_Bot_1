"""ICICI Direct market data: REST quotes + WS Streaming 2.0 → normalized ticks.

Phase A1: REST ``get_quotes`` / LTP.
Phase A2: Breeze livestream Socket.IO (rate refresh) for sub-second freshness.

Tick decode (list → NormalizedTick) lives only in this module (Architecture §8.9.2).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from backend.integrations.icici_direct.instrument_master import InstrumentMaster, get_instrument_master
from backend.integrations.icici_direct.models import IndexMark, NormalizedTick
from backend.integrations.icici_direct.session_manager import SessionManager, get_session_manager
from backend.integrations.icici_direct.ws_stream import (
    WS_MODE_DEPTH,
    BreezeMarketStream,
    FakeStreamTransport,
    stock_token_for_quotes,
    token_from_stock_symbol,
)

logger = logging.getLogger(__name__)

# Prefer WS cache when tick age is under this (sub-second freshness target).
WS_PREFER_MAX_AGE_SEC = 1.0

# Breeze NSE index Token values (NSEScripMaster / get_names) — small probe set so
# feed health receives ticks after connect without waiting for a REST LTP call.
# Tick symbols look like ``4.1!NIFTY 50`` (SDK cash subscribe for stock_code=NIFTY).
WS_FEED_PROBES: tuple[tuple[str, str, str], ...] = (
    ("NSE", "NIFTY", "NIFTY 50"),
    ("NSE", "BANKNIFTY", "Nifty Bank"),
    ("NSE", "INDVIX", "INDIA VIX"),
)

# Situational-bar global marks — Breeze cash quotes (stock_code INDVIX per vendor).
GLOBAL_INDEX_SPECS: tuple[tuple[str, str, str], ...] = (
    ("NIFTY 50", "NIFTY", "NSE"),
    ("INDIA VIX", "INDVIX", "NSE"),
)


class IciciDirectMarketDataAdapter:
    """Data-only marks adapter — never places orders."""

    def __init__(
        self,
        session_manager: SessionManager | None = None,
        instrument_master: InstrumentMaster | None = None,
        *,
        stream: BreezeMarketStream | None = None,
        ws_prefer_max_age_sec: float = WS_PREFER_MAX_AGE_SEC,
    ) -> None:
        self.session_manager = session_manager or get_session_manager()
        self.instruments = instrument_master or get_instrument_master()
        self._last_ticks: dict[str, NormalizedTick] = {}
        # Map WS stock-token → (exchange, tradingsymbol, provider_symbol_id)
        self._ws_meta: dict[str, tuple[str, str, str]] = {}
        self.ws_prefer_max_age_sec = float(ws_prefer_max_age_sec)
        self.last_error: str | None = None
        self._stream = stream or BreezeMarketStream(
            on_tick=self._on_ws_tick,
            on_disconnect=self._on_ws_disconnect,
        )
        if stream is not None:
            # Ensure callbacks point at this adapter when a custom stream is injected.
            self._stream.on_tick = self._on_ws_tick
            self._stream.on_disconnect = self._on_ws_disconnect

    @property
    def ws_connected(self) -> bool:
        return bool(self._stream.connected)

    @property
    def stream(self) -> BreezeMarketStream:
        return self._stream

    async def ensure_instruments(self, *, max_age_sec: float | None = None) -> int:
        """Load scrip master; refresh when empty or older than ``max_age_sec`` (MD-11).

        SecurityMaster.zip is public — prefer session client when authenticated,
        otherwise download without Breeze login so G11–G12 universe can load.
        """
        from backend.paper_sim.freshness import instrument_master_age_sec

        age = instrument_master_age_sec(self.instruments.loaded_at)
        needs_refresh = self.instruments.count == 0
        if max_age_sec is not None and (age is None or age > max_age_sec):
            needs_refresh = True
        if not needs_refresh:
            return self.instruments.count
        try:
            client = await self.session_manager.ensure_session()
            return await self.instruments.refresh(client)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Session unavailable for instrument refresh (%s); using public SecurityMaster.zip",
                exc,
            )
            return await self.instruments.refresh_public()

    async def connect_ws(self) -> dict[str, Any]:
        """A2 — open shared Breeze livestream connection using session_token auth."""
        client = await self.session_manager.ensure_session()
        if not client.session_token:
            raise ValueError("No session_token — authenticate first")
        await self._stream.connect(session_token_b64=client.session_token)
        self.last_error = None
        return self.ws_status()

    async def ensure_ws_connected(self) -> dict[str, Any]:
        """Connect A2 WS when credentials/session allow; seed probe joins for ticks.

        Used after broker auth and when the UI polls feed health / recommendations
        so Streaming 2.0 does not stay idle after REST-only session setup.
        A bare connect without ``join`` never receives ticks (subscriptions=0).
        """
        if self.ws_connected:
            await self._seed_ws_probe_subscriptions()
            return self.ws_status()
        session_health = self.session_manager.health()
        if not session_health.get("authenticated"):
            if not session_health.get("credentials_ready"):
                return self.ws_status()
            try:
                await self.session_manager.ensure_session()
            except Exception as exc:  # noqa: BLE001
                self.last_error = str(exc)
                logger.warning("Breeze session for WS ensure failed: %s", exc)
                status = self.ws_status()
                status["ensure_error"] = str(exc)
                return status
        try:
            await self.connect_ws()
            await self._seed_ws_probe_subscriptions()
            return self.ws_status()
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
            logger.warning("Breeze WS ensure_ws_connected failed: %s", exc)
            status = self.ws_status()
            status["ensure_error"] = str(exc)
            return status

    async def _seed_ws_probe_subscriptions(self) -> None:
        """Best-effort join for index spot probes so A2 freshness can become active."""
        if not self.ws_connected:
            return
        for exchange, tradingsymbol, symboltoken in WS_FEED_PROBES:
            try:
                stock = stock_token_for_quotes(exchange, symboltoken)
                if stock in self._stream.subscriptions:
                    continue
                self._ws_meta[stock] = (exchange.upper(), tradingsymbol, str(symboltoken))
                await self._stream.subscribe(stock)
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "WS probe subscribe skipped %s:%s: %s",
                    exchange,
                    symboltoken,
                    exc,
                )

    async def disconnect_ws(self) -> dict[str, Any]:
        await self._stream.disconnect()
        self._mark_all_ticks_stale()
        return self.ws_status()

    async def subscribe_ws(
        self,
        *,
        exchange: str,
        tradingsymbol: str,
        symboltoken: str | None = None,
    ) -> dict[str, Any]:
        """Subscribe quotes mode for one instrument (one mode per token)."""
        if not self.ws_connected:
            await self.connect_ws()
        record = None
        if symboltoken:
            record = self.instruments.resolve(symboltoken=symboltoken)
        if not record:
            record = self.instruments.resolve(exchange=exchange, tradingsymbol=tradingsymbol)
        token = (record.symboltoken if record else None) or symboltoken
        if not token:
            raise ValueError("symboltoken required for WS subscribe")
        stock = stock_token_for_quotes(exchange, token)
        symbol = (record.tradingsymbol if record else None) or tradingsymbol
        self._ws_meta[stock] = (exchange.upper(), symbol, str(token))
        added = await self._stream.subscribe(stock)
        return {
            "subscribed": stock,
            "added": added,
            "exchange": exchange.upper(),
            "tradingsymbol": symbol,
            "symboltoken": str(token),
            "ws": self.ws_status(),
        }

    async def unsubscribe_ws(
        self,
        *,
        exchange: str,
        symboltoken: str,
    ) -> dict[str, Any]:
        stock = stock_token_for_quotes(exchange, symboltoken)
        removed = await self._stream.unsubscribe(stock)
        self._ws_meta.pop(stock, None)
        return {"unsubscribed": stock, "removed": removed, "ws": self.ws_status()}

    async def get_ltp(
        self,
        exchange: str,
        tradingsymbol: str,
        symboltoken: str | None = None,
    ) -> NormalizedTick:
        # A2: prefer fresh WS cache for sub-second marks.
        cached = self._prefer_ws_tick(exchange, tradingsymbol, symboltoken)
        if cached is not None:
            return cached

        client = await self.session_manager.ensure_session()
        record = None
        if symboltoken:
            record = self.instruments.resolve(symboltoken=symboltoken)
        if not record:
            record = await self.instruments.resolve_or_search(
                client, exchange=exchange, tradingsymbol=tradingsymbol
            )
        stock_code = (record.stock_code if record else None) or tradingsymbol
        token = (record.symboltoken if record else None) or symboltoken or stock_code
        product = "cash"
        if exchange.upper() == "NFO":
            product = "options" if (record and (
                (record.tradingsymbol or "").upper().endswith(("CE", "PE"))
                or "OPT" in (record.instrumenttype or "").upper()
            )) else "futures"

        payload = await client.get_quotes(
            stock_code=stock_code,
            exchange_code=exchange.upper(),
            product_type=product,
            expiry_date=(record.expiry if record and record.expiry else "") or "",
            right=_infer_right(record.tradingsymbol if record else tradingsymbol),
            strike_price=str(int(record.strike)) if record and record.strike is not None else "",
        )
        data = _first_quote(payload)
        ltp = float(
            data.get("ltp")
            or data.get("LTP")
            or data.get("last")
            or data.get("last_price")
            or 0
        )
        tick = NormalizedTick(
            exchange=exchange.upper(),
            symbol=tradingsymbol,
            provider_symbol_id=str(token),
            ltp=ltp,
            bid=_optional_float(data.get("best_bid_price") or data.get("bid") or data.get("bPrice")),
            ask=_optional_float(data.get("best_ask_price") or data.get("ask") or data.get("sPrice")),
            ts=datetime.now(timezone.utc),
            stale=False,
        )
        self._last_ticks[f"{exchange.upper()}:{token}"] = tick
        self.last_error = None
        logger.debug("LTP REST %s:%s = %s", exchange, tradingsymbol, ltp)

        # Best-effort: keep WS subscription warm for subsequent sub-second marks.
        if self.ws_connected and token:
            try:
                stock = stock_token_for_quotes(exchange, str(token))
                self._ws_meta[stock] = (exchange.upper(), tradingsymbol, str(token))
                await self._stream.subscribe(stock)
            except Exception as exc:  # noqa: BLE001
                logger.debug("WS auto-subscribe skipped: %s", exc)

        return tick

    async def get_global_indices(self) -> list[IndexMark]:
        """NIFTY 50 + India VIX for the dashboard situational bar."""
        marks: list[IndexMark] = []
        for label, stock_code, exchange in GLOBAL_INDEX_SPECS:
            marks.append(await self._fetch_index_mark(label, stock_code, exchange))
        return marks

    async def _fetch_index_mark(
        self,
        label: str,
        stock_code: str,
        exchange: str,
    ) -> IndexMark:
        # Prefer fresh WS LTP; still need REST (or prior REST) for % change.
        cached = self.get_cached_tick(exchange, stock_code)
        if cached is None:
            # Probe tokens use display names (e.g. "NIFTY 50") as provider_symbol_id.
            for _ex, _code, token in WS_FEED_PROBES:
                if _code.upper() == stock_code.upper() and _ex.upper() == exchange.upper():
                    cached = self.get_cached_tick(exchange, token)
                    break

        try:
            client = await self.session_manager.ensure_session()
            payload = await client.get_quotes(
                stock_code=stock_code,
                exchange_code=exchange.upper(),
                product_type="cash",
                expiry_date="",
                right="",
                strike_price="",
            )
            data = _first_quote(payload)
            ltp = _optional_float(
                data.get("ltp")
                or data.get("LTP")
                or data.get("last")
                or data.get("last_price")
            )
            previous_close = _optional_float(
                data.get("previous_close") or data.get("prev_close") or data.get("close")
            )
            change_pct = _optional_float(
                data.get("ltp_percent_change")
                or data.get("percent_change")
                or data.get("pChange")
            )
            if change_pct is None and ltp is not None and previous_close and previous_close != 0:
                change_pct = ((ltp - previous_close) / previous_close) * 100.0

            # Do not overlay WS LTP for global indices — some index tick shapes
            # (esp. India VIX) can decode with bad scale and flash garbage %.
            if ltp is None and cached is not None and not cached.stale:
                ltp = cached.ltp
                if previous_close and previous_close != 0:
                    change_pct = ((ltp - previous_close) / previous_close) * 100.0

            if ltp is None:
                return IndexMark(
                    label=label,
                    stock_code=stock_code,
                    exchange=exchange.upper(),
                    stale=True,
                    error="quote missing ltp",
                )

            tick = NormalizedTick(
                exchange=exchange.upper(),
                symbol=label,
                provider_symbol_id=stock_code,
                ltp=float(ltp),
                bid=_optional_float(
                    data.get("best_bid_price") or data.get("bid") or data.get("bPrice")
                ),
                ask=_optional_float(
                    data.get("best_ask_price") or data.get("ask") or data.get("sPrice")
                ),
                ts=datetime.now(timezone.utc),
                stale=False,
            )
            self._last_ticks[f"{exchange.upper()}:{stock_code}"] = tick
            self.last_error = None
            return IndexMark(
                label=label,
                stock_code=stock_code,
                exchange=exchange.upper(),
                ltp=float(ltp),
                previous_close=previous_close,
                change_pct=change_pct,
                ts=tick.ts,
                stale=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Index mark %s failed: %s", stock_code, exc)
            self.last_error = str(exc)
            if cached is not None and cached.ltp is not None:
                return IndexMark(
                    label=label,
                    stock_code=stock_code,
                    exchange=exchange.upper(),
                    ltp=cached.ltp,
                    ts=cached.ts,
                    stale=True,
                    error=str(exc),
                )
            return IndexMark(
                label=label,
                stock_code=stock_code,
                exchange=exchange.upper(),
                stale=True,
                error=str(exc),
            )

    async def get_candles(
        self,
        *,
        exchange: str,
        symboltoken: str,
        interval: str,
        from_date: str,
        to_date: str,
        stock_code: str | None = None,
    ) -> list[Any]:
        client = await self.session_manager.ensure_session()
        payload = await client.get_historical_charts(
            {
                "stock_code": stock_code or symboltoken,
                "exchange_code": exchange,
                "interval": interval,
                "from_date": from_date,
                "to_date": to_date,
                "product_type": "cash" if exchange.upper() in {"NSE", "BSE"} else "futures",
            }
        )
        success = payload.get("Success")
        if isinstance(success, list):
            return success
        return list(success or [])

    def get_cached_tick(self, exchange: str, symboltoken: str) -> NormalizedTick | None:
        return self._last_ticks.get(f"{exchange.upper()}:{symboltoken}")

    def ws_status(self) -> dict[str, Any]:
        stream_health = self._stream.health()
        freshest_age: float | None = None
        for tick in self._last_ticks.values():
            if tick.stale:
                continue
            age = _tick_age_sec(tick)
            if age is None:
                continue
            if freshest_age is None or age < freshest_age:
                freshest_age = age
        return {
            **stream_health,
            "phase": "A2",
            "cached_ticks": len(self._last_ticks),
            "freshest_tick_age_sec": freshest_age,
            "sub_second_fresh": freshest_age is not None and freshest_age < 1.0,
            "ws_prefer_max_age_sec": self.ws_prefer_max_age_sec,
        }

    def health(self) -> dict[str, Any]:
        ws = self.ws_status()
        return {
            "provider": "icici_direct",
            "phase": "A2" if self.ws_connected or self._stream.subscription_count else "A1",
            "rest_ok": self.last_error is None,
            "ws_connected": self.ws_connected,
            "ws": ws,
            "instrument_count": self.instruments.count,
            "cached_ticks": len(self._last_ticks),
            "last_error": self.last_error,
            "instruments_loaded_at": (
                self.instruments.loaded_at.isoformat() if self.instruments.loaded_at else None
            ),
        }

    def _prefer_ws_tick(
        self,
        exchange: str,
        tradingsymbol: str,
        symboltoken: str | None,
    ) -> NormalizedTick | None:
        if not self.ws_connected:
            return None
        token = symboltoken
        if not token:
            record = self.instruments.resolve(exchange=exchange, tradingsymbol=tradingsymbol)
            token = record.symboltoken if record else None
        if not token:
            return None
        tick = self._last_ticks.get(f"{exchange.upper()}:{token}")
        if tick is None or tick.stale:
            return None
        age = _tick_age_sec(tick)
        if age is None or age > self.ws_prefer_max_age_sec:
            return None
        return tick

    async def _on_ws_tick(self, data: list[Any]) -> None:
        tick = decode_breeze_tick(data, meta=self._ws_meta)
        if tick is None:
            return
        key = f"{tick.exchange}:{tick.provider_symbol_id}"
        self._last_ticks[key] = tick
        self.last_error = None
        logger.debug("LTP WS %s = %s", key, tick.ltp)

    async def _on_ws_disconnect(self) -> None:
        self._mark_all_ticks_stale()
        logger.warning("Breeze WS disconnected — marks flagged stale")

    def _mark_all_ticks_stale(self) -> None:
        for key, tick in list(self._last_ticks.items()):
            self._last_ticks[key] = tick.model_copy(update={"stale": True})


def decode_breeze_tick(
    data: list[Any],
    *,
    meta: dict[str, tuple[str, str, str]] | None = None,
) -> NormalizedTick | None:
    """
    Decode Breeze livestream ``stock`` payload list into NormalizedTick.

    Quotes shape (data_type ``1``): ``[symbol, open, last, high, low, change,
    bPrice, bQty, sPrice, sQty, ltq, avgPrice, ...]`` per Breeze docs / SDK.
    """
    if not data or not isinstance(data[0], str) or "!" not in data[0]:
        return None
    symbol = data[0]
    exchange_guess, token = token_from_stock_symbol(symbol)
    meta = meta or {}
    if symbol in meta:
        exchange, tradingsymbol, provider_id = meta[symbol]
    else:
        exchange = exchange_guess or "NSE"
        tradingsymbol = token or symbol
        provider_id = token or symbol

    # Quotes data_type == '1' (prefix like 4.1!TOKEN)
    data_type = None
    try:
        data_type = symbol.split("!")[0].split(".")[1]
    except (IndexError, AttributeError):
        data_type = None

    if data_type == WS_MODE_DEPTH or (len(data) >= 3 and isinstance(data[2], list)):
        # Market depth — not used for marks (one mode per token = quotes).
        return None

    if len(data) < 3:
        return None

    ltp = _optional_float(data[2])  # last
    if ltp is None:
        return None
    bid = _optional_float(data[6]) if len(data) > 6 else None
    ask = _optional_float(data[8]) if len(data) > 8 else None
    ts = datetime.now(timezone.utc)
    # Prefer exchange timestamp when present (index 19 NSE/BSE, 21 F&O)
    for idx in (19, 21):
        if len(data) > idx and isinstance(data[idx], (int, float)):
            try:
                ts = datetime.fromtimestamp(float(data[idx]), tz=timezone.utc)
            except (OSError, OverflowError, ValueError):
                pass
            break

    return NormalizedTick(
        exchange=exchange.upper(),
        symbol=tradingsymbol,
        provider_symbol_id=str(provider_id),
        ltp=float(ltp),
        bid=bid,
        ask=ask,
        ts=ts,
        stale=False,
    )


def _tick_age_sec(tick: NormalizedTick, *, now: datetime | None = None) -> float | None:
    if tick.ts is None:
        return None
    current = now or datetime.now(timezone.utc)
    ts = tick.ts if tick.ts.tzinfo else tick.ts.replace(tzinfo=timezone.utc)
    return max(0.0, (current.astimezone(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds())


def _first_quote(payload: dict[str, Any]) -> dict[str, Any]:
    success = payload.get("Success")
    if isinstance(success, list) and success:
        row = success[0]
        return row if isinstance(row, dict) else {}
    if isinstance(success, dict):
        return success
    return {}


def _infer_right(symbol: str | None) -> str:
    if not symbol:
        return ""
    upper = symbol.upper()
    if upper.endswith("CE"):
        return "call"
    if upper.endswith("PE"):
        return "put"
    return ""


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


_market_data: IciciDirectMarketDataAdapter | None = None


def get_market_data_adapter() -> IciciDirectMarketDataAdapter:
    global _market_data
    if _market_data is None:
        _market_data = IciciDirectMarketDataAdapter()
    return _market_data


def reset_market_data_for_tests() -> None:
    global _market_data
    _market_data = None


def make_test_market_data_with_fake_ws(
    *,
    session_manager: SessionManager | None = None,
    instrument_master: InstrumentMaster | None = None,
) -> tuple[IciciDirectMarketDataAdapter, FakeStreamTransport]:
    """Test helper — adapter wired to FakeStreamTransport (no network)."""
    transport = FakeStreamTransport()
    stream = BreezeMarketStream(transport=transport, auto_reconnect=False)
    adapter = IciciDirectMarketDataAdapter(
        session_manager=session_manager,
        instrument_master=instrument_master,
        stream=stream,
    )
    return adapter, transport
