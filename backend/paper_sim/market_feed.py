"""Market-data-only bridge for the paper simulator.

Uses ICICI Direct Breeze LTP + instrument master (scrip master). Never imports
or calls order APIs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from backend.integrations.icici_direct.instrument_master import InstrumentMaster, get_instrument_master
from backend.integrations.icici_direct.market_data import (
    IciciDirectMarketDataAdapter,
    get_market_data_adapter,
)
from backend.integrations.icici_direct.models import InstrumentRecord, NormalizedTick
from backend.paper_sim.freshness import instrument_master_age_sec


class MarketQuoteFeed(Protocol):
    """Minimal feed contract so paper_sim can be tested without ICICI Direct."""

    async def ensure_instruments(self, *, max_age_sec: float | None = None) -> int: ...

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

    async def ensure_instruments(self, *, max_age_sec: float | None = None) -> int:
        """Load scrip master; force refresh when empty or older than ``max_age_sec``."""
        age = instrument_master_age_sec(self._instruments.loaded_at)
        needs_refresh = self._instruments.count == 0
        if max_age_sec is not None and (age is None or age > max_age_sec):
            needs_refresh = True
        if not needs_refresh:
            return self._instruments.count
        client = await self._md.session_manager.ensure_session()
        return await self._instruments.refresh(client)

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

    @property
    def instruments_loaded_at(self) -> datetime | None:
        return self._instruments.loaded_at

    def health(self) -> dict:
        md = self._md.health()
        age = instrument_master_age_sec(self._instruments.loaded_at)
        return {
            "feed": "icici_direct_data_only",
            "execution_coupled": False,
            "instrument_master_age_sec": age,
            "instrument_count": self._instruments.count,
            "instruments_loaded_at": (
                self._instruments.loaded_at.isoformat()
                if self._instruments.loaded_at
                else None
            ),
            "ws_connected": bool(md.get("ws_connected")),
            "ws_sub_second_fresh": bool(
                (md.get("ws") or {}).get("sub_second_fresh")
            ),
            "market_data": md,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
