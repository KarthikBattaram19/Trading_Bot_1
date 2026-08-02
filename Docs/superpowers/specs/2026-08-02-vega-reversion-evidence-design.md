# Vega scalping — empirical evidence for IV mean-reversion (design)

## Problem

Vega scalping's entry (`backend/quant/signals/iv_zscore.py`) fires on intraday IV
z ≤ −2. The strategy docs (`Docs/Trading_Strategies.md` §Vega Scalping) call this
"probabilistic, not a guarantee" — it assumes intraday IV is stationary enough,
often enough, that a −2σ dislocation tends to revert toward the mean rather than
keep falling. Nothing in the codebase measures whether that's true for the
instruments actually traded: no hit rate, no distribution of revert-vs-keep-falling
outcomes. This is tracked as part of the P1 "proof of edge" backlog item in
`Docs/bot_health/BACKLOG.md` (`.cursor/rules/must-fix-before-claiming-performance.mdc`).

This is narrower than the full walk-forward/OOS P&L replay in that backlog item
(which is blocked on the P0 item producing real closed trades). Measuring whether
IV itself reverts after a −2σ trigger does not depend on closed trades — it only
needs an intraday IV time series — so it can be built now.

## Data reality

The only IV history on disk (`backend/data/iv_history.json`, written by
`backend/services/iv_history_store.py`) is ~2 sessions, thin, flat-looking values —
not enough for a real measurement. Breeze does not expose historical IV directly;
it exposes historical option premium candles (`get_historical_charts`) and
underlying spot candles. This design backfills a small pilot slice of real history
by fetching those premium candles and inverting them to IV via Black-Scholes,
using the existing pricer in `backend/quant/pricing/bsm.py`.

## Scope

- Pilot universe: NIFTY, BANKNIFTY, and 2–3 liquid F&O stocks (fixed constant in
  the backfill script), ATM strike only, current expiry, maximum lookback Breeze's
  historical endpoint returns for options.
- Evidence-gathering only. This does **not** change `iv_zscore.py`'s
  `reject_vega` / entry-gating logic. A future change can wire gating once the
  evidence exists and has been reviewed — not part of this design.
- Does not attempt the full walk-forward P&L OOS replay (separate, P0-blocked
  backlog item).

## Components

### 1. `backend/quant/pricing/implied_vol.py` (new)

```
def implied_volatility(
    *, market_price: float, spot: float, strike: float, time_years: float,
    rate: float, dividend_yield: float, option_type: Literal["call", "put"],
    tol: float = 1e-6, max_iter: int = 100,
) -> float | None
```

Bisection over a volatility bracket (e.g. `[1e-4, 5.0]`), calling
`black_scholes_merton_price` from `bsm.py` each iteration. Returns `None` (does not
raise) when:
- the market price is outside the no-arbitrage bound for the option's intrinsic
  value (bracket has no sign change), or
- the solver does not converge within `max_iter`.

Callers treat `None` the same way `iv_zscore.py` already treats unusable IV
inputs — skip the bar, don't fabricate a value.

### 2. `backend/scripts/backfill_iv_history.py` (new)

One-off, rerunnable CLI script (pattern matches
`backend/scripts/connect_icici_direct.py`). For each pilot symbol:

1. Resolve current expiry and ATM strike from session-open spot (reuses instrument
   resolution already in `backend/integrations/icici_direct/market_data.py`).
2. Fetch historical option premium candles for that strike (`get_historical_charts`,
   5-minute interval, call side) and underlying spot candles for the same window.
3. For each bar, invert premium → IV via `implied_volatility`, using
   time-to-expiry computed from the bar's timestamp.
4. Append `{iv, ts}` into `iv_history.json` via `IvHistoryStore.append`, keyed
   `SYMBOL|session_date` — identical schema to what the live path already writes,
   so the validator (and `iv_zscore.py` itself) don't need to know the data's
   origin.
5. Rate-limited (sleep between calls, hard cap comfortably under the ~100
   calls/min envelope from `CLAUDE.md`). Idempotent: skips symbol/session keys
   already present unless `--force` is passed.

Not covered by automated tests beyond wiring (see Testing) — it needs live/paper
Breeze credentials to actually run, same as `connect_icici_direct.py`.

### 3. `backend/quant/analytics/vega_reversion_validator.py` (new)

Pure functions, no I/O. Given one session's IV series (`Sequence[float]`, chronological):

1. Replay the series with an expanding window mirroring `compute_iv_zscore`'s
   rolling logic (same `min_observations` default) to find every point where
   `vega_entry_signal` would have fired (z ≤ −2, usable).
2. From each trigger point forward, classify the outcome against the remaining
   points in the session, using the strategy doc's own Rule 7 (Table VS-2 — stop
   at 3σ/4σ below mean) and same-day-flattening rule:
   - `REVERTED` — z rises to ≥ −0.5 (config constant) before either stopping out
     or session end.
   - `STOP_HIT` — z falls to ≤ −3.0 (config constant) before reverting.
   - `NO_REVERT_AT_CLOSE` — neither condition met by the session's last point.
3. Aggregate across all sessions/symbols in the store: event count, outcome
   counts/percentages, per-symbol breakdown, distribution of bars-to-revert for
   `REVERTED` events.
4. Flag the aggregate as `insufficient_sample: true` when total event count < 30
   (config constant) — the report must not present a hit-rate as meaningful below
   this line.

### 4. `backend/scripts/run_vega_reversion_validation.py` (new)

CLI: loads all sessions from `iv_history.json` via `IvHistoryStore`, runs the
validator, writes:
- `Docs/bot_health/vega_reversion_evidence.md` — methodology, sample size, hit-rate
  table, per-symbol breakdown; a prominent "INSUFFICIENT SAMPLE — not yet
  validated" banner when `insufficient_sample` is true.
- A JSON sidecar (same directory) with the raw aggregate for future automation
  (e.g. a later gating decision, or the Guruji bot-health skill).

### 5. Docs / backlog updates

- `Docs/bot_health/BACKLOG.md` P1 bullet: add a sub-line pointing at
  `vega_reversion_evidence.md` and its current sample-size status, so the Guruji
  skill picks it up on the next run instead of re-flagging this as a total gap.
- `Docs/Trading_Strategies.md` §Vega Scalping: one cross-reference line to where
  the empirical evidence lives. Does not change the existing "probabilistic, not
  a guarantee" framing until real evidence justifies a stronger claim.

## Testing

- `backend/tests/quant/test_implied_vol.py` — round-trip `price → implied_vol →
  price` across moneyness levels and times-to-expiry; `None` on arbitrage-violating
  price and on non-convergence.
- `backend/tests/quant/test_vega_reversion_validator.py` — synthetic IV series
  fixtures for each outcome (`REVERTED`, `STOP_HIT`, `NO_REVERT_AT_CLOSE`) plus
  boundary cases (trigger at session end, multiple triggers in one session);
  asserts per-event classification and aggregate stats, including the
  `insufficient_sample` flag at n=29 vs n=30.
- `backend/tests/test_backfill_iv_history.py` — script exercised against a fake
  market-data adapter (no live network), asserting: correct `IvHistoryStore`
  writes, call-count stays under the configured budget, rerun is a no-op without
  `--force`.

## Out of scope

- Any change to `iv_zscore.py` entry/gating behavior.
- Full walk-forward P&L OOS replay (separate P0-blocked backlog item).
- Widening beyond the pilot universe (can follow once this pipeline is proven).
