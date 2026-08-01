"""GARCH / IV z-score signal packet + evaluate (Phase 1.5).

Authority: Docs/Paper_Simulator.md signals API; Trading_Parameters Parts H, N4, T;
Trading_Strategies.md SH-4. Signals drive paper-sim and recommendation packets.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from backend.execution.options_only import OPTIONS_ONLY_REQUIRED
from backend.models.recommendations import GateResult, MarketNewsSummary, StrategyType
from backend.quant.signals.garch import (
    GarchForecastResult,
    detect_price_gaps,
    forecast_garch_11,
    log_returns_from_prices,
)
from backend.quant.signals.iv_zscore import IvZScoreResult, compute_iv_zscore, vega_entry_signal
from backend.services.atm_liquidity import (
    AtmHistoryPoint,
    AtmLiquidityLive,
    AtmSideMarks,
    evaluate_atm_liquidity,
    live_from_aggregated,
)
from backend.services.market_news import get_market_news
from backend.services.strategy_selection import (
    QuantRegimeInputs,
    select_strategy_packet,
)

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "trading_parameters.defaults.json"


def _load_config() -> dict[str, Any]:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


@dataclass(frozen=True)
class SignalComputeInputs:
    """Raw series / overrides used to build a signal packet."""

    symbol: str
    und_price: float
    option_iv_annual: float
    price_history: Sequence[float] | None = None
    log_returns: Sequence[float] | None = None
    intraday_iv_series: Sequence[float] | None = None
    garch_forecast_annual: float | None = None
    iv_z_score: float | None = None
    garch_distorted: bool | None = None
    days_to_earnings: int | None = None
    realized_vol_intraday: float | None = None
    atm_premium_inr: float = 100.0
    volume: int = 10_000
    open_interest: int = 25_000
    spread_pct: float = 0.4
    dte: int = 20
    includes_underlying: bool = False
    ce_volume: int | None = None
    pe_volume: int | None = None
    ce_open_interest: int | None = None
    pe_open_interest: int | None = None
    ce_bid: float | None = None
    ce_ask: float | None = None
    pe_bid: float | None = None
    pe_ask: float | None = None
    atm_history_prior: Sequence[AtmHistoryPoint] | None = None


def seed_atm_history_prior(volume: int, open_interest: int, *, days: int = 10) -> list[AtmHistoryPoint]:
    """Synthetic prior sessions so current marks clear 1.5× / 1.3× relative gates."""
    avg_vol = max(1, int(volume / 1.6))
    avg_oi = max(1, int(open_interest / 1.4))
    return [
        AtmHistoryPoint(session_date=f"2026-01-{i:02d}", atm_volume=avg_vol, atm_oi=avg_oi)
        for i in range(1, days + 1)
    ]


def _live_from_inputs(inp: SignalComputeInputs) -> AtmLiquidityLive:
    if (
        inp.ce_volume is not None
        and inp.pe_volume is not None
        and inp.ce_open_interest is not None
        and inp.pe_open_interest is not None
        and inp.ce_bid is not None
        and inp.ce_ask is not None
        and inp.pe_bid is not None
        and inp.pe_ask is not None
    ):
        return AtmLiquidityLive(
            ce=AtmSideMarks(
                volume=int(inp.ce_volume),
                open_interest=int(inp.ce_open_interest),
                bid=float(inp.ce_bid),
                ask=float(inp.ce_ask),
            ),
            pe=AtmSideMarks(
                volume=int(inp.pe_volume),
                open_interest=int(inp.pe_open_interest),
                bid=float(inp.pe_bid),
                ask=float(inp.pe_ask),
            ),
        )
    return live_from_aggregated(
        volume=int(inp.volume),
        open_interest=int(inp.open_interest),
        spread_pct_value=float(inp.spread_pct),
    )


def _liquidity_gate_results(result, f: dict[str, Any]) -> list[GateResult]:
    vs = f"{result.volume_vs_avg:.2f}" if result.volume_vs_avg is not None else "n/a"
    oi_vs = f"{result.oi_vs_avg:.2f}" if result.oi_vs_avg is not None else "n/a"
    return [
        GateResult(
            gate_id="T13",
            label=f"Volume ≥ {f['min_volume']}",
            passed=result.abs_volume_ok,
            detail=str(result.atm_volume),
            parameter_ref="Trading_Parameters.md Part T — T13",
        ),
        GateResult(
            gate_id="T13b",
            label=f"Volume > {f['volume_vs_avg_min_ratio']}× {result.history_days}d avg",
            passed=result.rel_volume_ok,
            detail=f"vs_avg={vs}",
            parameter_ref="Trading_Parameters.md Part T — T13b",
        ),
        GateResult(
            gate_id="T14",
            label=f"Open interest ≥ {f['min_open_interest']}",
            passed=result.abs_oi_ok,
            detail=str(result.atm_oi),
            parameter_ref="Trading_Parameters.md Part T — T14",
        ),
        GateResult(
            gate_id="T14b",
            label=f"OI > {f['oi_vs_avg_min_ratio']}× {result.history_days}d avg",
            passed=result.rel_oi_ok,
            detail=f"vs_avg={oi_vs}",
            parameter_ref="Trading_Parameters.md Part T — T14b",
        ),
        GateResult(
            gate_id="T15",
            label=f"Spread < {f['max_spread_pct']}% of mid",
            passed=result.spread_ok,
            detail=f"{result.spread_pct:.2f}%",
            parameter_ref="Trading_Parameters.md Part T — T15",
        ),
    ]


def compute_garch_from_inputs(
    inp: SignalComputeInputs,
    cfg: dict[str, Any] | None = None,
) -> GarchForecastResult:
    """Resolve GARCH forecast from override, log returns, or price history."""
    cfg = cfg or _load_config()
    gcfg = cfg["garch_forecast"]
    gamma = float(gcfg["gamma_weight"])
    alpha = float(gcfg["alpha_weight"])
    beta = float(gcfg["beta_weight"])
    ann = int(gcfg["annualization_factor"])
    min_obs = int(gcfg.get("min_observations", 20))
    max_gap = float(gcfg.get("max_log_return_gap", 0.25))

    if inp.garch_forecast_annual is not None and inp.garch_forecast_annual > 0:
        distorted = bool(inp.garch_distorted) if inp.garch_distorted is not None else False
        daily = inp.garch_forecast_annual / math.sqrt(ann)
        return GarchForecastResult(
            sigma_daily=daily,
            sigma_annual=float(inp.garch_forecast_annual),
            vl=None,
            prior_u2=None,
            prior_sigma2=None,
            forecast_sigma2=None,
            garch_distorted=distorted,
            insufficient_history=False,
            reason="override" if not distorted else "override_distorted",
            observations=0,
        )

    gap = False
    returns: list[float]
    if inp.log_returns is not None:
        returns = [float(r) for r in inp.log_returns]
        gap = any(abs(r) > max_gap for r in returns)
    elif inp.price_history is not None:
        gap = detect_price_gaps(inp.price_history, max_return_abs=max_gap)
        returns = log_returns_from_prices(inp.price_history)
    else:
        return GarchForecastResult(
            sigma_daily=None,
            sigma_annual=None,
            vl=None,
            prior_u2=None,
            prior_sigma2=None,
            forecast_sigma2=None,
            garch_distorted=True,
            insufficient_history=True,
            reason="no_price_history",
            observations=0,
        )

    result = forecast_garch_11(
        returns,
        gamma=gamma,
        alpha=alpha,
        beta=beta,
        annualization_factor=ann,
        min_observations=min_obs,
        gap_detected=gap,
    )
    if inp.garch_distorted is True:
        return GarchForecastResult(
            sigma_daily=result.sigma_daily,
            sigma_annual=result.sigma_annual,
            vl=result.vl,
            prior_u2=result.prior_u2,
            prior_sigma2=result.prior_sigma2,
            forecast_sigma2=result.forecast_sigma2,
            garch_distorted=True,
            insufficient_history=result.insufficient_history,
            reason=result.reason or "forced_distorted",
            observations=result.observations,
        )
    return result


def compute_iv_z_from_inputs(
    inp: SignalComputeInputs,
    cfg: dict[str, Any] | None = None,
) -> IvZScoreResult:
    """Resolve IV z-score from override or intraday IV series."""
    cfg = cfg or _load_config()
    zcfg = cfg.get("iv_zscore") or {}
    vega_cfg = cfg.get("strategies", {}).get("vega_scalping", {}).get("iv_signal", {})
    entry_z = float(zcfg.get("entry_z_threshold", vega_cfg.get("entry_z_threshold", -2.0)))
    min_obs = int(zcfg.get("min_observations", 5))

    if inp.iv_z_score is not None:
        z = float(inp.iv_z_score)
        reject = math.isnan(z) or math.isinf(z)
        return IvZScoreResult(
            iv_z_score=None if reject else z,
            iv_intraday_mean=None,
            iv_intraday_std=None,
            current_iv=inp.option_iv_annual,
            reject_vega=reject,
            stationarity_ok=not reject,
            reason="override" if not reject else "nan_zscore_override",
            observations=0,
        )

    if inp.intraday_iv_series:
        return compute_iv_zscore(
            inp.intraday_iv_series,
            current_iv=inp.option_iv_annual,
            min_observations=min_obs,
            entry_z_threshold=entry_z,
        )

    return IvZScoreResult(
        iv_z_score=None,
        iv_intraday_mean=None,
        iv_intraday_std=None,
        current_iv=inp.option_iv_annual,
        reject_vega=True,
        stationarity_ok=False,
        reason="no_iv_series",
        observations=0,
    )


def _retail_gates(
    inp: SignalComputeInputs,
    *,
    includes_underlying: bool,
    cfg: dict[str, Any],
) -> list[GateResult]:
    """Options-only hard lock plus T1 / T13-T15 gates used by POST /signals/evaluate."""
    f = cfg["option_universe_filters"]
    gates: list[GateResult] = []

    if includes_underlying:
        gates.append(
            GateResult(
                gate_id=OPTIONS_ONLY_REQUIRED,
                label="Options-only hard lock",
                passed=False,
                detail="Stock/underlying legs are not allowed",
                parameter_ref="backend.execution.options_only",
            )
        )

    prem_ok = inp.atm_premium_inr < float(f["max_option_premium"])
    gates.append(
        GateResult(
            gate_id="T1",
            label=f"ATM premium < {f['max_option_premium']} INR",
            passed=prem_ok,
            detail=f"₹{inp.atm_premium_inr:.2f}",
            parameter_ref="Trading_Parameters.md Part T — T1",
        )
    )

    live = _live_from_inputs(inp)
    prior = list(inp.atm_history_prior) if inp.atm_history_prior is not None else []
    liq = evaluate_atm_liquidity(
        live=live,
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
    return gates


def build_signal_packet(
    inp: SignalComputeInputs,
    news: MarketNewsSummary | None = None,
    cfg: dict[str, Any] | None = None,
    *,
    setup_designed_for_event: bool = False,
    position_open: bool = False,
) -> dict[str, Any]:
    """Compute GARCH + IV z, run SH-4 + news, return paper-sim signals packet."""
    cfg = cfg or _load_config()
    news = news or get_market_news()
    garch = compute_garch_from_inputs(inp, cfg)
    ivz = compute_iv_z_from_inputs(inp, cfg)
    zcfg = cfg.get("iv_zscore") or {}
    vega_cfg = cfg.get("strategies", {}).get("vega_scalping", {}).get("iv_signal", {})
    entry_z = float(zcfg.get("entry_z_threshold", vega_cfg.get("entry_z_threshold", -2.0)))

    garch_annual = garch.sigma_annual
    distorted = garch.garch_distorted or (inp.garch_distorted is True)
    # Q-15: reject vega — treat z as missing for SH-4
    z_for_sh4 = ivz.iv_z_score if ivz.usable else None

    # When GARCH unusable (Q-14 / MD-10), force distorted so SH-4 stands aside
    if not garch.usable:
        distorted = True
        # Placeholder forecast so QuantRegimeInputs stays valid; SH-4 blocks on distorted
        garch_annual = garch_annual if garch_annual and garch_annual > 0 else 0.01

    quant = QuantRegimeInputs(
        symbol=inp.symbol.upper(),
        iv_annualized=float(inp.option_iv_annual),
        garch_forecast=float(garch_annual),
        iv_z_score=z_for_sh4,
        days_to_earnings=inp.days_to_earnings,
        realized_vol_intraday=inp.realized_vol_intraday,
        garch_distorted=distorted,
    )
    selection = select_strategy_packet(
        quant,
        news,
        cfg,
        setup_designed_for_event=setup_designed_for_event,
        position_open=position_open,
    )

    iv_minus = (
        float(inp.option_iv_annual) - float(garch_annual)
        if garch_annual is not None
        else None
    )
    cheap_vol = (
        garch.usable
        and not distorted
        and float(inp.option_iv_annual) < float(garch_annual)
    )
    vega_ok = vega_entry_signal(ivz, entry_z_threshold=entry_z) and news.news_not_blocking

    signal_reproducible = garch.usable or (
        inp.garch_forecast_annual is not None and inp.garch_forecast_annual > 0
    )

    return {
        "underlying": inp.symbol.upper(),
        "und_price": inp.und_price,
        "garch_forecast_annual": garch.sigma_annual,
        "option_iv_annual": inp.option_iv_annual,
        "iv_minus_garch": iv_minus,
        "iv_zscore": ivz.iv_z_score,
        "iv_intraday_mean": ivz.iv_intraday_mean,
        "iv_intraday_std": ivz.iv_intraday_std,
        "garch_distorted": distorted,
        "garch_insufficient_history": garch.insufficient_history,
        "garch_reason": garch.reason,
        "iv_z_reject_vega": ivz.reject_vega,
        "iv_z_reason": ivz.reason,
        "cheap_vol": cheap_vol,
        "vega_entry_ok": vega_ok,
        "signal_reproducible": signal_reproducible,
        "selected_strategy": selection["selected_strategy"],
        "entry_mode": selection["entry_mode"],
        "scenario_tag": selection["scenario_tag"],
        "primary_signal": selection["primary_signal"],
        "rejected_strategies": selection["rejected_strategies"],
        "recommendation": selection["recommendation"],
        "post_entry_action": selection["post_entry_action"],
        "news_impact": selection["news_impact"],
        "market_news": selection["market_news"],
        "strategy": selection["strategy"],
        "garch_detail": {
            "sigma_daily": garch.sigma_daily,
            "vl": garch.vl,
            "observations": garch.observations,
            "usable": garch.usable,
        },
        "iv_z_detail": {
            "observations": ivz.observations,
            "stationarity_ok": ivz.stationarity_ok,
            "usable": ivz.usable,
            "entry_z_threshold": entry_z,
        },
    }


def evaluate_candidate(
    inp: SignalComputeInputs,
    news: MarketNewsSummary | None = None,
    cfg: dict[str, Any] | None = None,
    *,
    setup_designed_for_event: bool = False,
    position_open: bool = False,
) -> dict[str, Any]:
    """POST /signals/evaluate — signal packet + options-only retail gates."""
    cfg = cfg or _load_config()
    packet = build_signal_packet(
        inp,
        news=news,
        cfg=cfg,
        setup_designed_for_event=setup_designed_for_event,
        position_open=position_open,
    )
    gates = _retail_gates(inp, includes_underlying=inp.includes_underlying, cfg=cfg)
    all_gates_ok = all(g.passed for g in gates)

    # Downgrade recommendation when gates fail or signals not reproducible
    recommendation = packet["recommendation"]
    eligible = True
    block_reasons: list[str] = []
    if not all_gates_ok:
        eligible = False
        failed = [g.gate_id for g in gates if not g.passed]
        block_reasons.append(f"gate_fail:{','.join(failed)}")
        recommendation = "stand_aside"
    if not packet["signal_reproducible"] or packet["garch_distorted"]:
        if packet["selected_strategy"] == StrategyType.blocked.value or packet[
            "recommendation"
        ] in {"blocked", "stand_aside"}:
            pass
        elif packet["garch_insufficient_history"]:
            eligible = False
            block_reasons.append("q14_insufficient_garch_history")
            recommendation = "stand_aside"
    if packet["iv_z_reject_vega"] and packet["selected_strategy"] == StrategyType.vega_scalping.value:
        eligible = False
        block_reasons.append("q15_iv_z_reject_vega")
        recommendation = "stand_aside"

    packet.update(
        {
            "gates": [g.model_dump(mode="json") for g in gates],
            "gates_passed": all_gates_ok,
            "includes_underlying": inp.includes_underlying,
            "eligible": eligible and all_gates_ok and recommendation
            not in {"blocked", "stand_aside"},
            "block_reasons": block_reasons,
            "recommendation": recommendation,
            "evaluate": True,
        }
    )
    return packet


# --- Demo universe for GET /signals when live history is not injected ---

_DEMO: dict[str, dict[str, Any]] = {
    "RELIANCE": {
        "und_price": 982.5,
        "option_iv_annual": 0.24,
        "target_z": -2.3,
        "days_to_earnings": None,
        "atm_premium_inr": 185,
        "volume": 12500,
        "open_interest": 22000,
        "spread_pct": 0.4,
        "dte": 22,
        "realized_vol_intraday": 0.018,
    },
    "SBIN": {
        "und_price": 812.4,
        "option_iv_annual": 0.22,
        "target_z": None,
        "days_to_earnings": None,
        "atm_premium_inr": 95,
        "volume": 22000,
        "open_interest": 35000,
        "spread_pct": 0.4,
        "dte": 20,
        "realized_vol_intraday": 0.012,
    },
    "TATASTEEL": {
        "und_price": 142.8,
        "option_iv_annual": 0.31,
        "target_z": -2.6,
        "days_to_earnings": None,
        "atm_premium_inr": 42,
        "volume": 8900,
        "open_interest": 22000,
        "spread_pct": 0.4,
        "dte": 18,
        "realized_vol_intraday": 0.022,
    },
    "INFY": {
        "und_price": 1680.0,
        "option_iv_annual": 0.29,
        "target_z": -1.8,
        "days_to_earnings": 1,
        "atm_premium_inr": 210,
        "volume": 15200,
        "open_interest": 28000,
        "spread_pct": 0.4,
        "dte": 25,
        "realized_vol_intraday": 0.015,
    },
    "ITC": {
        "und_price": 428.5,
        "option_iv_annual": 0.26,
        "target_z": -2.1,
        "days_to_earnings": None,
        "atm_premium_inr": 68,
        "volume": 31000,
        "open_interest": 42000,
        "spread_pct": 0.4,
        "dte": 15,
        "realized_vol_intraday": 0.011,
    },
}


def _synthetic_price_history(spot: float, n: int = 60) -> list[float]:
    return [spot * (1 + 0.01 * math.sin(i / 3)) for i in range(n)]


def _synthetic_iv_series(iv: float, target_z: float | None, n: int = 30) -> list[float] | None:
    """Build an IV history whose (current_iv − mean) / std ≈ ``target_z``."""
    if target_z is None:
        return None
    std = 0.02
    mean = iv - target_z * std
    # Alternating mean±std; caller passes current_iv separately via option_iv_annual
    return [mean - std, mean + std] * max(n // 2, 5)


def signals_for_underlying(
    underlying: str,
    news: MarketNewsSummary | None = None,
    *,
    price_history: Sequence[float] | None = None,
    intraday_iv_series: Sequence[float] | None = None,
    option_iv_annual: float | None = None,
    und_price: float | None = None,
    includes_underlying: bool = False,
) -> dict[str, Any]:
    """GET /signals — demo-backed packet (live candles can be injected later)."""
    sym = underlying.upper()
    demo = _DEMO.get(sym)
    if demo is None and und_price is None:
        # Generic fallback so unknown symbols still return a structured packet
        demo = {
            "und_price": und_price or 500.0,
            "option_iv_annual": option_iv_annual or 0.25,
            "target_z": None,
            "days_to_earnings": None,
            "atm_premium_inr": 100,
            "volume": 12000,
            "open_interest": 15000,
            "spread_pct": 1.0,
            "dte": 20,
            "realized_vol_intraday": 0.012,
        }
    assert demo is not None
    spot = float(und_price if und_price is not None else demo["und_price"])
    iv = float(option_iv_annual if option_iv_annual is not None else demo["option_iv_annual"])
    history = list(price_history) if price_history is not None else _synthetic_price_history(spot)
    iv_series = (
        list(intraday_iv_series)
        if intraday_iv_series is not None
        else _synthetic_iv_series(iv, demo.get("target_z"))
    )
    vol = int(demo.get("volume", 10000))
    oi = int(demo.get("open_interest", 25000))
    spread = float(demo.get("spread_pct", 0.4))
    inp = SignalComputeInputs(
        symbol=sym,
        und_price=spot,
        option_iv_annual=iv,
        price_history=history,
        intraday_iv_series=iv_series,
        days_to_earnings=demo.get("days_to_earnings"),
        realized_vol_intraday=demo.get("realized_vol_intraday"),
        atm_premium_inr=float(demo.get("atm_premium_inr", 100)),
        volume=vol,
        open_interest=oi,
        spread_pct=spread,
        dte=int(demo.get("dte", 20)),
        includes_underlying=includes_underlying,
        atm_history_prior=seed_atm_history_prior(vol, oi),
    )
    return build_signal_packet(inp, news=news)
