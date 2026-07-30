"""Market-data-only bridge for the paper simulator.

Uses ICICI Direct Breeze LTP + instrument master. Never imports or calls order APIs.
"""

from __future__ import annotations

from typing import Protocol

from backend.integrations.icici_direct.instrument_master import InstrumentMaster, get_instrument_master
from backend.integrations.icici_direct.market_data import (
    IciciDirectMarketDataAdapter,
    get_market_data_adapter,
)
from backend.integrations.icici_direct.models import InstrumentRecord, NormalizedTick


class MarketQuoteFeed(Protocol):
    """Minimal feed contract so paper_sim can be tested without ICICI Direct."""

    async def ensure_instruments(self) -> int: ...

    async def get_ltp(
        self,
        exchange: str,
        tradingsymbol: str,
        symboltoken: str | None = None,
    ) -> NormalizedTick: ...

    def list_options(
        self,
        *,
        name: str,
        exchange: str = "NFO",
        expiry: str | None = None,
        limit: int = 500,
    ) -> list[InstrumentRecord]: ...

    def resolve(
        self,
        *,
        exchange: str | None = None,
        tradingsymbol: str | None = None,
        symboltoken: str | None = None,
    ) -> InstrumentRecord | None: ...


class IciciDirectDataOnlyFeed:
    """
    Read-only ICICI Direct marks for paper trading.

    Separation rule: this class may call market-data / instrument-master only.
    It must never call place_order, cancel_order, or any execution path.
    """

    def __init__(
        self,
        market_data: IciciDirectMarketDataAdapter | None = None,
        instruments: InstrumentMaster | None = None,
    ) -> None:
        self._md = market_data or get_market_data_adapter()
        self._instruments = instruments or get_instrument_master()

    async def ensure_instruments(self) -> int:
        return await self._md.ensure_instruments()

    async def get_ltp(
        self,
        exchange: str,
        tradingsymbol: str,
        symboltoken: str | None = None,
    ) -> NormalizedTick:
        return await self._md.get_ltp(exchange, tradingsymbol, symboltoken)

    def list_options(
        self,
        *,
        name: str,
        exchange: str = "NFO",
        expiry: str | None = None,
        limit: int = 500,
    ) -> list[InstrumentRecord]:
        return self._instruments.list_options(
            name=name, exchange=exchange, expiry=expiry, limit=limit
        )

    def resolve(
        self,
        *,
        exchange: str | None = None,
        tradingsymbol: str | None = None,
        symboltoken: str | None = None,
    ) -> InstrumentRecord | None:
        return self._instruments.resolve(
            exchange=exchange, tradingsymbol=tradingsymbol, symboltoken=symboltoken
        )

    def health(self) -> dict:
        md = self._md.health()
        return {
            "feed": "icici_direct_data_only",
            "execution_coupled": False,
            "market_data": md,
        }
