"""Calibrate per-symbol GARCH(1,1) weight overrides from daily close history.

Usage (from repo root, after backfill_daily_price_history.py — use --all-fno
there to cover the full FNO universe):
  python -m backend.scripts.calibrate_garch_weights

For every symbol in backend/data/daily_price_history.json, walk-forward
scores a fixed grid of (gamma, alpha, beta) candidates by out-of-sample
QLIKE (same scheme as run_garch_walk_forward_validation.py) against the
global default weights. A symbol gets a recommended override only when the
best candidate clears the acceptance guard:

  win rate vs default > --min-win-rate (0.55) AND lower mean QLIKE,
  over >= --min-events (100) walk-forward days.

Writes:
  Docs/bot_health/garch_weight_calibration.md
  Docs/bot_health/garch_weight_calibration.json

This script NEVER edits config. It prints the recommended
``garch_forecast.symbol_overrides`` block; a human reviews the evidence and
commits the config change (same contract as the MLE walk-forward validator).
Pure-Python scoring: a full ~200-symbol universe takes minutes — offline use.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from backend.quant.analytics.daily_price_history_store import DailyPriceHistoryStore
from backend.quant.analytics.garch_walk_forward_validator import (
    CandidateGrid,
    CandidateScore,
    score_weight_candidates,
)
from backend.quant.signals.garch import log_returns_from_prices

REPORT_MD_PATH = (
    Path(__file__).resolve().parents[2] / "Docs" / "bot_health" / "garch_weight_calibration.md"
)
REPORT_JSON_PATH = REPORT_MD_PATH.with_suffix(".json")

DEFAULT_WEIGHTS: tuple[float, float, float] = (0.05, 0.05, 0.90)

# Grid spans sluggish (alpha=0.03) to highly reactive (alpha=0.15) regimes,
# capped at alpha+beta <= 0.97 to keep a real mean-reversion weight (gamma).
_ALPHAS = (0.03, 0.05, 0.08, 0.10, 0.12, 0.15)
_BETAS = (0.80, 0.85, 0.88, 0.90, 0.92)
DEFAULT_GRID: tuple[tuple[float, float, float], ...] = tuple(
    (round(1.0 - a - b, 4), a, b) for a in _ALPHAS for b in _BETAS if a + b <= 0.97
)


@dataclass(frozen=True, slots=True)
class SymbolCalibration:
    """Calibration outcome for one symbol: the grid plus the guard verdict."""

    symbol: str
    grid: CandidateGrid
    accepted: CandidateScore | None
    reject_reason: str | None


def _apply_guard(
    grid: CandidateGrid,
    *,
    min_events: int,
    min_win_rate: float,
) -> tuple[CandidateScore | None, str | None]:
    """Accept the best candidate only when the evidence clears the guard."""
    if grid.n_events < min_events:
        return None, "insufficient_events"
    if not grid.candidates or grid.candidates[0].mean_qlike is None:
        return None, "no_usable_candidates"
    best = grid.candidates[0]
    if grid.default.mean_qlike is None:
        return None, "default_unusable"
    if best.mean_qlike >= grid.default.mean_qlike:
        return None, "default_at_least_as_good"
    if (best.win_rate_vs_default or 0.0) <= min_win_rate:
        return None, "win_rate_below_guard"
    return best, None


def run_calibration(
    *,
    store: DailyPriceHistoryStore | None = None,
    window: int = 250,
    min_events: int = 100,
    min_win_rate: float = 0.55,
    default_weights: tuple[float, float, float] = DEFAULT_WEIGHTS,
    grid: tuple[tuple[float, float, float], ...] = DEFAULT_GRID,
) -> list[SymbolCalibration]:
    store = store or DailyPriceHistoryStore()
    results: list[SymbolCalibration] = []
    for symbol in store.symbols():
        returns = log_returns_from_prices(store.series(symbol=symbol))
        scored = score_weight_candidates(
            returns,
            candidates=list(grid),
            window=window,
            default_weights=default_weights,
        )
        accepted, reason = _apply_guard(
            scored, min_events=min_events, min_win_rate=min_win_rate
        )
        results.append(
            SymbolCalibration(
                symbol=symbol, grid=scored, accepted=accepted, reject_reason=reason
            )
        )
    return results


def recommended_overrides(results: list[SymbolCalibration]) -> dict[str, dict[str, float]]:
    """Accepted candidates as a config-ready ``symbol_overrides`` mapping."""
    out: dict[str, dict[str, float]] = {}
    for cal in results:
        if cal.accepted is None:
            continue
        out[cal.symbol] = {
            "gamma_weight": round(cal.accepted.gamma, 4),
            "alpha_weight": round(cal.accepted.alpha, 4),
            "beta_weight": round(cal.accepted.beta, 4),
        }
    return out


def _fmt(v: float | None, *, pct: bool = False, digits: int = 4) -> str:
    if v is None:
        return "n/a"
    return f"{v * 100:.1f}%" if pct else f"{v:.{digits}f}"


def render_report(
    *,
    results: list[SymbolCalibration],
    store: DailyPriceHistoryStore,
    window: int,
    min_events: int = 100,
    min_win_rate: float = 0.55,
) -> str:
    lines: list[str] = []
    lines.append("# Per-symbol GARCH(1,1) weight calibration")
    lines.append("")
    lines.append(
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} — "
        "see Docs/superpowers/specs/2026-08-08-garch-per-symbol-weights-design.md."
    )
    lines.append("")
    lines.append("## Method")
    lines.append("")
    lines.append(
        f"Rolling {window}-trading-day walk-forward per symbol; each grid candidate "
        "and the global default (γ=0.05, α=0.05, β=0.90) forecast next-day variance "
        "from the same trailing window, scored by OOS QLIKE against the realized "
        "next-day squared log return. An override is recommended only if the best "
        f"candidate beats the default on mean QLIKE with a pairwise win rate > "
        f"{min_win_rate:.0%} over ≥ {min_events} events; otherwise the symbol keeps "
        "the global default."
    )
    lines.append("")
    lines.append("## Per-symbol results")
    lines.append("")
    lines.append(
        "| Symbol | Days | Events | Default QLIKE | Best candidate (γ/α/β) "
        "| Best QLIKE | Win rate | Verdict |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")
    for cal in results:
        n_days = len(store.series(symbol=cal.symbol))
        best = cal.grid.candidates[0] if cal.grid.candidates else None
        best_desc = (
            f"{best.gamma:.2f}/{best.alpha:.2f}/{best.beta:.2f}" if best else "n/a"
        )
        verdict = (
            f"**override** {cal.accepted.gamma:.2f}/{cal.accepted.alpha:.2f}/{cal.accepted.beta:.2f}"
            if cal.accepted
            else f"keep default ({cal.reject_reason})"
        )
        lines.append(
            f"| {cal.symbol} | {n_days} | {cal.grid.n_events} "
            f"| {_fmt(cal.grid.default.mean_qlike)} | {best_desc} "
            f"| {_fmt(best.mean_qlike) if best else 'n/a'} "
            f"| {_fmt(best.win_rate_vs_default, pct=True) if best else 'n/a'} "
            f"| {verdict} |"
        )
    lines.append("")
    overrides = recommended_overrides(results)
    lines.append("## Recommended `garch_forecast.symbol_overrides`")
    lines.append("")
    if overrides:
        lines.append("```json")
        lines.append(json.dumps(overrides, indent=2))
        lines.append("```")
        lines.append("")
        lines.append(
            "Review this evidence, then apply the block above to "
            "`backend/config/trading_parameters.defaults.json` — this script does "
            "not change config itself."
        )
    else:
        lines.append(
            "No symbol cleared the acceptance guard — keep the global default "
            "weights everywhere (an empty `symbol_overrides` is the correct state)."
        )
    lines.append("")
    return "\n".join(lines)


def _calibration_to_dict(cal: SymbolCalibration) -> dict:
    def _score(s: CandidateScore) -> dict:
        return {
            "gamma": s.gamma,
            "alpha": s.alpha,
            "beta": s.beta,
            "n_events": s.n_events,
            "mean_qlike": s.mean_qlike,
            "win_rate_vs_default": s.win_rate_vs_default,
        }

    return {
        "symbol": cal.symbol,
        "n_events": cal.grid.n_events,
        "default": _score(cal.grid.default),
        "top_candidates": [_score(s) for s in cal.grid.candidates[:5]],
        "accepted": _score(cal.accepted) if cal.accepted else None,
        "reject_reason": cal.reject_reason,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", type=int, default=250)
    parser.add_argument("--min-events", type=int, default=100)
    parser.add_argument("--min-win-rate", type=float, default=0.55)
    args = parser.parse_args()

    store = DailyPriceHistoryStore()
    if not store.symbols():
        print("No data in daily_price_history.json — run backfill_daily_price_history.py first.")
        return 1

    results = run_calibration(
        store=store,
        window=args.window,
        min_events=args.min_events,
        min_win_rate=args.min_win_rate,
    )

    report = render_report(
        results=results,
        store=store,
        window=args.window,
        min_events=args.min_events,
        min_win_rate=args.min_win_rate,
    )
    REPORT_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD_PATH.write_text(report, encoding="utf-8")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": args.window,
        "min_events": args.min_events,
        "min_win_rate": args.min_win_rate,
        "default_weights": {
            "gamma_weight": DEFAULT_WEIGHTS[0],
            "alpha_weight": DEFAULT_WEIGHTS[1],
            "beta_weight": DEFAULT_WEIGHTS[2],
        },
        "per_symbol": [_calibration_to_dict(c) for c in results],
        "recommended_symbol_overrides": recommended_overrides(results),
    }
    REPORT_JSON_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"Wrote {REPORT_MD_PATH}")
    print(f"Wrote {REPORT_JSON_PATH}")
    overrides = recommended_overrides(results)
    print("Recommended garch_forecast.symbol_overrides:")
    print(json.dumps(overrides, indent=2) if overrides else "(none — keep defaults)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
