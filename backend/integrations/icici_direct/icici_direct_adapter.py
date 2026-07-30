"""ICICI Direct BrokerAdapter implementation (architecture.md §11.2 / §11.8–11.15)."""

from __future__ import annotations

import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from backend.integrations.base import BrokerAdapter, ExecutionMode, InternalOrder
from backend.integrations.icici_direct.client import IciciDirectAPIError
from backend.integrations.icici_direct.instrument_master import InstrumentMaster, get_instrument_master
from backend.integrations.icici_direct.models import IciciDirectConnectionConfig
from backend.integrations.icici_direct.order_mapper import OrderMapper
from backend.integrations.icici_direct.session_manager import SessionManager, get_session_manager

logger = logging.getLogger(__name__)


class RateLimiter:
    """Simple token-bucket style limiter (orders/sec). Breeze cap ≈ 10 combined ops/sec."""

    def __init__(self, rate_per_sec: float) -> None:
        self.rate = max(rate_per_sec, 0.1)
        self._timestamps: deque[float] = deque()

    def allow(self) -> bool:
        now = time.monotonic()
        window = 1.0
        while self._timestamps and now - self._timestamps[0] > window:
            self._timestamps.popleft()
        if len(self._timestamps) >= int(self.rate):
            return False
        self._timestamps.append(now)
        return True


class IciciDirectBrokerAdapter(BrokerAdapter):
    provider = "icici_direct"

    def __init__(
        self,
        config: IciciDirectConnectionConfig | None = None,
        session_manager: SessionManager | None = None,
        instrument_master: InstrumentMaster | None = None,
        execution_mode: ExecutionMode | None = None,
    ) -> None:
        self.config = config or IciciDirectConnectionConfig()
        self.session_manager = session_manager or get_session_manager()
        self.instruments = instrument_master or get_instrument_master()
        self.mapper = OrderMapper(product_default=self.config.product_default)
        self.execution_mode = execution_mode or ExecutionMode.shadow
        self._rate_limiter = RateLimiter(self.config.order_rate_limit_per_sec)
        self._shadow_orders: list[dict[str, Any]] = []
        self.last_reject_reason: str | None = None
        self._order_latencies_ms: deque[float] = deque(maxlen=50)

    def set_execution_mode(self, mode: ExecutionMode) -> None:
        self.execution_mode = mode

    async def authenticate(self) -> dict[str, Any]:
        session = await self.session_manager.authenticate(force=True)
        return {
            "provider": self.provider,
            "authenticated": True,
            "customer_id": session.customer_id,
            "authenticated_at": session.authenticated_at.isoformat(),
            "has_session_token": bool(session.session_token),
        }

    async def _resolve_leg_meta(self, order: InternalOrder) -> list[dict[str, Any]]:
        needs_network = False
        for leg in order.legs:
            exchange = (leg.exchange or "NFO").upper()
            if leg.symbol_token and self.instruments.resolve(symboltoken=leg.symbol_token):
                continue
            if self.instruments.resolve(exchange=exchange, tradingsymbol=leg.symbol):
                continue
            if leg.symbol_token:
                continue
            needs_network = True
            break

        client = None
        if needs_network or (
            self.execution_mode == ExecutionMode.live and self.instruments.count == 0
        ):
            client = await self.session_manager.ensure_session()
            if self.instruments.count == 0:
                try:
                    await self.instruments.refresh(client)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Instrument master refresh skipped: %s", exc)

        resolved: list[dict[str, Any]] = []
        for leg in order.legs:
            exchange = (leg.exchange or "NFO").upper()
            symbol = leg.symbol
            token = leg.symbol_token
            record = None
            if token:
                record = self.instruments.resolve(symboltoken=token)
            if not record:
                record = self.instruments.resolve(exchange=exchange, tradingsymbol=symbol)
            if not record and client is not None:
                record = await self.instruments.resolve_or_search(
                    client, exchange=exchange, tradingsymbol=symbol
                )
            if not record and token:
                resolved.append(
                    {
                        "tradingsymbol": symbol,
                        "symboltoken": token,
                        "stock_code": symbol,
                        "exchange": exchange,
                        "lotsize": 1,
                        "tick_size": 0.05,
                    }
                )
                continue
            if not record:
                raise ValueError(f"Cannot resolve instrument {exchange}:{symbol}")
            right = None
            upper = record.tradingsymbol.upper()
            if upper.endswith("CE"):
                right = "call"
            elif upper.endswith("PE"):
                right = "put"
            resolved.append(
                {
                    "tradingsymbol": record.tradingsymbol,
                    "symboltoken": record.symboltoken,
                    "stock_code": record.stock_code or record.tradingsymbol,
                    "exchange": record.exchange,
                    "lotsize": record.lotsize,
                    "tick_size": record.tick_size,
                    "expiry": record.expiry,
                    "strike": record.strike,
                    "right": right,
                    "instrumenttype": record.instrumenttype,
                }
            )
        return resolved

    async def submit_order(self, order: InternalOrder) -> dict[str, Any]:
        if not order.legs:
            raise ValueError("order has no legs")

        resolved = await self._resolve_leg_meta(order)
        payloads = self.mapper.map_order_legs(order, resolved)

        if self.execution_mode in {ExecutionMode.shadow, ExecutionMode.paper}:
            dry = {
                "provider": self.provider,
                "mode": self.execution_mode.value,
                "dry_run": True,
                "internal_order_id": order.internal_order_id,
                "legs": [p.to_api_dict() for p in payloads],
                "submitted_at": datetime.now(timezone.utc).isoformat(),
            }
            self._shadow_orders.append(dry)
            logger.info(
                "ICICI Direct shadow submit internal_order_id=%s legs=%s",
                order.internal_order_id,
                len(payloads),
            )
            return {
                "success": True,
                "dry_run": True,
                "order_ids": [
                    f"shadow_{order.internal_order_id}_{i+1}" for i in range(len(payloads))
                ],
                "payloads": dry["legs"],
            }

        from backend.integrations.registry import place_order_enabled

        if not place_order_enabled():
            raise IciciDirectAPIError(
                "Live place_order blocked — set EXECUTION_MODE=live and "
                "ALLOW_LIVE_PLACE_ORDER=true (Phase 5 / GCP only)"
            )

        if not self._rate_limiter.allow():
            self.last_reject_reason = "order_rate_limit"
            raise IciciDirectAPIError("Local order rate limit exceeded")

        client = await self.session_manager.ensure_session()
        order_ids: list[str] = []
        responses: list[dict[str, Any]] = []
        for idx, payload in enumerate(payloads):
            started = time.perf_counter()
            try:
                resp = await client.place_order(payload.to_api_dict())
            except IciciDirectAPIError as exc:
                self.last_reject_reason = str(exc)
                for placed_id in reversed(order_ids):
                    try:
                        await client.cancel_order({"order_id": placed_id, "exchange_code": payload.exchange_code})
                    except IciciDirectAPIError:
                        logger.exception("Rollback cancel failed for %s", placed_id)
                raise IciciDirectAPIError(
                    f"Leg {idx + 1} failed: {exc}; attempted rollback of {len(order_ids)} legs",
                    payload=exc.payload,
                ) from exc
            elapsed_ms = (time.perf_counter() - started) * 1000
            self._order_latencies_ms.append(elapsed_ms)
            success = resp.get("Success") or {}
            oid = ""
            if isinstance(success, dict):
                oid = str(success.get("order_id") or success.get("orderid") or "")
            if oid:
                order_ids.append(oid)
            responses.append(resp)

        return {
            "success": True,
            "dry_run": False,
            "order_ids": order_ids,
            "responses": responses,
        }

    async def cancel_order(self, order_id: str, *, exchange_code: str = "NSE") -> dict[str, Any]:
        if self.execution_mode in {ExecutionMode.shadow, ExecutionMode.paper}:
            return {"success": True, "dry_run": True, "order_id": order_id}
        client = await self.session_manager.ensure_session()
        return await client.cancel_order({"order_id": order_id, "exchange_code": exchange_code})

    async def get_positions(self) -> list[dict[str, Any]]:
        client = await self.session_manager.ensure_session()
        payload = await client.get_positions()
        data = payload.get("Success") or []
        return data if isinstance(data, list) else [data]

    async def get_account(self) -> dict[str, Any]:
        client = await self.session_manager.ensure_session()
        return await client.get_funds()

    async def get_order_status(self, order_id: str) -> dict[str, Any]:
        if order_id.startswith("shadow_"):
            return {"order_id": order_id, "status": "complete", "dry_run": True}
        client = await self.session_manager.ensure_session()
        book = await client.get_order_list({})
        rows = book.get("Success") or []
        if isinstance(rows, list):
            for row in rows:
                if str(row.get("order_id") or row.get("orderid")) == order_id:
                    return row
        return {"order_id": order_id, "status": "unknown", "order_book": book}

    async def health(self) -> dict[str, Any]:
        from backend.integrations.registry import place_order_enabled

        session_health = self.session_manager.health()
        avg_latency = (
            sum(self._order_latencies_ms) / len(self._order_latencies_ms)
            if self._order_latencies_ms
            else None
        )
        return {
            "provider": self.provider,
            "enabled": self.config.enabled,
            "execution_mode": self.execution_mode.value,
            "place_order_enabled": place_order_enabled(),
            "default_for_execution": self.config.default_for_execution,
            "session": session_health,
            "instrument_count": self.instruments.count,
            "shadow_orders_logged": len(self._shadow_orders),
            "avg_order_latency_ms": avg_latency,
            "last_reject_reason": self.last_reject_reason,
        }

    @property
    def shadow_orders(self) -> list[dict[str, Any]]:
        return list(self._shadow_orders)


_adapter: IciciDirectBrokerAdapter | None = None


def get_icici_direct_adapter() -> IciciDirectBrokerAdapter:
    global _adapter
    if _adapter is None:
        _adapter = IciciDirectBrokerAdapter()
    return _adapter
