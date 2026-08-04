# GARCH(1,1) MLE-fit walk-forward evidence

Generated 2026-08-04 16:36 UTC — see Improve_Recoemmendation_Engine.md §3.4 and Docs/superpowers/plans/2026-08-04-garch-mle-fit.md.

## Method

Rolling 250-trading-day window, stepped forward one day at a time. At each step, both the fixed-weight (γ=0.05, α=0.05, β=0.90) and MLE-fit (`fit_min_observations=60`) GARCH(1,1) forecast next-day variance from the same trailing window; each is scored against the realized next-day squared log return via QLIKE (`ln(σ̂²) + r²/σ̂²`, lower is better — the standard robust loss for comparing variance forecasts, and the same shape as the MLE fit's own likelihood) and squared error. A result is flagged insufficient below 100 combined evaluation days.

## Pilot universe

| Symbol | History range | Trading days |
|---|---|---|
| BANKNIFTY | 2024-02-16 → 2026-08-03 | 609 |
| HDFCBANK | 2024-02-16 → 2026-08-03 | 609 |
| INFY | 2024-02-16 → 2026-08-03 | 609 |
| NIFTY | 2024-02-16 → 2026-08-03 | 607 |
| RELIANCE | 2024-02-16 → 2026-08-03 | 609 |

## Per-symbol results

| Symbol | Events | Fit-usable rate | Mean QLIKE (fixed) | Mean QLIKE (fitted) | Fitted win rate | Mean MSE (fixed) | Mean MSE (fitted) |
|---|---|---|---|---|---|---|---|
| BANKNIFTY | 358 | 100.0% | -8.4381 | -8.4641 | 57.0% | 0.00000006 | 0.00000006 |
| HDFCBANK | 358 | 100.0% | -7.9091 | -7.8944 | 51.4% | 0.00000012 | 0.00000012 |
| INFY | 358 | 100.0% | -6.9593 | -6.9637 | 49.2% | 0.00000054 | 0.00000054 |
| NIFTY | 356 | 100.0% | -8.6488 | -8.6564 | 54.5% | 0.00000002 | 0.00000002 |
| RELIANCE | 358 | 100.0% | -7.6522 | -7.6265 | 41.3% | 0.00000011 | 0.00000011 |

## Combined (all symbols pooled, weighted by event count)

- Total events: **1788**
- Fit-usable rate: **100.0%** (fraction of steps where the MLE fit converged to a usable forecast, not `garch_fit_failed`)
- Mean QLIKE — fixed: **-7.9207**, fitted: **-7.9202**
- Mean MSE — fixed: **0.00000017**, fitted: **0.00000017**
- Fitted win rate (fraction of fit-usable steps where fitted QLIKE < fixed QLIKE): **50.7%**

## Recommendation

The fixed-weight fallback is at least as good as the MLE fit on this evidence (1788 pooled out-of-sample days) — **keep `garch_forecast.enable_mle_fit: false`.** This is consistent with the final-review finding that the fit tends toward degenerate boundary solutions on the history lengths this bot actually sees per symbol.
