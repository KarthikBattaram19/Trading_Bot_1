# Per-symbol GARCH(1,1) weights — design

Date: 2026-08-08. Approved by owner (extend to all FNO underlyings, not just the pilot five).

## Problem

`forecast_garch_11` runs with one global fixed weight set (γ=0.05, α=0.05, β=0.90)
for every underlying. The 2026-08-04 walk-forward evidence
(`Docs/bot_health/garch_mle_walk_forward_evidence.md`, 1,788 pooled OOS days)
showed the *daily MLE re-fit* is not the answer — it ties the fixed weights
(50.7% win rate) and tends to degenerate boundary solutions on 250-day
windows — so `enable_mle_fit` stays `false`. But that evidence never tested
whether *different fixed weights per symbol* beat the global fixed set.

A new walk-forward grid experiment (window=250, QLIKE, same scoring as the
existing validator, run 2026-08-08 on `backend/data/daily_price_history.json`)
shows they do, for some symbols:

| Symbol | Best OOS candidate (γ/α/β) | Win rate vs 0.05/0.05/0.90 | Full-history MLE corroboration |
|---|---|---|---|
| BANKNIFTY | 0.03/0.12/0.85 | 61.5% (n=358) | α=0.16, β=0.79 |
| NIFTY | 0.04/0.08/0.88 | 61.0% (n=356) | α=0.07, β=0.88 |
| HDFCBANK | 0.04/0.08/0.88 | 60.1% (n=358) | α=0.07, β=0.91 |
| INFY | (none passes guard) | best is 49.4% | α=0.02, β=0.97 |
| RELIANCE | (current is rank 1/17) | — | degenerate fit |

At n≈358 a 60% win rate is ~4σ above coin-flip; for NIFTY/HDFCBANK the grid
winner independently matches the MLE point estimate. Index/bank vol clusters
harder (needs higher α reactivity); α=0.05 lags after vol shocks, distorting
the `iv_below_garch_forecast` and `iv_elevated_vs_garch_multiplier` gates.

## Design

Mechanism: **per-symbol fixed-weight overrides, calibrated offline by a
repeatable evidence-gated script.** No runtime fitting; `enable_mle_fit`
stays `false`.

### 1. Config — `garch_forecast.symbol_overrides`

`backend/config/trading_parameters.defaults.json`:

```json
"symbol_overrides": {
  "BANKNIFTY": {"gamma_weight": 0.03, "alpha_weight": 0.12, "beta_weight": 0.85},
  "NIFTY":     {"gamma_weight": 0.04, "alpha_weight": 0.08, "beta_weight": 0.88},
  "HDFCBANK":  {"gamma_weight": 0.04, "alpha_weight": 0.08, "beta_weight": 0.88}
}
```

Schema (`GarchForecastParams`): map of uppercase symbol → the three weights,
each in [0, 1], `additionalProperties: false` per entry. `_assert_weights`
in `garch.py` already enforces sum≈1 at call time.

Any symbol without an override uses the global weights — this is how the
design covers the whole FNO universe: overrides exist only where evidence
supports them; everything else falls back.

### 2. Runtime — `quant_snapshot.py`

Resolve `symbol → gcfg["symbol_overrides"][SYMBOL] → global weights` before
calling `forecast_garch_11`. `symbol=None` or no entry → global weights.
Only wiring change in the trading path.

### 3. Calibration — `backend/scripts/calibrate_garch_weights.py`

For every symbol in `DailyPriceHistoryStore`:

- Walk-forward (window=250) over a fixed grid: α ∈ {0.03, 0.05, 0.08, 0.10,
  0.12, 0.15} × β ∈ {0.80, 0.85, 0.88, 0.90, 0.92}, α+β ≤ 0.97, γ = 1−α−β.
- Score each candidate by mean OOS QLIKE; compare pairwise vs the global
  default weights.
- **Acceptance guard**: recommend an override only if the best candidate's
  win rate vs the default > 0.55 AND its mean QLIKE is lower, over ≥ 100
  events. Otherwise the symbol keeps the global default.
- Writes `Docs/bot_health/garch_weight_calibration.md` + `.json` and prints
  the recommended `symbol_overrides` block. **It never edits config itself**
  — a human reviews and commits, same contract as
  `run_garch_walk_forward_validation.py`.

Grid scoring lives in `garch_walk_forward_validator.py` (new function
reusing the existing QLIKE machinery), so validation and calibration share
one scoring path.

### 4. Universe coverage — backfill `--all-fno`

`backfill_daily_price_history.py` gains `--all-fno`: source symbols from
`instrument_master.list_fno_underlyings()` instead of the pilot tuple.
Existing rate limiting (1s sleep, idempotent skip) already keeps a ~200
symbol run inside the Breeze envelope. Runbook: backfill `--all-fno`, then
run the calibrator, review, commit accepted overrides.

### 5. Testing

- Validator: grid scoring returns per-candidate QLIKE/win-rate; degenerate
  candidates excluded.
- Calibrator guard: accepts a clearly-better candidate; rejects <55% win
  rate, rejects insufficient events.
- `quant_snapshot`: override used when present; fallback when absent/None;
  config with bad weights (sum≠1) surfaces the existing `_assert_weights`
  error.
- Backfill: `--all-fno` pulls from instrument master.
- Schema: defaults validate against the schema.

### Expected impact

More accurate next-day vol forecasts on ~60% of days for BANKNIFTY, NIFTY,
HDFCBANK (the highest-liquidity underlyings). After vol spikes the forecast
reacts/decays realistically instead of lagging, so fewer false cheap-vol
long entries during post-spike IV decay and truer elevated-IV calendar
triggers. No gate is loosened; this sharpens the signal feeding the gates.

### Out of scope

- Flipping `enable_mle_fit` (rejected by 2026-08-04 evidence).
- Changing the global default weights (would degrade RELIANCE/INFY).
- Automatic config mutation by the calibrator (human review stays in loop).
- P&L replay of overrides (needs closed trades; separate blocked P1 item).
