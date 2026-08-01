"""
Instrument recommendation engine.

Analyzes feed data per Docs/Trading_Parameters.md, applies strategy selection
per Docs/Trading_Strategies.md Table SH-4, ranks candidates, returns top 3.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.integrations.icici_direct.instrument_master import (
    data_feed_bindings_for,
    get_instrument_master,
)
from backend.models.recommendations import (
    GateResult,
    HedgeInsight,
    InstrumentRecommendation,
    MarketNewsSummary,
    ParameterSnapshot,
    RecommendationResponse,
    ScoreBreakdown,
    StrategySelectionLogic,
    StrategyType,
    TradeEconomicsInsight,
)
from backend.quant.signals.garch import forecast_garch_11, log_returns_from_prices
from backend.quant.signals.iv_zscore import compute_iv_zscore
from backend.services.feed_health import get_feed_sources
from backend.services.learning_service import get_learning_service
from backend.services.market_news import get_market_news
from backend.services.strategy_selection import (
    QuantRegimeInputs,
    select_strategy_sh4,
)
from backend.services.universe_enrichment import (
    EnrichmentStats,
    get_universe_enricher,
    live_marks_to_candidate_fields,
)

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "trading_parameters.defaults.json"

# Offline fixture metrics keyed by G11 NSE/display symbol (marks enrichment).
_DEMO_SPECS: list[tuple] = [
    ("RELIANCE", 982.5, 0.24, -2.3, None, 185, 12500, 22000, 1.2, 22, 0.018, False),
    ("TATASTEEL", 142.8, 0.31, -2.6, None, 42, 8900, 12500, 1.8, 18, 0.022, False),
    ("INFY", 1680.0, 0.29, -1.8, 1, 210, 15200, 28000, 1.1, 25, 0.015, False),
    ("SBIN", 812.4, 0.27, None, None, 95, 22000, 35000, 0.9, 20, 0.012, False),
    ("HDFCBANK", 945.0, 0.22, None, 3, 120, 18500, 18500, 1.0, 28, 0.009, False),
    ("ITC", 428.5, 0.26, -2.1, None, 68, 31000, 42000, 0.7, 15, 0.011, False),
    ("NIFTY", 24500.0, 0.18, -2.4, None, 145, 45000, 80000, 0.5, 7, 0.014, False),
    ("BANKBARODA", 245.6, 0.35, None, None, 55, 9800, 8000, 2.3, 12, 0.028, False),
]
_DEMO_BY_SYMBOL = {row[0]: row for row in _DEMO_SPECS}


@dataclass
class InstrumentCandidate:
    symbol: str
    und_price: float
    iv_annualized: float
    garch_forecast: float
    iv_z_score: float | None
    days_to_earnings: int | None
    atm_premium_inr: float
    volume: int
    open_interest: int
    spread_pct: float
    dte: int
    realized_vol_intraday: float | None
    garch_distorted: bool
    price_history: list[float]
    marks_source: str = "stub"  # live | demo | stub


def _load_config() -> dict[str, Any]:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _garch_forecast(log_returns: list[float], cfg: dict[str, Any]) -> tuple[float, bool]:
    """GARCH(1,1) annualized vol per Trading_Parameters Part H (Phase 1.5 module)."""
    g = cfg["garch_forecast"]
    result = forecast_garch_11(
        log_returns,
        gamma=float(g["gamma_weight"]),
        alpha=float(g["alpha_weight"]),
        beta=float(g["beta_weight"]),
        annualization_factor=int(g["annualization_factor"]),
        min_observations=int(g.get("min_observations", 20)),
    )
    if result.usable and result.sigma_annual is not None:
        return result.sigma_annual, result.garch_distorted
    # Fallback for demo universe when series too short — still mark distorted (Q-14)
    return 0.28, True


def _iv_z_for_demo(iv: float, target_z: float | None, cfg: dict[str, Any]) -> float | None:
    """Build a synthetic intraday IV series so packet z-scores come from Part N4 math."""
    if target_z is None:
        return None
    zcfg = cfg.get("iv_zscore") or {}
    min_obs = int(zcfg.get("min_observations", 5))
    std = 0.02
    mean = iv - target_z * std
    # Alternating mean±std → sample std ≈ std; current_iv=iv ⇒ z ≈ target_z
    series = [mean - std, mean + std] * max(min_obs, 15)
    result = compute_iv_zscore(
        series,
        current_iv=iv,
        min_observations=min_obs,
        entry_z_threshold=float(
            zcfg.get(
                "entry_z_threshold",
                cfg["strategies"]["vega_scalping"]["iv_signal"]["entry_z_threshold"],
            )
        ),
    )
    return result.iv_z_score if result.usable else None


def _candidate_from_spec(row: tuple, cfg: dict[str, Any]) -> InstrumentCandidate:
    symbol, price, iv, z, de, prem, vol, oi, spread, dte, rv, distorted = row
    history = [price * (1 + 0.01 * math.sin(i / 3)) for i in range(60)]
    log_returns = log_returns_from_prices(history)
    garch, garch_dist = _garch_forecast(log_returns, cfg)
    if iv == 0:
        iv = garch * 0.92
    iv_z = _iv_z_for_demo(iv, z, cfg)
    return InstrumentCandidate(
        symbol=symbol,
        und_price=price,
        iv_annualized=iv,
        garch_forecast=garch,
        iv_z_score=iv_z,
        days_to_earnings=de,
        atm_premium_inr=prem,
        volume=vol,
        open_interest=oi,
        spread_pct=spread,
        dte=dte,
        realized_vol_intraday=rv,
        garch_distorted=distorted or garch_dist,
        price_history=history,
        marks_source="demo",
    )


def _stub_candidate(symbol: str, cfg: dict[str, Any]) -> InstrumentCandidate:
    """Universe member without enriched marks — fails retail gates until live LTP/IV land."""
    history = [1.0 for _ in range(5)]
    garch, garch_dist = _garch_forecast(log_returns_from_prices(history), cfg)
    return InstrumentCandidate(
        symbol=symbol,
        und_price=0.0,
        iv_annualized=0.0,
        garch_forecast=garch,
        iv_z_score=None,
        days_to_earnings=None,
        atm_premium_inr=999.0,
        volume=0,
        open_interest=0,
        spread_pct=99.0,
        dte=0,
        realized_vol_intraday=None,
        garch_distorted=True or garch_dist,
        price_history=history,
        marks_source="stub",
    )


def _candidate_from_live(symbol: str, fields: dict[str, Any]) -> InstrumentCandidate:
    return InstrumentCandidate(**{**fields, "symbol": symbol, "marks_source": "live"})


def _demo_universe(cfg: dict[str, Any] | None = None) -> list[InstrumentCandidate]:
    cfg = cfg or _load_config()
    return [_candidate_from_spec(row, cfg) for row in _DEMO_SPECS]


async def _ensure_fno_underlyings() -> tuple[list[str], str]:
    """Load ICICI Direct NFO underlyings for G11–G12 feed-bound universe.

    Returns (symbols, source_note).
    """
    master = get_instrument_master()
    if not master.list_fno_underlyings():
        try:
            from backend.integrations.icici_direct.market_data import get_market_data_adapter

            await get_market_data_adapter().ensure_instruments()
        except Exception as exc:  # noqa: BLE001
            logger.warning("FNO instrument master refresh failed: %s", exc)
            try:
                await master.refresh_public()
            except Exception as exc2:  # noqa: BLE001
                logger.warning("Public SecurityMaster.zip refresh failed: %s", exc2)

    underlyings = master.list_fno_underlyings()
    if underlyings:
        return underlyings, "icici_direct_fonsescripmaster"
    return [row[0] for row in _DEMO_SPECS], "demo_fallback"


async def _build_universe() -> tuple[
    list[InstrumentCandidate],
    dict[str, dict[str, str]],
    str,
    EnrichmentStats | None,
]:
    """Feed-bound universe (G11–G12): all NSE F&O underlyings from ICICI Direct master.

    When ``recommendation_universe_enrichment.enabled`` is true, each underlying is
    marked with live NSE LTP + NFO option-chain ATM metrics (rate-limited).
    """
    cfg = _load_config()
    symbols, source = await _ensure_fno_underlyings()
    master = get_instrument_master()
    candidates: list[InstrumentCandidate] = []
    bindings: dict[str, dict[str, str]] = {}
    enrich_cfg = cfg.get("recommendation_universe_enrichment") or {}
    enrich_enabled = bool(enrich_cfg.get("enabled", True))
    enrich_stats: EnrichmentStats | None = None
    live_by_symbol: dict[str, Any] = {}

    if enrich_enabled and symbols and source.startswith("icici_direct"):
        try:
            enricher = get_universe_enricher(cfg)
            live_by_symbol, enrich_stats = await enricher.enrich_many(symbols)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Universe live enrichment failed: %s", exc)
            enrich_stats = EnrichmentStats(requested=len(symbols), failed=len(symbols))
            enrich_stats.errors.append(str(exc))

    for symbol in symbols:
        bindings[symbol] = master.feed_bindings_for(symbol) if master.count else data_feed_bindings_for(
            symbol
        )
        live = live_by_symbol.get(symbol.upper()) if live_by_symbol else None
        if live is not None:
            fields = live_marks_to_candidate_fields(live, cfg)
            candidates.append(_candidate_from_live(symbol, fields))
            continue

        demo = _DEMO_BY_SYMBOL.get(symbol)
        enrichment_total_fail = (
            enrich_enabled
            and enrich_stats is not None
            and enrich_stats.delivered == 0
        )
        # Demo fixtures only when enrichment is off, or the whole live pass failed.
        if demo is not None and (not enrich_enabled or enrichment_total_fail):
            candidates.append(_candidate_from_spec(demo, cfg))
        else:
            candidates.append(_stub_candidate(symbol, cfg))

    if not candidates:
        demo_cands = _demo_universe(cfg)
        for c in demo_cands:
            bindings[c.symbol] = data_feed_bindings_for(c.symbol)
        return demo_cands, bindings, "demo_fallback", enrich_stats

    return candidates, bindings, source, enrich_stats


def _structure_uses_underlying(strategy: StrategySelectionLogic, cfg: dict[str, Any]) -> bool:
    """Hard lock: recommendations never include the cash underlying leg."""
    return False


def _prefer_options_only_for_high_spot(
    c: InstrumentCandidate,
    strategy: StrategySelectionLogic,
    cfg: dict[str, Any],
) -> tuple[StrategySelectionLogic, bool]:
    """No-op retained for legacy callers; all recommendation paths are options-only."""
    return strategy, False


def _evaluate_gates(
    c: InstrumentCandidate,
    cfg: dict[str, Any],
    *,
    includes_underlying: bool = True,
) -> list[GateResult]:
    """Retail universe filters Part T + pre-trade gates I21."""
    f = cfg["option_universe_filters"]
    gates: list[GateResult] = []

    gates.append(
        GateResult(
            gate_id="OPTIONS_ONLY_REQUIRED",
            label="Recommendation construction is options-only",
            passed=not includes_underlying,
            detail="No cash underlying leg" if not includes_underlying else "Cash underlying leg requested",
            parameter_ref="options-only hard lock",
        )
    )

    prem_ok = c.atm_premium_inr < f["max_option_premium"]
    gates.append(
        GateResult(
            gate_id="T1",
            label=f"ATM premium < {f['max_option_premium']} INR",
            passed=prem_ok,
            detail=f"₹{c.atm_premium_inr:.2f}",
            parameter_ref="Trading_Parameters.md Part T — T1",
        )
    )

    liq_vol = c.volume >= f["min_volume"]
    gates.append(
        GateResult(
            gate_id="T13",
            label=f"Volume ≥ {f['min_volume']}",
            passed=liq_vol,
            detail=str(c.volume),
            parameter_ref="Trading_Parameters.md Part T — T13",
        )
    )

    liq_oi = c.open_interest >= f["min_open_interest"]
    gates.append(
        GateResult(
            gate_id="T14",
            label=f"Open interest ≥ {f['min_open_interest']}",
            passed=liq_oi,
            detail=str(c.open_interest),
            parameter_ref="Trading_Parameters.md Part T — T14",
        )
    )

    spread_ok = c.spread_pct <= f["max_spread_pct"]
    gates.append(
        GateResult(
            gate_id="T15",
            label=f"Spread ≤ {f['max_spread_pct']}% of mid",
            passed=spread_ok,
            detail=f"{c.spread_pct:.2f}%",
            parameter_ref="Trading_Parameters.md Part T — T15",
        )
    )

    dte_min = cfg["strategies"]["simple_volatility"]["option_selection"]["min_dte"]
    dte_ok = c.dte >= dte_min
    gates.append(
        GateResult(
            gate_id="L3.3",
            label=f"DTE ≥ {dte_min}",
            passed=dte_ok,
            detail=f"{c.dte} days",
            parameter_ref="Trading_Parameters.md Part L — L3.3",
        )
    )

    return gates


def _select_strategy(
    c: InstrumentCandidate,
    news: MarketNewsSummary,
    cfg: dict[str, Any],
) -> StrategySelectionLogic:
    """Cross-strategy decision matrix — Trading_Strategies.md Table SH-4 + news overlay."""
    return select_strategy_sh4(
        QuantRegimeInputs(
            symbol=c.symbol,
            iv_annualized=c.iv_annualized,
            garch_forecast=c.garch_forecast,
            iv_z_score=c.iv_z_score,
            days_to_earnings=c.days_to_earnings,
            realized_vol_intraday=c.realized_vol_intraday,
            garch_distorted=c.garch_distorted,
        ),
        news,
        cfg,
    )


def _score_candidate(
    c: InstrumentCandidate,
    strategy: StrategySelectionLogic,
    gates: list[GateResult],
    module_weight: float = 1.0,
) -> ScoreBreakdown:
    if strategy.selected_strategy == StrategyType.blocked:
        return ScoreBreakdown(
            base=0.0,
            strategy_boost=0.0,
            liquidity_boost=0.0,
            spread_penalty=0.0,
            failure_memory_penalty=0.0,
            module_weight_factor=module_weight,
            total=0.0,
            components=["Blocked strategy — score zero"],
        )
    if not all(g.passed for g in gates):
        failed = [g.gate_id for g in gates if not g.passed]
        return ScoreBreakdown(
            base=0.0,
            strategy_boost=0.0,
            liquidity_boost=0.0,
            spread_penalty=0.0,
            failure_memory_penalty=0.0,
            module_weight_factor=module_weight,
            total=0.0,
            components=[f"Gate fail: {', '.join(failed)}"],
        )

    base = 0.5
    strategy_boost = 0.0
    components = [f"Base eligibility {base:.2f}"]

    if strategy.selected_strategy == StrategyType.vega_scalping and c.iv_z_score:
        strategy_boost = min(0.4, abs(c.iv_z_score) * 0.1)
        components.append(
            f"Vega z-depth boost +{strategy_boost:.2f} (|z|={abs(c.iv_z_score):.2f})"
        )
    elif strategy.selected_strategy == StrategyType.simple_volatility:
        edge = c.garch_forecast - c.iv_annualized
        strategy_boost = min(0.35, edge * 2)
        components.append(
            f"Cheap-vol edge boost +{strategy_boost:.2f} (GARCH−IV={edge:.1%})"
        )
    elif strategy.selected_strategy == StrategyType.gamma_scalping:
        if strategy.entry_mode == "earnings_gap_mode":
            strategy_boost = 0.3
            components.append("Earnings-gap mode boost +0.30")
        elif strategy.entry_mode == "high_realized_vol_mode":
            strategy_boost = 0.25
            components.append("High realized-vol mode boost +0.25")
        else:
            strategy_boost = 0.15
            components.append("Gamma fallback boost +0.15")

    liquidity_boost = min(0.15, c.open_interest / 200000)
    components.append(f"OI liquidity boost +{liquidity_boost:.2f}")

    spread_penalty = c.spread_pct * 0.02
    components.append(f"Spread penalty −{spread_penalty:.2f} ({c.spread_pct:.2f}% mid)")

    raw = base + strategy_boost + liquidity_boost - spread_penalty
    # Module weight from continual learning attribution (§12.4)
    weighted = raw * module_weight
    if abs(module_weight - 1.0) > 0.001:
        components.append(
            f"Module weight ×{module_weight:.3f} (learning attribution) → {weighted:.3f}"
        )

    total = round(min(0.99, max(0.0, weighted)), 3)
    components.append(f"Total score {total:.3f} (capped at 0.99)")

    return ScoreBreakdown(
        base=base,
        strategy_boost=round(strategy_boost, 3),
        liquidity_boost=round(liquidity_boost, 3),
        spread_penalty=round(spread_penalty, 3),
        failure_memory_penalty=0.0,
        module_weight_factor=round(module_weight, 3),
        total=total,
        components=components,
    )


def _market_summary(c: InstrumentCandidate, strategy: StrategySelectionLogic) -> str:
    iv_vs = (
        "cheap"
        if c.iv_annualized < c.garch_forecast
        else "rich"
        if c.iv_annualized > c.garch_forecast * 1.05
        else "fair"
    )
    z_part = (
        f" Intraday IV z={c.iv_z_score:.2f}."
        if c.iv_z_score is not None
        else " No intraday IV z-score."
    )
    earn = (
        f" Earnings in {c.days_to_earnings}d."
        if c.days_to_earnings is not None
        else ""
    )
    rv = (
        f" Intraday RV={c.realized_vol_intraday:.1%}."
        if c.realized_vol_intraday is not None
        else ""
    )
    return (
        f"{c.symbol} spot ₹{c.und_price:.2f}; IV {c.iv_annualized:.1%} vs GARCH "
        f"{c.garch_forecast:.1%} ({iv_vs} vol). Scenario: {strategy.scenario_tag}."
        f"{z_part}{earn}{rv}"
    )


def _hedge_insight(
    strategy: StrategySelectionLogic,
    *,
    options_only: bool = False,
) -> HedgeInsight:
    st = strategy.selected_strategy
    if st == StrategyType.vega_scalping:
        return HedgeInsight(
            method="Delta-neutral ATM long vol; flatten same session",
            greek_targets="Δ≈0 · V+ · Θ ignored (intraday)",
            structure_note="Single ATM option; options-only delta hedge; no overnight carry (N6.5)",
        )
    if st == StrategyType.gamma_scalping:
        mode = strategy.entry_mode or "cheap_vol_mode"
        return HedgeInsight(
            method=f"Vega-neutral long gamma ({mode})",
            greek_targets="Δ≈0 · V≈0 · Γ+ · Θ−",
            structure_note="Near/far expiry same-strike; four-leg options-only structure",
        )
    if st == StrategyType.simple_volatility:
        return HedgeInsight(
            method="Delta-neutral long vega (cheap vol)",
            greek_targets="Δ≈0 · Γ+ · V+ · Θ−",
            structure_note="ATM option; options-only hedge; hold D+0/D+1",
        )
    return HedgeInsight(
        method="Blocked — no hedge",
        greek_targets="n/a",
        structure_note="Do not enter",
    )


def _economics_insight(c: InstrumentCandidate, cfg: dict[str, Any]) -> TradeEconomicsInsight:
    max_budget = float(cfg.get("risk", {}).get("max_trade_notional_inr", 100_000))
    # Rough retail margin proxy: premium × lot-proxy + buffer within INR 1L cap
    margin = min(max_budget, max(c.atm_premium_inr * 50, c.und_price * 10))
    slip = round(c.spread_pct * 0.5, 2)
    edge_note = (
        f"IV−GARCH edge {(c.garch_forecast - c.iv_annualized):.1%}; "
        f"premium ₹{c.atm_premium_inr:.0f} within T1 cap; "
        f"est. slippage ~{slip}% of mid from spread."
    )
    return TradeEconomicsInsight(
        margin_estimate_inr=round(margin, 0),
        max_trade_budget_inr=max_budget,
        atm_premium_inr=c.atm_premium_inr,
        estimated_slippage_pct=slip,
        net_edge_note=edge_note,
    )


def _insight_checklist(
    c: InstrumentCandidate,
    strategy: StrategySelectionLogic,
    gates: list[GateResult],
    event_risks: list[str],
    failure_modes: list[str],
) -> list[str]:
    """P1-aligned completeness checklist for the UI."""
    return [
        f"P1.1 Strategy: {strategy.selected_strategy.value}"
        + (f" / {strategy.entry_mode}" if strategy.entry_mode else ""),
        f"P1.2 Instrument: {c.symbol} @ ₹{c.und_price:.2f}",
        "P1.3 Market condition: summarized",
        "P1.4 Entry rationale: primary signal set",
        "P1.5 Hedge construction: method + Greek targets",
        "P1.6 Size & margin: within INR 1,00,000 retail cap",
        "P1.7 Exit plan: stop / target / time",
        f"P1.8 Event risks: {len(event_risks)} item(s)",
        f"P1.9 Failure modes: {len(failure_modes)} scenario bullet(s)",
        f"Gates: {sum(1 for g in gates if g.passed)}/{len(gates)} pass",
        f"Matrix: {strategy.cross_strategy_matrix_ref}",
    ]


def _why_this_rank(
    rank: int,
    rec: InstrumentRecommendation,
    peers: list[InstrumentRecommendation],
) -> str:
    if rank == 1:
        runner = peers[1] if len(peers) > 1 else None
        if runner:
            gap = rec.score - runner.score
            return (
                f"Rank #1 — highest score {rec.score:.2f} "
                f"(+{gap:.2f} vs #{runner.rank} {runner.underlying_symbol}). "
                f"Strategy edge: {rec.strategy.primary_signal}."
            )
        return f"Rank #1 — sole eligible candidate (score {rec.score:.2f})."
    prev = next((p for p in peers if p.rank == rank - 1), None)
    if prev:
        gap = prev.score - rec.score
        return (
            f"Rank #{rank} — score {rec.score:.2f}, "
            f"{gap:.2f} below #{prev.rank} {prev.underlying_symbol}. "
            f"Still eligible: {rec.strategy.primary_signal}."
        )
    return f"Rank #{rank} — score {rec.score:.2f}."


def _build_logic_trail(
    c: InstrumentCandidate,
    strategy: StrategySelectionLogic,
    gates: list[GateResult],
    cfg: dict[str, Any],
    *,
    includes_underlying: bool = True,
) -> list[str]:
    """Complete step-by-step logic for UI transparency."""
    steps = [
        f"1. Feed bind: underlying_symbol={c.symbol}, und_price=₹{c.und_price:.2f} (A4/A5)",
        "2. Options-only lock: recommendation construction uses option legs only",
        f"3. Liquidity T13–T15: vol={c.volume}, OI={c.open_interest}, spread={c.spread_pct:.2f}%",
        f"4. GARCH(1,1) forecast σ_annual={c.garch_forecast:.2%} (H10); mark IV={c.iv_annualized:.2%} (G4)",
    ]
    if c.iv_z_score is not None:
        steps.append(f"5. Intraday IV z-score={c.iv_z_score:.2f} (N4.4–N4.5)")
    else:
        steps.append("5. Intraday IV series: insufficient history for z-score (vega scalp blocked)")

    if c.days_to_earnings is not None:
        steps.append(f"6. Earnings calendar: DTE_event={c.days_to_earnings} (G6, M2.2)")

    steps.append(
        f"7. Strategy matrix ({strategy.cross_strategy_matrix_ref}): "
        f"→ {strategy.selected_strategy.value}"
        + (f" [{strategy.entry_mode}]" if strategy.entry_mode else "")
    )
    steps.append(f"8. Primary signal: {strategy.primary_signal}")

    failed = [g for g in gates if not g.passed]
    if failed:
        steps.append(f"9. GATE FAIL: {', '.join(g.gate_id for g in failed)} — excluded from ranking")
    else:
        steps.append("9. Options-only retail gates + DTE pass — eligible for ranking")

    if strategy.rejected_strategies:
        steps.append(f"10. Alternatives rejected: {'; '.join(strategy.rejected_strategies)}")
    if strategy.news_impact:
        steps.append(f"11. News overlay: {strategy.news_impact}")

    return steps


def _exit_plan(strategy: StrategySelectionLogic, cfg: dict[str, Any]) -> str:
    st = strategy.selected_strategy
    if st == StrategyType.vega_scalping:
        v = cfg["strategies"]["vega_scalping"]
        return (
            f"Target: IV mean reversion (N6.1). Stop: {v['iv_signal']['stop_z_threshold']}σ. "
            f"Flatten at session close (N6.5)."
        )
    if st == StrategyType.gamma_scalping:
        if strategy.entry_mode == "earnings_gap_mode":
            return "Close after earnings gap (M6). Re-neutralize delta/vega at breakeven."
        return "D+0 or D+1; re-hedge at gamma-theta breakeven (J2, M5.1)."
    if st == StrategyType.simple_volatility:
        return "D+0/D+1 hold (L7.1). Re-hedge at gamma-theta breakeven. Exit if IV keeps falling (L8)."
    return "Blocked — no entry"


async def generate_recommendations(
    news: MarketNewsSummary | None = None,
) -> RecommendationResponse:
    cfg = _load_config()
    now = datetime.now(timezone.utc)
    # A2: open WS Streaming 2.0 when credentials/session allow before reporting feeds.
    try:
        from backend.integrations.icici_direct.market_data import get_market_data_adapter
        from backend.integrations.icici_direct.session_manager import get_session_manager

        health = get_session_manager().health()
        if health.get("authenticated") or health.get("credentials_ready"):
            await get_market_data_adapter().ensure_ws_connected()
    except Exception:  # noqa: BLE001
        pass

    # Refresh analysis must re-ingest Market_News (bypass TTL cache) so the
    # NewsPanel / feed timestamps update with every recommendation cycle.
    if news is None:
        news = get_market_news(force_refresh=True)
    sources = get_feed_sources()
    learning = get_learning_service()

    universe, feed_bindings, universe_source, enrich_stats = await _build_universe()
    ranked: list[InstrumentRecommendation] = []
    passing = 0
    learning_hits = 0

    live_count = sum(1 for c in universe if c.marks_source == "live")
    stub_count = sum(1 for c in universe if c.marks_source == "stub")
    demo_count = sum(1 for c in universe if c.marks_source == "demo")

    for c in universe:
        strategy = _select_strategy(c, news, cfg)
        strategy, force_options_only = _prefer_options_only_for_high_spot(c, strategy, cfg)
        includes_underlying = _structure_uses_underlying(strategy, cfg) and not force_options_only
        gates = _evaluate_gates(c, cfg, includes_underlying=includes_underlying)
        weight = learning.module_weight(strategy.selected_strategy.value)
        score_bd = _score_candidate(c, strategy, gates, module_weight=weight)

        if all(g.passed for g in gates) and strategy.selected_strategy != StrategyType.blocked:
            passing += 1

        if score_bd.total <= 0:
            continue

        params = ParameterSnapshot(
            und_price=c.und_price,
            iv_annualized=c.iv_annualized,
            garch_forecast=c.garch_forecast,
            iv_z_score=c.iv_z_score,
            days_to_earnings=c.days_to_earnings,
            atm_premium_inr=c.atm_premium_inr,
            volume=c.volume,
            open_interest=c.open_interest,
            spread_pct=c.spread_pct,
            dte=c.dte,
            realized_vol_intraday=c.realized_vol_intraday,
            garch_distorted=c.garch_distorted,
        )

        event_risks = _event_risks(c, strategy, news)
        failure_modes = _failure_modes(strategy)
        confidence_before = min(0.95, score_bd.total + 0.05)

        # Temporary rec for failure-memory query (rank filled later)
        draft = InstrumentRecommendation(
            rank=0,
            underlying_symbol=c.symbol,
            score=score_bd.total,
            confidence=confidence_before,
            strategy=strategy,
            parameters=params,
            parameter_gates=gates,
            market_summary=_market_summary(c, strategy),
            entry_rationale=strategy.primary_signal,
            complete_logic=_build_logic_trail(
                c, strategy, gates, cfg, includes_underlying=includes_underlying
            ),
            score_breakdown=score_bd,
            hedge=_hedge_insight(strategy, options_only=not includes_underlying),
            economics=_economics_insight(c, cfg),
            exit_plan=_exit_plan(strategy, cfg),
            event_risks=event_risks,
            failure_modes=failure_modes,
            why_this_rank="",
            alternative_considered=(
                strategy.rejected_strategies[0] if strategy.rejected_strategies else None
            ),
            insight_checklist=_insight_checklist(
                c, strategy, gates, event_risks, failure_modes
            ),
        )

        insight = learning.build_learning_insight(draft, confidence_before)
        if insight.failure_matches:
            learning_hits += 1
            # Reflect penalty on score breakdown for UI transparency
            score_bd.failure_memory_penalty = insight.confidence_penalty
            score_bd.components.append(
                f"Failure-memory confidence penalty −{insight.confidence_penalty:.2f} "
                f"({len(insight.failure_matches)} similar loss(es) — §12.6)"
            )
            draft.complete_logic.append(
                f"12. Learning: {insight.learning_note}"
            )
        else:
            draft.complete_logic.append(f"12. Learning: {insight.learning_note}")

        draft.confidence = insight.confidence_after
        draft.learning = insight
        draft.score_breakdown = score_bd
        ranked.append(draft)

    min_confidence = float(
        cfg.get("execution_constraints", {}).get("min_recommendation_confidence", 0.80)
    )
    below_confidence = [r for r in ranked if r.confidence < min_confidence]
    ranked = [r for r in ranked if r.confidence >= min_confidence]

    ranked.sort(key=lambda r: r.score, reverse=True)
    top3 = ranked[:3]
    for i, rec in enumerate(top3, start=1):
        rec.rank = i
    for rec in top3:
        rec.why_this_rank = _why_this_rank(rec.rank, rec, top3)

    notes = [
        f"Scanned {len(universe)} instruments from feed-bound universe (G11–G12).",
        (
            "Universe source: ICICI Direct FONSEScripMaster "
            f"({universe_source}) — all NSE F&O underlyings with auto G12 bindings."
            if universe_source.startswith("icici_direct")
            else f"Universe source: {universe_source} (ICICI Direct FNO master unavailable)."
        ),
        (
            f"Marks coverage: live={live_count}, stub={stub_count}, demo={demo_count} "
            "(live = NSE LTP + NFO option-chain ATM)."
        ),
        f"{passing} passed all options-only retail gates (I21).",
        f"Confidence floor: only candidates with confidence ≥ {min_confidence:.0%} are recommended.",
        "Strategy selection follows Trading_Strategies.md Table SH-4 with Market_News overlay.",
        "Parameter gates sourced from Trading_Parameters.md Parts G, H, I, T, U.",
        "Each recommendation includes a complete P1 insight packet for operator review.",
        "Continual learning: failure memory + module weights applied (§12).",
    ]
    if enrich_stats is not None:
        notes.extend(enrich_stats.note_lines())
    if feed_bindings:
        sample_sym = next(iter(feed_bindings))
        sample_bind = feed_bindings[sample_sym]
        notes.append(
            f"G12 example ({sample_sym}): und_price={sample_bind.get('und_price')}, "
            f"option_chain={sample_bind.get('option_chain')} "
            f"({len(feed_bindings)} underlyings bound)."
        )
    if below_confidence:
        notes.append(
            f"{len(below_confidence)} candidate(s) scored but were excluded for "
            f"confidence < {min_confidence:.0%} "
            f"(best excluded: {max(r.confidence for r in below_confidence):.0%})."
        )
    if learning_hits:
        notes.append(
            f"Failure-memory matches on {learning_hits} candidate(s) — "
            "confidence penalized −0.10 where similar losses exist."
        )
    if news.macro_risk_flags:
        notes.append(f"News flags: {'; '.join(news.macro_risk_flags)}")
    if not news.news_not_blocking or news.kill_event or news.news_post_shock:
        notes.append(
            "News overlay gating SH-4 rows "
            f"(news_not_blocking={news.news_not_blocking}, "
            f"post_shock={news.news_post_shock}, kill_event={news.kill_event})."
        )
    if not top3:
        notes.append(
            f"No instruments met the ≥{min_confidence:.0%} confidence bar this cycle — "
            "no recommendations surfaced."
        )

    return RecommendationResponse(
        generated_at=now,
        feed_as_of=now,
        feed_sources=sources,
        market_news=news,
        universe_scanned=len(universe),
        candidates_passing_gates=passing,
        recommendations=top3,
        analysis_notes=notes,
    )


def _event_risks(
    c: InstrumentCandidate,
    strategy: StrategySelectionLogic,
    news: MarketNewsSummary,
) -> list[str]:
    risks: list[str] = []
    if c.days_to_earnings is not None and c.days_to_earnings <= 2:
        risks.append(f"Earnings in {c.days_to_earnings} day(s)")
    if news.news_event_imminent:
        risks.append("Market_News: earnings/company event imminent (U5)")
    if news.earnings_mentions > 2:
        risks.append("Broad earnings season — IV crush risk for long-vega")
    if news.news_post_shock or news.kill_event:
        risks.append("Post-shock / kill_event — model trades blocked (U6/U10)")
    if not news.news_not_blocking:
        risks.append("news_not_blocking=false — SH-4 rows gated (U4)")
    if c.spread_pct > 1.5:
        risks.append("Spread near cap — execution cost sensitivity")
    if strategy.selected_strategy == StrategyType.vega_scalping:
        risks.append("Must flatten same session (N6.5)")
    return risks or ["No elevated event risks identified"]


def _failure_modes(strategy: StrategySelectionLogic) -> list[str]:
    if strategy.selected_strategy == StrategyType.vega_scalping:
        return [
            "IV continues falling — stop at −3σ/−4σ",
            "Intraday stationarity breakdown (N4.7)",
            "Stale IV measurements",
        ]
    if strategy.selected_strategy == StrategyType.gamma_scalping:
        return [
            "Quiet market — theta dominates",
            "Term-structure distortion post-entry",
            "Post-gap Greek drift",
        ]
    if strategy.selected_strategy == StrategyType.simple_volatility:
        return [
            "IV does not rise toward GARCH forecast",
            "Theta bleed without gamma payment",
            "Hedge cost excessive",
        ]
    return ["Model blocked — do not trade"]
