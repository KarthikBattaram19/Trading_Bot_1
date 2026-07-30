"""Build intended multi-leg opening structures for Phase 1 auto-completion.

After an entry fills, remaining intended opening legs may be submitted without
operator consent, but must pass the same open-trade gates as the first entry
(``Docs/Paper_Simulator.md`` Phase 1 multi-leg completion).
"""

from __future__ import annotations

from typing import Any

from backend.paper_sim.models import PaperLegRequest, PaperSide

# Strategy tags that imply a multi-leg opening structure.
_SIMPLE_VOL_TAGS = frozenset({"simple_vol", "simple_volatility"})
_GAMMA_TAGS = frozenset({"gamma", "gamma_scalping", "gamma_scalp"})
_VEGA_TAGS = frozenset({"vega", "vega_scalping", "vega_scalp"})
_STOCK_HEDGE_TAGS = _SIMPLE_VOL_TAGS | _GAMMA_TAGS | _VEGA_TAGS


def normalize_strategy_tag(tag: str | None) -> str | None:
    if not tag:
        return None
    t = tag.strip().lower().replace("-", "_").replace(" ", "_")
    if t in _SIMPLE_VOL_TAGS:
        return "simple_volatility"
    if t in _GAMMA_TAGS:
        return "gamma_scalping"
    if t in _VEGA_TAGS:
        return "vega_scalping"
    return t


def strategy_implies_multi_leg(strategy_tag: str | None) -> bool:
    return normalize_strategy_tag(strategy_tag) in {
        "simple_volatility",
        "gamma_scalping",
        "vega_scalping",
    }


def _option_type(symbol: str) -> str | None:
    upper = symbol.upper()
    if upper.endswith("CE"):
        return "CE"
    if upper.endswith("PE"):
        return "PE"
    return None


def _is_cash_leg(exchange: str, symbol: str) -> bool:
    if exchange.upper() not in {"NSE", "BSE"}:
        return False
    return _option_type(symbol) is None


def _leg_key(symbol: str, side: str | PaperSide, exchange: str) -> str:
    side_v = side.value if isinstance(side, PaperSide) else str(side)
    return f"{exchange.upper()}:{symbol.upper()}:{side_v.lower()}"


def missing_intended_legs(
    *,
    current_legs: list[Any],
    intended_legs: list[PaperLegRequest],
) -> list[PaperLegRequest]:
    """Return intended legs not yet present on the position (by exchange/symbol/side)."""
    present: set[str] = set()
    for leg in current_legs:
        symbol = getattr(leg, "symbol", None) or leg.get("symbol")  # type: ignore[union-attr]
        exchange = getattr(leg, "exchange", None) or leg.get("exchange")  # type: ignore[union-attr]
        side = getattr(leg, "side", None) or leg.get("side")  # type: ignore[union-attr]
        if symbol and exchange and side is not None:
            present.add(_leg_key(str(symbol), side, str(exchange)))
    missing: list[PaperLegRequest] = []
    for intended in intended_legs:
        key = _leg_key(intended.symbol, intended.side, intended.exchange)
        if key not in present:
            missing.append(intended)
    return missing


def build_intended_legs_from_entry(
    *,
    strategy_tag: str | None,
    underlying: str | None,
    entry_legs: list[PaperLegRequest],
    feed: Any,
    prefer_stock_hedge: bool = True,
) -> list[PaperLegRequest]:
    """
    Infer the bot's intended multi-leg opening plan from strategy + first entry.

    - simple_volatility: long ATM CE + PE (add missing option side)
    - gamma / vega with stock hedge: long option(s) + cash underlying hedge
    - If entry already has 2+ legs, treat that basket as the intended structure
    """
    if len(entry_legs) >= 2:
        return list(entry_legs)

    if not strategy_implies_multi_leg(strategy_tag):
        return list(entry_legs)

    norm = normalize_strategy_tag(strategy_tag)
    intended = list(entry_legs)
    if not entry_legs:
        return intended

    first = entry_legs[0]
    qty = int(first.quantity)

    # Pair the opposite option for simple vol (straddle shape).
    if norm == "simple_volatility" and not _is_cash_leg(first.exchange, first.symbol):
        ot = _option_type(first.symbol)
        record = None
        if first.symbol_token:
            record = feed.resolve(symboltoken=first.symbol_token)
        if record is None:
            record = feed.resolve(exchange=first.exchange, tradingsymbol=first.symbol)
        if record is not None and ot is not None:
            want = "PE" if ot == "CE" else "CE"
            pair = _find_matching_option(
                feed,
                name=(record.name or underlying or "").upper(),
                expiry=record.expiry,
                strike=float(record.strike or 0.0),
                option_type=want,
            )
            if pair is not None:
                intended.append(
                    PaperLegRequest(
                        symbol=pair.tradingsymbol,
                        side=first.side,
                        quantity=qty,
                        exchange=pair.exchange,
                        symbol_token=pair.symboltoken,
                        option_type=want,  # type: ignore[arg-type]
                        strike=float(pair.strike) if pair.strike is not None else None,
                        expiry=pair.expiry,
                    )
                )

    # Stock hedge for strategies that delta-hedge with underlying.
    if prefer_stock_hedge and norm in {"simple_volatility", "gamma_scalping", "vega_scalping"}:
        und = (underlying or "").upper()
        if und and not any(_is_cash_leg(lg.exchange, lg.symbol) for lg in intended):
            # Only add stock hedge when construction expects it and we have an option entry.
            has_option = any(
                not _is_cash_leg(lg.exchange, lg.symbol) for lg in intended
            )
            if has_option and norm != "simple_volatility":
                # simple_vol default in playbook is often options straddle; stock is optional.
                # gamma/vega with stock hedge: add underlying lot-sized by option contracts.
                stock = feed.resolve(exchange="NSE", tradingsymbol=und)
                if stock is None:
                    stock = feed.resolve(tradingsymbol=und)
                if stock is not None:
                    # Hedge share count ≈ option quantity (India lot already in option qty).
                    hedge_qty = max(qty, 1)
                    # Long options → short stock to neutralize; short options → long stock.
                    hedge_side = (
                        PaperSide.sell if first.side == PaperSide.buy else PaperSide.buy
                    )
                    intended.append(
                        PaperLegRequest(
                            symbol=stock.tradingsymbol,
                            side=hedge_side,
                            quantity=hedge_qty,
                            exchange=stock.exchange,
                            symbol_token=stock.symboltoken,
                        )
                    )

    return intended


def _find_matching_option(
    feed: Any,
    *,
    name: str,
    expiry: str | None,
    strike: float,
    option_type: str,
) -> Any | None:
    if not name or strike <= 0:
        return None
    options = feed.list_options(name=name, exchange="NFO", expiry=expiry, limit=500)
    best = None
    best_dist = float("inf")
    for rec in options:
        sym = (rec.tradingsymbol or "").upper()
        if not sym.endswith(option_type.upper()):
            continue
        if expiry and rec.expiry and str(rec.expiry).upper() != str(expiry).upper():
            continue
        rec_strike = float(rec.strike or 0.0)
        dist = abs(rec_strike - strike)
        if dist < best_dist:
            best_dist = dist
            best = rec
    return best
