"""Option-chain assembly from ICICI Direct scrip master + optional LTP marks."""

from __future__ import annotations

from datetime import datetime, timezone

from backend.paper_sim.freshness import evaluate_tick, instrument_master_age_sec, tick_age_sec
from backend.paper_sim.market_feed import MarketQuoteFeed
from backend.paper_sim.models import OptionChainContract, OptionChainSnapshot

_INDEX_UNDERLYINGS = frozenset(
    {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"}
)


def _option_type(symbol: str) -> str | None:
    s = symbol.upper()
    if s.endswith("CE"):
        return "CE"
    if s.endswith("PE"):
        return "PE"
    return None


def _prefer_near_spot(
    records: list,
    *,
    spot: float | None,
    max_contracts: int,
) -> list:
    """Keep CE/PE pairs nearest to spot when we have more contracts than the limit."""
    if spot is None or len(records) <= max_contracts:
        return records[:max_contracts]

    scored: list[tuple[float, object]] = []
    for record in records:
        strike = float(record.strike) if record.strike is not None else spot
        scored.append((abs(strike - spot), record))
    scored.sort(key=lambda x: (x[0], getattr(x[1], "tradingsymbol", "")))
    return [r for _, r in scored[:max_contracts]]


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
    option_stale_threshold_sec: float = 120.0,
    quote_stale_threshold_sec: float = 60.0,
    instrument_master_max_age_sec: float | None = 86_400.0,
) -> OptionChainSnapshot:
    """
    Build an option chain from the scrip master, optionally enriching with LTP.

    Marks path: instrument master (SecurityMaster) + ICICI Direct REST quotes.
    Does not call Breeze ``place_order``.
    """
    await feed.ensure_instruments(max_age_sec=instrument_master_max_age_sec)

    und = underlying.upper().strip()
    # Auto-resolve cash spot for equity underlyings (not indices).
    resolved_spot_symbol = spot_symbol
    if resolved_spot_symbol is None and und not in _INDEX_UNDERLYINGS:
        resolved_spot_symbol = und

    spot_ltp: float | None = None
    spot_age: float | None = None
    if resolved_spot_symbol:
        try:
            tick = await feed.get_ltp(spot_exchange, resolved_spot_symbol)
            spot_ltp = tick.ltp if tick.ltp > 0 else None
            spot_age = tick_age_sec(tick)
            # Spot itself must pass quote freshness when LTP enrichment is on.
            if include_ltp and spot_ltp is not None:
                detail = evaluate_tick(tick, threshold_sec=quote_stale_threshold_sec)
                if detail.stale:
                    spot_ltp = None
                    spot_age = detail.age_sec
        except Exception:  # noqa: BLE001 — spot is optional enrichment
            spot_ltp = None
            spot_age = None

    # Pull a wider window so ATM preference can trim to max_contracts.
    fetch_limit = max(max_contracts * 3, max_contracts)
    records = feed.list_options(
        name=und, exchange=exchange, expiry=expiry, limit=fetch_limit
    )
    records = _prefer_near_spot(records, spot=spot_ltp, max_contracts=max_contracts)

    contracts: list[OptionChainContract] = []
    stale_contracts: list[str] = []
    now = datetime.now(timezone.utc)

    for record in records:
        ltp: float | None = None
        if include_ltp:
            try:
                tick = await feed.get_ltp(
                    record.exchange, record.tradingsymbol, record.symboltoken
                )
                detail = evaluate_tick(
                    tick, threshold_sec=option_stale_threshold_sec, now=now
                )
                if detail.stale:
                    stale_contracts.append(record.tradingsymbol)
                    ltp = None
                else:
                    ltp = tick.ltp
            except Exception:  # noqa: BLE001
                stale_contracts.append(record.tradingsymbol)
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

    master_age = None
    loaded_at = getattr(feed, "instruments_loaded_at", None)
    if callable(loaded_at):
        loaded_at = loaded_at()
    master_age = instrument_master_age_sec(loaded_at, now=now)

    marks_fresh: bool | None = None
    if include_ltp:
        marks_fresh = len(stale_contracts) == 0 and len(contracts) > 0

    return OptionChainSnapshot(
        underlying=und,
        exchange=exchange.upper(),
        expiry=expiry,
        spot_ltp=spot_ltp,
        contracts=contracts,
        as_of=now,
        source="icici_direct_scrip_master",
        marks_fresh=marks_fresh,
        stale_contracts=stale_contracts,
        spot_age_sec=spot_age,
        instrument_master_age_sec=master_age,
    )
