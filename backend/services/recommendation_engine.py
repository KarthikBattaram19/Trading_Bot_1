"""
Instrument recommendation engine.

Analyzes feed data per Docs/Trading_Parameters.md, applies strategy selection
per Docs/Trading_Strategies.md Table SH-4, ranks candidates, returns top 3.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
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
    StrategyCoverageStatus,
    StrategySelectionLogic,
    StrategyType,
    TradeEconomicsInsight,
)
from backend.quant.signals.garch import forecast_garch_11, log_returns_from_prices
from backend.quant.signals.iv_zscore import compute_iv_zscore
from backend.services.atm_liquidity import (
    AtmHistoryPoint,
    evaluate_atm_liquidity,
    live_from_aggregated,
)
from backend.services.atm_liquidity_history import AtmLiquidityHistoryStore
from backend.services.candle_history import fetch_daily_closes, fetch_realized_vol_intraday
from backend.services.earnings_calendar import EarningsCalendarStore, session_date_ist
from backend.services.feed_health import get_feed_sources
from backend.services.iv_history_store import IvHistoryStore
from backend.services.confidence_calibrator import ConfidenceCalibrator
from backend.services.learning_service import get_learning_service
from backend.services.market_news import get_market_news
from backend.services.quant_snapshot import (
    QuantSnapshot,
    build_quant_snapshot,
    snapshot_to_candidate_fields,
)
from backend.services.signals import _liquidity_gate_results, seed_atm_history_prior
from backend.services.strategy_coverage import evaluate_strategy_coverage
from backend.services.strategy_selection import (
    QuantRegimeInputs,
    select_strategy_sh4,
)
from backend.services.universe_enrichment import (
    EnrichmentStats,
    LiveMarks,
    get_universe_enricher,
)

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "trading_parameters.defaults.json"

# In-process response cache so /recommendations and /decisions do not re-scan
# ~200 FNO underlyings on every page load (Breeze rate limits make that a multi-minute hang).
_response_cache: RecommendationResponse | None = None
_response_cache_at: float | None = None
_response_cache_lock = asyncio.Lock()


def _response_cache_ttl_sec() -> float:
    try:
        section = (_load_config().get("recommendation_universe_enrichment") or {})
        return float(section.get("response_cache_ttl_sec", 90.0))
    except Exception:  # noqa: BLE001
        return 90.0


def reset_recommendation_response_cache_for_tests() -> None:
    global _response_cache, _response_cache_at
    _response_cache = None
    _response_cache_at = None


def _store_recommendation_response_cache(response: RecommendationResponse) -> None:
    global _response_cache, _response_cache_at
    _response_cache = response
    _response_cache_at = time.monotonic()


def peek_cached_recommendations() -> RecommendationResponse | None:
    """Return a still-fresh cached packet, or None."""
    if _response_cache is None or _response_cache_at is None:
        return None
    if (time.monotonic() - _response_cache_at) > _response_cache_ttl_sec():
        return None
    return _response_cache

# Offline fixture metrics keyed by G11 NSE/display symbol (marks enrichment).
_DEMO_SPECS: list[tuple] = [
    ("RELIANCE", 982.5, 0.24, -2.3, None, 185, 12500, 22000, 0.4, 22, 0.018, False),
    ("TATASTEEL", 142.8, 0.31, -2.6, None, 42, 8900, 22000, 0.4, 18, 0.022, False),
    ("INFY", 1680.0, 0.29, -1.8, 1, 210, 15200, 28000, 0.4, 25, 0.015, False),
    ("SBIN", 812.4, 0.27, None, None, 95, 22000, 35000, 0.4, 20, 0.012, False),
    ("HDFCBANK", 945.0, 0.22, None, 3, 120, 18500, 25000, 0.4, 28, 0.009, False),
    ("ITC", 428.5, 0.26, -2.1, None, 68, 31000, 42000, 0.4, 15, 0.011, False),
    ("NIFTY", 24500.0, 0.18, -2.4, None, 145, 45000, 80000, 0.4, 7, 0.014, False),
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
    atm_history_prior: list[AtmHistoryPoint] | None = None
    expiry_key: str | None = None


def _load_config() -> dict[str, Any]:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _garch_forecast(log_returns: list[float], cfg: dict[str, Any]) -> tuple[float | None, bool]:
    """GARCH(1,1) annualized vol — no silent 0.28 fallback (live-clean)."""
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
    return None, True


def _iv_z_for_demo(iv: float, target_z: float | None, cfg: dict[str, Any]) -> float | None:
    """Build a synthetic intraday IV series for offline fixture helpers only."""
    if target_z is None:
        return None
    zcfg = cfg.get("iv_zscore") or {}
    min_obs = int(zcfg.get("min_observations", 5))
    std = 0.02
    mean = iv - target_z * std
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
    """Test/offline fixture helper only — not used for production ranking."""
    symbol, price, iv, z, de, prem, vol, oi, spread, dte, rv, distorted = row
    history = [price * (1 + 0.01 * math.sin(i / 3)) for i in range(60)]
    log_returns = log_returns_from_prices(history)
    garch, garch_dist = _garch_forecast(log_returns, cfg)
    if garch is None:
        garch = 0.0
        garch_dist = True
    if iv == 0:
        iv = garch * 0.92 if garch else 0.0
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
        atm_history_prior=seed_atm_history_prior(vol, oi),
    )


def _stub_candidate(symbol: str, cfg: dict[str, Any]) -> InstrumentCandidate:
    """Non-ranking placeholder — not added to production recommendation candidates."""
    return InstrumentCandidate(
        symbol=symbol,
        und_price=0.0,
        iv_annualized=0.0,
        garch_forecast=0.0,
        iv_z_score=None,
        days_to_earnings=None,
        atm_premium_inr=999.0,
        volume=0,
        open_interest=0,
        spread_pct=99.0,
        dte=0,
        realized_vol_intraday=None,
        garch_distorted=True,
        price_history=[1.0],
        marks_source="stub",
    )


def _candidate_from_live(symbol: str, fields: dict[str, Any]) -> InstrumentCandidate:
    src = fields.pop("marks_source", "live")
    return InstrumentCandidate(**{**fields, "symbol": symbol, "marks_source": src})


def _demo_universe(cfg: dict[str, Any] | None = None) -> list[InstrumentCandidate]:
    """Offline fixture helper for unit tests — never used by production ranking."""
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
    # No demo symbol fallback for ranking — empty universe + coverage abort.
    return [], "empty_fno_master"


async def _build_universe() -> tuple[
    list[InstrumentCandidate],
    dict[str, dict[str, str]],
    str,
    EnrichmentStats | None,
    list[QuantSnapshot],
]:
    """Feed-bound universe with live-clean QuantSnapshots (no demo/stub ranking)."""
    cfg = _load_config()
    symbols, source = await _ensure_fno_underlyings()
    master = get_instrument_master()
    candidates: list[InstrumentCandidate] = []
    snapshots: list[QuantSnapshot] = []
    bindings: dict[str, dict[str, str]] = {}
    enrich_cfg = cfg.get("recommendation_universe_enrichment") or {}
    enrich_enabled = bool(enrich_cfg.get("enabled", True))
    snap_cfg = cfg.get("quant_snapshot") or {}
    lookback = int(snap_cfg.get("daily_lookback_days", 60))
    fetch_rv = bool(snap_cfg.get("fetch_intraday_rv", True))
    enrich_stats: EnrichmentStats | None = None
    live_by_symbol: dict[str, LiveMarks] = {}
    budget_sec = float(enrich_cfg.get("generation_budget_sec", 20.0))
    max_symbols = max(1, int(enrich_cfg.get("max_symbols", 40)))
    deadline = time.monotonic() + max(5.0, budget_sec)

    # Prefer liquid index / bank names first so a budget cut still covers core names.
    priority = {
        "NIFTY": 0,
        "BANKNIFTY": 1,
        "FINNIFTY": 2,
        "MIDCPNIFTY": 3,
        "RELIANCE": 10,
        "HDFCBANK": 11,
        "ICICIBANK": 12,
        "INFY": 13,
        "TCS": 14,
        "SBIN": 15,
        "TATASTEEL": 16,
        "ITC": 17,
    }
    symbols = sorted(
        symbols,
        key=lambda s: (priority.get(s.upper(), 1000), s.upper()),
    )

    if enrich_enabled and symbols and source.startswith("icici_direct"):
        try:
            enricher = get_universe_enricher(cfg)
            live_by_symbol, enrich_stats = await enricher.enrich_many(
                symbols,
                deadline_monotonic=deadline,
                max_symbols=max_symbols,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Universe live enrichment failed: %s", exc)
            enrich_stats = EnrichmentStats(requested=len(symbols), failed=len(symbols))
            enrich_stats.errors.append(str(exc))

    iv_store = IvHistoryStore()
    earn_cal = EarningsCalendarStore()
    as_of = session_date_ist()
    now_iso = datetime.now(timezone.utc).isoformat()

    # Only build history for symbols that actually got live marks, and stop at budget.
    live_symbols = [s for s in symbols if s.upper() in {k.upper() for k in live_by_symbol}]
    history_sem = asyncio.Semaphore(3)

    async def _history_for(symbol: str) -> tuple[str, list[float], float | None]:
        live = live_by_symbol.get(symbol.upper())
        if live is None:
            return symbol, [], None
        stock_code = live.stock_code or master.stock_code_for_underlying(symbol)
        async with history_sem:
            if time.monotonic() >= deadline:
                return symbol, [], None
            history = await fetch_daily_closes(
                symbol=symbol,
                stock_code=stock_code,
                lookback_days=lookback,
                as_of_date=as_of,
            )
            rv: float | None = None
            if fetch_rv and time.monotonic() < deadline:
                rv = await fetch_realized_vol_intraday(
                    symbol=symbol,
                    stock_code=stock_code,
                    as_of_date=as_of,
                )
            return symbol, history, rv

    history_by_symbol: dict[str, tuple[list[float], float | None]] = {}
    if live_symbols:
        remaining = max(0.5, deadline - time.monotonic())
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*[_history_for(s) for s in live_symbols]),
                timeout=remaining,
            )
            for symbol, history, rv in results:
                history_by_symbol[symbol.upper()] = (history, rv)
        except asyncio.TimeoutError:
            logger.warning(
                "Candle history budget exhausted after enriching %d symbols",
                len(live_by_symbol),
            )
            if enrich_stats is not None:
                enrich_stats.errors.append(
                    "generation_budget: candle history truncated to keep API responsive"
                )

    for symbol in symbols:
        bindings[symbol] = (
            master.feed_bindings_for(symbol)
            if master.count
            else data_feed_bindings_for(symbol)
        )
        live = live_by_symbol.get(symbol.upper()) if live_by_symbol else None
        if live is None:
            snapshots.append(
                build_quant_snapshot(
                    marks=None,
                    symbol=symbol,
                    price_history_daily=[],
                    iv_series_intraday=[],
                    days_to_earnings=None,
                    cfg=cfg,
                )
            )
            continue

        if live.iv_annualized > 0:
            iv_store.append(
                symbol=symbol,
                session_date=as_of,
                ts_iso=now_iso,
                iv=float(live.iv_annualized),
            )
        iv_series = iv_store.series(symbol=symbol, session_date=as_of)
        history, rv = history_by_symbol.get(symbol.upper(), ([], None))
        days_earn = earn_cal.days_to_earnings(symbol, as_of_date=as_of)
        snap = build_quant_snapshot(
            marks=live,
            price_history_daily=history,
            iv_series_intraday=iv_series,
            days_to_earnings=days_earn,
            realized_vol_intraday=rv,
            cfg=cfg,
        )
        snapshots.append(snap)
        fields = snapshot_to_candidate_fields(snap)
        if snap.expiry_key:
            fields["atm_history_prior"] = AtmLiquidityHistoryStore().prior_points(
                underlying=symbol,
                expiry_key=snap.expiry_key,
                before_date=as_of,
                lookback_days=int(
                    (cfg.get("option_universe_filters") or {}).get(
                        "atm_history_lookback_days", 20
                    )
                ),
            )
        candidates.append(_candidate_from_live(symbol, fields))

    return candidates, bindings, source, enrich_stats, snapshots


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
    includes_underlying: bool = False,
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

    prior = list(c.atm_history_prior) if c.atm_history_prior is not None else []
    if not prior and c.expiry_key:
        store = AtmLiquidityHistoryStore()
        session_date = datetime.now(timezone.utc).astimezone().date().isoformat()
        try:
            from zoneinfo import ZoneInfo

            session_date = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        except Exception:  # noqa: BLE001
            pass
        prior = store.prior_points(
            underlying=c.symbol,
            expiry_key=c.expiry_key,
            before_date=session_date,
            lookback_days=int(f.get("atm_history_lookback_days", 20)),
        )

    liq = evaluate_atm_liquidity(
        live=live_from_aggregated(
            volume=int(c.volume),
            open_interest=int(c.open_interest),
            spread_pct_value=float(c.spread_pct),
        ),
        prior=prior,
        min_volume=int(f["min_volume"]),
        min_open_interest=int(f["min_open_interest"]),
        max_spread_pct=float(f["max_spread_pct"]),
        volume_vs_avg_min_ratio=float(f.get("volume_vs_avg_min_ratio", 1.5)),
        oi_vs_avg_min_ratio=float(f.get("oi_vs_avg_min_ratio", 1.3)),
        lookback_days=int(f.get("atm_history_lookback_days", 20)),
        min_history_days=int(f.get("atm_history_min_days", 10)),
    )
    gates.extend(_liquidity_gate_results(liq, f))

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
    *,
    available_strategies: set[StrategyType] | None = None,
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
        available_strategies=available_strategies,
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
    includes_underlying: bool = False,
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
    *,
    force_refresh: bool = False,
) -> RecommendationResponse:
    """Return top recommendations, preferring a short-lived in-process cache.

    Full live enrichment of the FNO universe can take minutes under Breeze rate
    limits. Page loads (/recommendations, /decisions) must not wait that long —
    serve a fresh-enough cached packet, and only recompute on miss / force_refresh.
    """
    if not force_refresh and news is None:
        cached = peek_cached_recommendations()
        if cached is not None:
            return cached

    async with _response_cache_lock:
        if not force_refresh and news is None:
            cached = peek_cached_recommendations()
            if cached is not None:
                return cached
        result = await _generate_recommendations_uncached(news=news)
        _store_recommendation_response_cache(result)
        return result


async def _generate_recommendations_uncached(
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
    calibrator = ConfidenceCalibrator()

    universe, feed_bindings, universe_source, enrich_stats, snapshots = await _build_universe()
    universe_size = len(snapshots) if snapshots else len(universe)
    # Coverage must use the enrichment-attempted count when the cycle is capped
    # (max_symbols / budget); scoring against full G11 makes publish impossible.
    attempted = (
        enrich_stats.requested
        if enrich_stats is not None and enrich_stats.requested > 0
        else 0
    )
    scanned = attempted if attempted > 0 else universe_size
    if scanned <= 0:
        scanned = len(feed_bindings) or 0
    coverage_report = evaluate_strategy_coverage(
        snapshots,
        scanned=scanned,
        cfg=cfg,
    )
    available = coverage_report.available_strategies

    ranked: list[InstrumentRecommendation] = []
    passing = 0
    learning_hits = 0

    live_count = sum(1 for c in universe if c.marks_source == "live")
    stub_count = sum(1 for c in universe if c.marks_source == "stub")
    demo_count = sum(1 for c in universe if c.marks_source == "demo")

    for c in universe:
        strategy = _select_strategy(
            c, news, cfg, available_strategies=available
        )
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

        raw_after = insight.confidence_after
        conf, cal_status, conf_source = calibrator.apply(
            raw_after, strategy.selected_strategy.value
        )
        draft.raw_confidence = raw_after
        draft.confidence = conf
        draft.calibration_status = cal_status
        draft.confidence_source = conf_source
        insight.confidence_after = conf
        insight.calibration_status = cal_status
        insight.confidence_source = conf_source
        if cal_status == "calibrated":
            draft.complete_logic.append(
                f"13. Confidence calibration: P(win)={conf:.0%} via outcome map "
                f"(raw after learning={raw_after:.0%})."
            )
            score_bd.components.append(
                f"Calibrated confidence {conf:.3f} (source=outcome_map; "
                f"raw={raw_after:.3f})"
            )
        else:
            draft.complete_logic.append(
                "13. Confidence calibration: uncalibrated heuristic "
                f"(min(0.95, score+0.05) after learning) = {conf:.0%}."
            )
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

    calibrated_n = sum(1 for r in top3 if r.calibration_status == "calibrated")
    notes = [
        f"Scanned {universe_size} instruments from feed-bound universe (G11–G12).",
        (
            f"Coverage denominator: {scanned} enrichment-attempted underlyings "
            f"(max_symbols/budget cap; not full universe)."
            if attempted > 0 and attempted != universe_size
            else f"Coverage denominator: {scanned} underlyings."
        ),
        (
            "Universe source: ICICI Direct FONSEScripMaster "
            f"({universe_source}) — all NSE F&O underlyings with auto G12 bindings."
            if universe_source.startswith("icici_direct")
            else f"Universe source: {universe_source} (ICICI Direct FNO master unavailable)."
        ),
        (
            f"Marks coverage: live={live_count}, stub={stub_count}, demo={demo_count} "
            "(live = NSE LTP + NFO option-chain ATM; demo/stub not used for ranking)."
        ),
        f"Live-ranked candidates: {len(universe)}.",
        f"{passing} passed all options-only retail gates (I21).",
        f"Confidence floor: only candidates with confidence ≥ {min_confidence:.0%} are recommended.",
        (
            f"Confidence calibration: {calibrated_n}/{len(top3)} top recommendations use "
            "outcome-calibrated P(win); others use uncalibrated heuristic."
            if top3
            else "Confidence calibration: no recommendations this cycle."
        ),
        "Strategy selection follows Trading_Strategies.md Table SH-4 with Market_News overlay.",
        "Parameter gates sourced from Trading_Parameters.md Parts G, H, I, T, U.",
        "Each recommendation includes a complete P1 insight packet for operator review.",
        "Continual learning: failure memory + module weights applied (§12).",
        "Live-clean quant: no synthetic GARCH / flat-history fills in ranking.",
    ]
    notes.extend(coverage_report.note_lines())
    if not available:
        top3 = []
        notes.append(
            "STRATEGY_COVERAGE cycle: all strategies aborted — no recommendations published."
        )
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

    coverage_rows = [
        StrategyCoverageStatus.model_validate(r) for r in coverage_report.api_rows()
    ]
    return RecommendationResponse(
        generated_at=now,
        feed_as_of=now,
        feed_sources=sources,
        market_news=news,
        universe_scanned=universe_size,
        candidates_passing_gates=passing,
        recommendations=top3,
        analysis_notes=notes,
        coverage_by_strategy=coverage_rows,
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
