"""Option-chain assembly for paper sim (data feed only)."""

from __future__ import annotations

from datetime import datetime, timezone

from backend.paper_sim.market_feed import MarketQuoteFeed
from backend.paper_sim.models import OptionChainContract, OptionChainSnapshot


def _option_type(symbol: str) -> str | None:
    s = symbol.upper()
    if s.endswith("CE"):
        return "CE"
    if s.endswith("PE"):
        return "PE"
    return None


async def build_option_chain(
    feed: MarketQuoteFeed,
    *,
    underlying: str,
    exchange: str = "NFO",
    expiry: str | None = None,
    include_ltp: bool = False,
    max_contracts: int = 80,
    spot_symbol: str | None = None,
    spot_exchange: str = "NSE",
) -> OptionChainSnapshot:
    await feed.ensure_instruments()
    records = feed.list_options(
        name=underlying, exchange=exchange, expiry=expiry, limit=max_contracts
    )

    spot_ltp: float | None = None
    if spot_symbol:
        try:
            tick = await feed.get_ltp(spot_exchange, spot_symbol)
            spot_ltp = tick.ltp
        except Exception:  # noqa: BLE001 — spot is optional enrichment
            spot_ltp = None

    contracts: list[OptionChainContract] = []
    for record in records[:max_contracts]:
        ltp: float | None = None
        if include_ltp:
            try:
                tick = await feed.get_ltp(
                    record.exchange, record.tradingsymbol, record.symboltoken
                )
                ltp = tick.ltp
            except Exception:  # noqa: BLE001
                ltp = None
        contracts.append(
            OptionChainContract(
                tradingsymbol=record.tradingsymbol,
                symboltoken=record.symboltoken,
                exchange=record.exchange,
                name=record.name,
                expiry=record.expiry,
                strike=record.strike,
                option_type=_option_type(record.tradingsymbol),  # type: ignore[arg-type]
                lotsize=record.lotsize,
                ltp=ltp,
            )
        )

    return OptionChainSnapshot(
        underlying=underlying.upper(),
        exchange=exchange.upper(),
        expiry=expiry,
        spot_ltp=spot_ltp,
        contracts=contracts,
        as_of=datetime.now(timezone.utc),
        source="icici_direct_data_only",
    )
