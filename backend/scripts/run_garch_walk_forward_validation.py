"""Run the GARCH(1,1) walk-forward evidence check and write the report.

Usage (from repo root, after backfill_daily_price_history.py has been run):
  python -m backend.scripts.run_garch_walk_forward_validation

Reads backend/data/daily_price_history.json, runs a walk-forward comparison
of fixed-weight vs MLE-fit GARCH(1,1) forecasts per symbol (see
backend/quant/analytics/garch_walk_forward_validator.py for method), and
writes:
  Docs/bot_health/garch_mle_walk_forward_evidence.md
  Docs/bot_health/garch_mle_walk_forward_evidence.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from backend.quant.analytics.daily_price_history_store import DailyPriceHistoryStore
from backend.quant.analytics.garch_walk_forward_validator import (
    WalkForwardSummary,
    combine_summaries,
    run_walk_forward,
    summarize_walk_forward,
)
from backend.quant.signals.garch import log_returns_from_prices

REPORT_MD_PATH = (
    Path(__file__).resolve().parents[2] / "Docs" / "bot_health" / "garch_mle_walk_forward_evidence.md"
)
REPORT_JSON_PATH = REPORT_MD_PATH.with_suffix(".json")


def _fmt(v: float | None, *, pct: bool = False, digits: int = 4) -> str:
    if v is None:
        return "n/a"
    return f"{v * 100:.1f}%" if pct else f"{v:.{digits}f}"


def _summary_to_dict(s: WalkForwardSummary) -> dict:
    return {
        "symbol": s.symbol,
        "n_events": s.n_events,
        "n_fit_usable": s.n_fit_usable,
        "fit_usable_rate": s.fit_usable_rate,
        "mean_qlike_fixed": s.mean_qlike_fixed,
        "mean_qlike_fitted": s.mean_qlike_fitted,
        "mean_mse_fixed": s.mean_mse_fixed,
        "mean_mse_fitted": s.mean_mse_fitted,
        "fitted_win_rate": s.fitted_win_rate,
        "insufficient_sample": s.insufficient_sample,
    }


def run_validation(
    *,
    store: DailyPriceHistoryStore | None = None,
    window: int = 250,
    fit_min_observations: int = 60,
    min_events: int = 100,
) -> tuple[list[WalkForwardSummary], WalkForwardSummary]:
    store = store or DailyPriceHistoryStore()
    per_symbol: list[WalkForwardSummary] = []
    for symbol in store.symbols():
        closes = store.series(symbol=symbol)
        returns = log_returns_from_prices(closes)
        events = run_walk_forward(
            returns, window=window, fit_min_observations=fit_min_observations
        )
        per_symbol.append(
            summarize_walk_forward(symbol=symbol, events=events, min_events=min_events)
        )
    combined = combine_summaries(per_symbol) if per_symbol else combine_summaries([])
    return per_symbol, combined


def render_report(
    *,
    per_symbol: list[WalkForwardSummary],
    combined: WalkForwardSummary,
    store: DailyPriceHistoryStore,
    window: int,
    fit_min_observations: int,
) -> str:
    lines: list[str] = []
    lines.append("# GARCH(1,1) MLE-fit walk-forward evidence")
    lines.append("")
    lines.append(
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} — "
        "see Improve_Recoemmendation_Engine.md §3.4 and "
        "Docs/superpowers/plans/2026-08-04-garch-mle-fit.md."
    )
    lines.append("")
    if combined.insufficient_sample:
        lines.append(
            "> **⚠️ INSUFFICIENT SAMPLE — not a validated result.** "
            f"Combined event count ({combined.n_events}) is below the evidence floor. "
            "Do not treat these numbers as justification for changing `enable_mle_fit`."
        )
        lines.append("")

    lines.append("## Method")
    lines.append("")
    lines.append(
        f"Rolling {window}-trading-day window, stepped forward one day at a time. "
        "At each step, both the fixed-weight (γ=0.05, α=0.05, β=0.90) and "
        f"MLE-fit (`fit_min_observations={fit_min_observations}`) GARCH(1,1) forecast "
        "next-day variance from the same trailing window; each is scored against the "
        "realized next-day squared log return via QLIKE (`ln(σ̂²) + r²/σ̂²`, lower is "
        "better — the standard robust loss for comparing variance forecasts, and the "
        "same shape as the MLE fit's own likelihood) and squared error. "
        f"A result is flagged insufficient below {100} combined evaluation days."
    )
    lines.append("")

    lines.append("## Pilot universe")
    lines.append("")
    lines.append("| Symbol | History range | Trading days |")
    lines.append("|---|---|---|")
    for symbol in store.symbols():
        rng = store.date_range(symbol=symbol)
        n = len(store.series(symbol=symbol))
        rng_str = f"{rng[0]} → {rng[1]}" if rng else "n/a"
        lines.append(f"| {symbol} | {rng_str} | {n} |")
    lines.append("")

    lines.append("## Per-symbol results")
    lines.append("")
    lines.append(
        "| Symbol | Events | Fit-usable rate | Mean QLIKE (fixed) | Mean QLIKE (fitted) "
        "| Fitted win rate | Mean MSE (fixed) | Mean MSE (fitted) |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")
    for s in per_symbol:
        flag = " ⚠️" if s.insufficient_sample else ""
        lines.append(
            f"| {s.symbol}{flag} | {s.n_events} | {_fmt(s.fit_usable_rate, pct=True)} "
            f"| {_fmt(s.mean_qlike_fixed)} | {_fmt(s.mean_qlike_fitted)} "
            f"| {_fmt(s.fitted_win_rate, pct=True)} "
            f"| {_fmt(s.mean_mse_fixed, digits=8)} | {_fmt(s.mean_mse_fitted, digits=8)} |"
        )
    lines.append("")

    lines.append("## Combined (all symbols pooled, weighted by event count)")
    lines.append("")
    lines.append(f"- Total events: **{combined.n_events}**")
    lines.append(
        f"- Fit-usable rate: **{_fmt(combined.fit_usable_rate, pct=True)}** "
        "(fraction of steps where the MLE fit converged to a usable forecast, not `garch_fit_failed`)"
    )
    lines.append(f"- Mean QLIKE — fixed: **{_fmt(combined.mean_qlike_fixed)}**, fitted: **{_fmt(combined.mean_qlike_fitted)}**")
    lines.append(f"- Mean MSE — fixed: **{_fmt(combined.mean_mse_fixed, digits=8)}**, fitted: **{_fmt(combined.mean_mse_fitted, digits=8)}**")
    lines.append(f"- Fitted win rate (fraction of fit-usable steps where fitted QLIKE < fixed QLIKE): **{_fmt(combined.fitted_win_rate, pct=True)}**")
    lines.append("")

    lines.append("## Recommendation")
    lines.append("")
    if combined.insufficient_sample or combined.mean_qlike_fitted is None:
        lines.append(
            "Insufficient/no usable evidence — **keep `garch_forecast.enable_mle_fit: false`.** "
            "Do not flip the default on this evidence."
        )
    elif combined.mean_qlike_fitted < combined.mean_qlike_fixed and (combined.fitted_win_rate or 0) > 0.5:
        lines.append(
            "The MLE fit beats the fixed-weight fallback on both mean QLIKE and win rate over "
            f"{combined.n_events} pooled out-of-sample days. This is evidence in favor of the fit "
            "— **still requires human review before flipping `enable_mle_fit` to `true`** "
            "(this script does not change the config itself), and ideally a longer/rolling re-run "
            "as more history accumulates rather than a one-shot decision."
        )
    else:
        lines.append(
            "The fixed-weight fallback is at least as good as the MLE fit on this evidence "
            f"({combined.n_events} pooled out-of-sample days) — **keep `garch_forecast.enable_mle_fit: false`.** "
            "This is consistent with the final-review finding that the fit tends toward degenerate "
            "boundary solutions on the history lengths this bot actually sees per symbol."
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", type=int, default=250)
    parser.add_argument("--fit-min-observations", type=int, default=60)
    parser.add_argument("--min-events", type=int, default=100)
    args = parser.parse_args()

    store = DailyPriceHistoryStore()
    if not store.symbols():
        print("No data in daily_price_history.json — run backfill_daily_price_history.py first.")
        return 1

    per_symbol, combined = run_validation(
        store=store,
        window=args.window,
        fit_min_observations=args.fit_min_observations,
        min_events=args.min_events,
    )

    report = render_report(
        per_symbol=per_symbol,
        combined=combined,
        store=store,
        window=args.window,
        fit_min_observations=args.fit_min_observations,
    )
    REPORT_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD_PATH.write_text(report, encoding="utf-8")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": args.window,
        "fit_min_observations": args.fit_min_observations,
        "min_events": args.min_events,
        "per_symbol": [_summary_to_dict(s) for s in per_symbol],
        "combined": _summary_to_dict(combined),
    }
    REPORT_JSON_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"Wrote {REPORT_MD_PATH}")
    print(f"Wrote {REPORT_JSON_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
