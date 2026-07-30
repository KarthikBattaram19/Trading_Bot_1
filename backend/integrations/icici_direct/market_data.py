"""ICICI Direct market data: Breeze quotes → normalized ticks (A1).

WebSocket OHLC streaming is Phase 1 (A2); REST quotes are primary for Phase 0.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from backend.integrations.icici_direct.instrument_master import InstrumentMaster, get_instrument_master
from backend.integrations.icici_direct.models import NormalizedTick
from backend.integrations.icici_direct.session_manager import SessionManager, get_session_manager

logger = logging.getLogger(__name__)


class IciciDirectMarketDataAdapter:
    """Data-only marks adapter — never places orders."""

    def __init__(
        self,
        session_manager: SessionManager | None = None,
        instrument_master: InstrumentMaster | None = None,
    ) -> None:
        self.session_manager = session_manager or get_session_manager()
        self.instruments = instrument_master or get_instrument_master()
        self._last_ticks: dict[str, NormalizedTick] = {}
        self.ws_connected = False
        self.last_error: str | None = None

    async def ensure_instruments(self) -> int:
        if self.instruments.count > 0:
            return self.instruments.count
        client = await self.session_manager.ensure_session()
        return await self.instruments.refresh(client)

    async def get_ltp(
        self,
        exchange: str,
        tradingsymbol: str,
        symboltoken: str | None = None,
    ) -> NormalizedTick:
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
            bid=_optional_float(data.get("best_bid_price") or data.get("bid")),
            ask=_optional_float(data.get("best_ask_price") or data.get("ask")),
            ts=datetime.now(timezone.utc),
            stale=False,
        )
        self._last_ticks[f"{exchange.upper()}:{token}"] = tick
        self.last_error = None
        logger.debug("LTP %s:%s = %s", exchange, tradingsymbol, ltp)
        return tick

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

    def health(self) -> dict[str, Any]:
        return {
            "provider": "icici_direct",
            "phase": "A1",
            "rest_ok": self.last_error is None,
            "ws_connected": self.ws_connected,
            "instrument_count": self.instruments.count,
            "cached_ticks": len(self._last_ticks),
            "last_error": self.last_error,
            "instruments_loaded_at": (
                self.instruments.loaded_at.isoformat() if self.instruments.loaded_at else None
            ),
        }


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
