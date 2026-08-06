"""Build intended multi-leg opening structures for Phase 1 auto-completion.

After an entry fills, remaining intended opening legs may be submitted without
operator consent, but must pass the same open-trade gates as the first entry
(``Docs/Paper_Simulator.md`` Phase 1 multi-leg completion).

Options-only hard lock: intended plans never include NSE/BSE cash underlying legs.
"""

from __future__ import annotations

import logging
from math import isfinite
from typing import Any

from backend.paper_sim.config import PaperSimConfig
from backend.paper_sim.models import PaperLegRequest, PaperSide
from backend.quant.pricing.bsm import BSMInputs, option_greeks
from backend.services.universe_enrichment import _dte_from_expiry

logger = logging.getLogger(__name__)

# Strategy tags that imply a multi-leg opening structure.
_SIMPLE_VOL_TAGS = frozenset({"simple_vol", "simple_volatility"})
_GAMMA_TAGS = frozenset({"gamma", "gamma_scalping", "gamma_scalp"})
_VEGA_TAGS = frozenset({"vega", "vega_scalping", "vega_scalp"})


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
) -> list[PaperLegRequest]:
    """
    Infer the bot's intended multi-leg opening plan from strategy + first entry.

    - simple_volatility / vega_scalping: long ATM CE + PE (add missing option side)
    - gamma_scalping: four-leg NFO shape (straddle + second-strike CE/PE)
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

    if _is_cash_leg(first.exchange, first.symbol):
        return intended

    record = _resolve_option_record(feed, first, underlying)
    if record is None:
        return intended

    if norm in {"simple_volatility", "vega_scalping"}:
        _append_opposite_option_at_strike(
            intended,
            feed=feed,
            first=first,
            record=record,
            underlying=underlying,
            qty=qty,
        )
    elif norm == "gamma_scalping":
        _append_opposite_option_at_strike(
            intended,
            feed=feed,
            first=first,
            record=record,
            underlying=underlying,
            qty=qty,
        )
        _append_second_strike_option_pair(
            intended,
            feed=feed,
            first=first,
            record=record,
            underlying=underlying,
            qty=qty,
        )

    return intended


def _resolve_option_record(
    feed: Any, first: PaperLegRequest, underlying: str | None
) -> Any | None:
    if first.symbol_token:
        record = feed.resolve(symboltoken=first.symbol_token)
        if record is not None:
            return record
    return feed.resolve(exchange=first.exchange, tradingsymbol=first.symbol)


def _append_opposite_option_at_strike(
    intended: list[PaperLegRequest],
    *,
    feed: Any,
    first: PaperLegRequest,
    record: Any,
    underlying: str | None,
    qty: int,
) -> None:
    ot = _option_type(first.symbol)
    if ot is None:
        return
    want = "PE" if ot == "CE" else "CE"
    if any(
        not _is_cash_leg(lg.exchange, lg.symbol)
        and _option_type(lg.symbol) == want
        and float(lg.strike or 0) == float(record.strike or 0)
        for lg in intended
    ):
        return
    pair = _find_matching_option(
        feed,
        name=(record.name or underlying or "").upper(),
        expiry=record.expiry,
        strike=float(record.strike or 0.0),
        option_type=want,
    )
    if pair is None:
        return
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


def _append_second_strike_option_pair(
    intended: list[PaperLegRequest],
    *,
    feed: Any,
    first: PaperLegRequest,
    record: Any,
    underlying: str | None,
    qty: int,
) -> None:
    """Add CE+PE at the nearest listed strike different from the entry (four-leg gamma)."""
    base_strike = float(record.strike or 0.0)
    if base_strike <= 0:
        return
    name = (record.name or underlying or "").upper()
    options = feed.list_options(name=name, exchange="NFO", expiry=record.expiry, limit=500)
    alt_strikes: set[float] = set()
    for rec in options:
        sym = (rec.tradingsymbol or "").upper()
        if not (sym.endswith("CE") or sym.endswith("PE")):
            continue
        st = float(rec.strike or 0.0)
        if st > 0 and st != base_strike:
            alt_strikes.add(st)
    if not alt_strikes:
        return
    alt_strike = min(alt_strikes, key=lambda s: abs(s - base_strike))
    for want in ("CE", "PE"):
        if any(
            not _is_cash_leg(lg.exchange, lg.symbol)
            and _option_type(lg.symbol) == want
            and float(lg.strike or 0) == alt_strike
            for lg in intended
        ):
            continue
        pair = _find_matching_option(
            feed,
            name=name,
            expiry=record.expiry,
            strike=alt_strike,
            option_type=want,
        )
        if pair is None:
            continue
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


def _resolve_far_expiry(
    feed: Any,
    *,
    name: str,
    near_expiry: str | None,
    min_gap_days: int,
) -> tuple[str, int] | None:
    """Nearest listed expiry with DTE >= near-leg DTE + ``min_gap_days``.

    Table GS-1: use a near/far separation comparable to the source's 35-DTE-
    vs-63-DTE reference pair; too small a gap leaves nothing to hedge with.
    """
    near_dte = _dte_from_expiry(near_expiry or "")
    records = feed.list_options(name=name, exchange="NFO", limit=5000)
    expiries: dict[str, int] = {}
    for rec in records:
        if not rec.expiry:
            continue
        dte = _dte_from_expiry(rec.expiry)
        key = rec.expiry
        if key not in expiries or dte < expiries[key]:
            expiries[key] = dte
    candidates = [
        (exp, dte) for exp, dte in expiries.items() if dte >= near_dte + min_gap_days
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[1], x[0]))
    return candidates[0]


async def _append_vega_neutral_far_dated_pair(
    intended: list[PaperLegRequest],
    *,
    feed: Any,
    first: PaperLegRequest,
    record: Any,
    underlying: str | None,
    qty: int,
    paper_sim_config: PaperSimConfig,
    min_gap_days: int,
) -> None:
    """Short a longer-dated CE/PE pair sized to zero portfolio vega.

    Table GS-4 steps 3-4: solve the short-dated/long-dated call pair for
    vega neutrality first, then mirror the identical quantity into puts
    (delta identity in step 4's callout) rather than re-solving both sides
    independently.
    """
    strike = float(record.strike or 0.0)
    if strike <= 0:
        return
    name = (record.name or underlying or "").upper()

    near_dte = _dte_from_expiry(record.expiry or "")
    far = _resolve_far_expiry(feed, name=name, near_expiry=record.expiry, min_gap_days=min_gap_days)
    if far is None:
        logger.warning(
            "gamma_scalping calendar skip: no far expiry >= near_dte(%d)+%d days for %s",
            near_dte,
            min_gap_days,
            name,
        )
        return
    far_expiry, far_dte = far

    und_rec = feed.resolve(exchange="NSE", tradingsymbol=(underlying or name).upper())
    if und_rec is None:
        und_rec = feed.resolve(tradingsymbol=(underlying or name).upper())
    if und_rec is None:
        logger.warning("gamma_scalping calendar skip: no underlying spot record for %s", name)
        return
    tick = await feed.get_ltp(und_rec.exchange, und_rec.tradingsymbol, und_rec.symboltoken)
    spot = float(tick.ltp)
    if spot <= 0:
        return

    def _greeks(days: float, option_type: str) -> dict[str, float]:
        inputs = BSMInputs.from_api(
            und_price=spot,
            strike=strike,
            days_to_expiry=days,
            int_rate=paper_sim_config.risk_free_rate_pct,
            div_yield=paper_sim_config.dividend_yield_pct,
            volatility=paper_sim_config.default_iv_annual_pct,
            option_type=option_type,  # type: ignore[arg-type]
        )
        return option_greeks(inputs)

    near_call = _greeks(near_dte, "call")
    far_call = _greeks(far_dte, "call")
    vega_far = far_call["vega"]
    if not isfinite(vega_far) or abs(vega_far) < 1e-9:
        logger.warning(
            "gamma_scalping calendar skip: degenerate far vega (%s) for %s far_expiry=%s",
            vega_far,
            name,
            far_expiry,
        )
        return

    near_lotsize = max(int(record.lotsize or 1), 1)
    near_contracts = max(int(qty // near_lotsize), 1) if qty >= near_lotsize else 1
    far_contracts = max(round(near_contracts * near_call["vega"] / vega_far), 1)

    appended: list[PaperLegRequest] = []
    for want in ("CE", "PE"):
        pair = _find_matching_option(feed, name=name, expiry=far_expiry, strike=strike, option_type=want)
        if pair is None:
            logger.warning(
                "gamma_scalping calendar skip leg: no %s at strike=%.2f expiry=%s for %s",
                want,
                strike,
                far_expiry,
                name,
            )
            continue
        far_lotsize = max(int(pair.lotsize or near_lotsize), 1)
        leg = PaperLegRequest(
            symbol=pair.tradingsymbol,
            side=PaperSide.sell,
            quantity=far_contracts * far_lotsize,
            exchange=pair.exchange,
            symbol_token=pair.symboltoken,
            option_type=want,  # type: ignore[arg-type]
            strike=float(pair.strike) if pair.strike is not None else None,
            expiry=pair.expiry,
        )
        intended.append(leg)
        appended.append(leg)

    if len(appended) == 2:
        near_put = _greeks(near_dte, "put")
        far_put = _greeks(far_dte, "put")
        residual_delta = near_contracts * (near_call["delta"] + near_put["delta"]) - far_contracts * (
            far_call["delta"] + far_put["delta"]
        )
        residual_vega = near_contracts * (near_call["vega"] + near_put["vega"]) - far_contracts * (
            far_call["vega"] + far_put["vega"]
        )
        logger.info(
            "gamma_scalping calendar solve symbol=%s strike=%.2f near_dte=%d far_dte=%d "
            "vega_near_call=%.4f vega_far_call=%.4f near_contracts=%d far_contracts=%d "
            "residual_delta=%.4f residual_vega=%.4f",
            name,
            strike,
            near_dte,
            far_dte,
            near_call["vega"],
            vega_far,
            near_contracts,
            far_contracts,
            residual_delta,
            residual_vega,
        )
