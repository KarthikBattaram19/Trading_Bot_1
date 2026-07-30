"""Selects the default broker connection for execution."""

from __future__ import annotations

from typing import Any

from backend.integrations.base import BrokerAdapter, InternalOrder
from backend.integrations.registry import get_broker_adapter, get_default_broker_provider, get_execution_mode


class BrokerRouter:
    def __init__(self, provider: str | None = None) -> None:
        self.provider = provider or get_default_broker_provider()

    def adapter(self) -> BrokerAdapter:
        return get_broker_adapter(self.provider)

    async def submit(self, order: InternalOrder) -> dict[str, Any]:
        order.mode = get_execution_mode()
        return await self.adapter().submit_order(order)

    async def health(self) -> dict[str, Any]:
        return await self.adapter().health()


_router: BrokerRouter | None = None


def get_broker_router() -> BrokerRouter:
    global _router
    if _router is None:
        _router = BrokerRouter()
    return _router
