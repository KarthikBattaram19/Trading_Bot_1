"""Shared broker adapter contract (architecture.md §11.2)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ExecutionMode(str, Enum):
    shadow = "shadow"
    paper = "paper"
    live = "live"


class OrderLeg(BaseModel):
    leg_id: int
    symbol: str
    side: str  # buy | sell
    quantity: int
    order_type: str = "limit"  # market | limit | stop
    limit_price: float | None = None
    stop_price: float | None = None
    exchange: str | None = None
    symbol_token: str | None = None
    product: str | None = None
    type: str | None = None  # call | put | equity
    strike: float | None = None
    expiration: str | None = None


class InternalOrder(BaseModel):
    internal_order_id: str
    strategy_id: str | None = None
    signal_id: str | None = None
    underlying_symbol: str | None = None
    mode: ExecutionMode = ExecutionMode.shadow
    status: str = "pending"
    legs: list[OrderLeg] = Field(default_factory=list)
    order_tag: str | None = None


class BrokerAdapter(ABC):
    """Broker-agnostic execution interface."""

    provider: str

    @abstractmethod
    async def authenticate(self) -> dict[str, Any]:
        ...

    @abstractmethod
    async def submit_order(self, order: InternalOrder) -> dict[str, Any]:
        ...

    @abstractmethod
    async def cancel_order(self, order_id: str, *, variety: str = "NORMAL") -> dict[str, Any]:
        ...

    @abstractmethod
    async def get_positions(self) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    async def get_account(self) -> dict[str, Any]:
        ...

    @abstractmethod
    async def get_order_status(self, order_id: str) -> dict[str, Any]:
        ...

    @abstractmethod
    async def health(self) -> dict[str, Any]:
        ...
