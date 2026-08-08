# Per-symbol GARCH(1,1) weight calibration

Generated 2026-08-08 17:20 UTC — see Docs/superpowers/specs/2026-08-08-garch-per-symbol-weights-design.md.

## Method

Rolling 250-trading-day walk-forward per symbol; each grid candidate and the global default (γ=0.05, α=0.05, β=0.90) forecast next-day variance from the same trailing window, scored by OOS QLIKE against the realized next-day squared log return. An override is recommended only if the best candidate beats the default on mean QLIKE with a pairwise win rate > 55% over ≥ 100 events; otherwise the symbol keeps the global default.

## Per-symbol results

| Symbol | Days | Events | Default QLIKE | Best candidate (γ/α/β) | Best QLIKE | Win rate | Verdict |
|---|---|---|---|---|---|---|---|
| BANKNIFTY | 609 | 358 | -8.4381 | 0.03/0.12/0.85 | -8.4962 | 61.5% | **override** 0.03/0.12/0.85 |
| HDFCBANK | 609 | 358 | -7.9091 | 0.04/0.08/0.88 | -7.9264 | 60.1% | **override** 0.04/0.08/0.88 |
| INFY | 609 | 358 | -6.9593 | 0.05/0.03/0.92 | -6.9710 | 49.4% | keep default (win_rate_below_guard) |
| NIFTY | 607 | 356 | -8.6488 | 0.04/0.08/0.88 | -8.6680 | 61.0% | **override** 0.04/0.08/0.88 |
| RELIANCE | 609 | 358 | -7.6522 | 0.05/0.05/0.90 | -7.6522 | 0.0% | keep default (default_at_least_as_good) |

## Recommended `garch_forecast.symbol_overrides`

```json
{
  "BANKNIFTY": {
    "gamma_weight": 0.03,
    "alpha_weight": 0.12,
    "beta_weight": 0.85
  },
  "HDFCBANK": {
    "gamma_weight": 0.04,
    "alpha_weight": 0.08,
    "beta_weight": 0.88
  },
  "NIFTY": {
    "gamma_weight": 0.04,
    "alpha_weight": 0.08,
    "beta_weight": 0.88
  }
}
```

Review this evidence, then apply the block above to `backend/config/trading_parameters.defaults.json` — this script does not change config itself.
