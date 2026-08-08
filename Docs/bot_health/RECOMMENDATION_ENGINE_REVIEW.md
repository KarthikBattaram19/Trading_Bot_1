# Recommendation Engine — Analyst Review

Maintained by the `recommendation-engine-analyst` agent. Rewritten in full on
every run except the Findings and Change ledger sections, which are append-only.

Scope: the signal → strategy selection → ranking/gating → execution gates →
paper_sim fill → learning feedback path. Repo-wide health (P0–P2 backlog, CI,
safety invariants) belongs to `Guruji_for_Bhale_Bullodu` — see `BACKLOG.md`.

## Run header

Last reviewed commit: `c25caa5cce2fe01571c2269cf147312263f80124`
Last reviewed at: 2026-08-08T15:03:04+05:30 (IST, market closed)
Real (non-seed) closed trades: **0**
Last test result: **5 failed, 367 passed** (`pytest backend/tests -m "not integration"`)
Change attribution: **skipped — first run, no baseline.** No prior metrics row
exists, so there is nothing to diff against and no honest way to attribute any
commit to a metric movement. Attribution begins on the second run.

## Headline

The bot has never traded. Every record in `backend/data/learning_store.json` is
a seed fixture (`trd_seed_*`, `"seed": true`), so **real closed trades = 0,
session P&L = none, cumulative P&L = none, win rate = undefined**. Those are not
zeros to be plotted; they are absent values, and the metrics row for today is
written with `session_traded: false` and the metric objects omitted precisely so
that a future trend chart does not read a fabricated flat line at zero.

Against that baseline the single fact that matters is this: **as the code stands
today, the first-trade attempt on Monday 2026-08-10 cannot succeed.** Not
"might underperform" — cannot produce a single recommendation. The reason is a
corrupt JSON cache and an unguarded `json.load`, detailed below.

## Pipeline map

Modelled from the code at `c25caa5`, not from docstrings.

### `signals` — `backend/quant/signals/`

- `garch.py::forecast_garch_11` consumes log returns from daily closes. Requires
  `min_observations = 20`; `quant_snapshot._flat_or_short` demands
  `len(history) >= 21` and a non-constant series, else the forecast is marked
  unusable and `garch_distorted = True`. MLE fitting is **off**
  (`enable_mle_fit: false`), so the fixed 0.05/0.05/0.90 weights are always used.
- `iv_zscore.py::compute_iv_zscore` needs `min_observations = 5` samples and
  compares against `entry_z_threshold = -2.0`.
- **Drop condition:** insufficient/flat daily history, or fewer than 5 intraday
  IV samples.

### `feature_assembly` — `backend/services/`

- `universe_enrichment.enrich_many` caps the FNO list at `max_symbols = 15`
  (`EnrichmentStats.requested = len(capped)` — this matters, see Finding F-5)
  and works within a shared `generation_budget_sec = 90` deadline at
  `min_interval_ms = 700`, concurrency 4.
- `candle_history.fetch_daily_closes` goes **live to Breeze `historicalcharts`**
  every time; it does not read `backend/data/daily_price_history.json` (that
  file is a separate backfill artifact holding only 5 symbols). Any exception
  returns `[]`.
- `iv_history_store.IvHistoryStore` accumulates one ATM IV sample per symbol per
  cycle, keyed `SYMBOL|session_date`.
- `earnings_calendar.EarningsCalendarStore` — the backing file is empty (`{}`).
- `quant_snapshot.build_quant_snapshot` assembles all of it into a
  `QuantSnapshot` with explicit `SignalField.usable` flags. No synthetic fill:
  missing marks produce `marks_live = False` and every field unusable.
- **Drop condition:** no live marks; or GARCH/IV-z/RV individually unusable,
  which does not drop the symbol here but disqualifies it at the next stage.

### `strategy_selection` — `backend/services/strategy_coverage.py`

Per-strategy eligibility predicates, all requiring `marks_live` +
usable spot + usable IV:

| Strategy | Additionally requires |
|---|---|
| `simple_volatility` | usable GARCH, not distorted |
| `vega_scalping` | the above **plus** usable `iv_z_score` |
| `gamma_scalping` | `days_to_earnings <= 1` (no GARCH needed), **or** (RV-or-earnings) + usable GARCH |

A strategy publishes only when `coverage >= 0.60` **and** `eligible >= 6`.
`scanned` is the enrichment-attempted count (15), so the effective bar is
**9 of 15** — the ratio always binds harder than the count (Finding F-5).
Failure emits `STRATEGY_COVERAGE_ABORT` and the strategy is removed from
`available_strategies`.

### `ranking_gating` — `backend/services/recommendation_engine.py`

Per candidate: `_select_strategy` (restricted to `available_strategies`) →
`_evaluate_gates` (options-only lock is hard-coded: `_structure_uses_underlying`
returns `False` unconditionally) → `_score_candidate` weighted by the learning
module weight → failure-memory penalty → `ConfidenceCalibrator.apply`.
Candidates with `score <= 0` are dropped. Survivors are filtered by
`effective_min_confidence`, sorted by score, truncated to top 3.

Confidence is `min(0.95, score + 0.05)`. `backend/data/confidence_calibration.json`
does not exist, so `apply` returns the raw value as `uncalibrated`/`heuristic`
for every recommendation (Finding F-6).

### `execution_gates` — `backend/services/trade_executor.py`

Fires only when `SUPERVISION_MODE == "fully_autonomous"`; every other value,
including blank and typos, fails closed to "approval required". `.env.example`
ships `supervised` and the default in `supervision_mode.py` is `supervised`.
`is_one_trade_locked()` is ledger-derived from `learning_store.json` open trades
(seed-excluded), so it survives a restart. Then `_pre_submit_checks` (strategy
not blocked, all gates pass, lock free) and a 2% spread cap, then rank-1 →
rank-2 → rank-3 fallback.

### `fill` — `backend/paper_sim/`

`PaperEngine.submit_order` is the sole fill source for the autonomous path.
`resolve_atm_ce_leg` picks the nearest-strike CE at the nearest expiry with
DTE ≥ 10, one lot; `structure_builder` expands that into the full structure.
Rejections surface as `PaperLedgerError` / `StaleMarksError`.

### `feedback` — `backend/services/learning_service.py`

`PaperEngine.close_position` calls `record_ledger_close` (engine.py:489), which
writes the realized outcome and releases the one-trade lock. The
recommend → approve → `paper_sim` → learning loop is genuinely closed in code;
what is missing is any traffic through it.

### trigger — `backend/services/trading_scheduler.py`

Auto-started from the FastAPI lifespan (`main.py:44-46`). Phase-gated by
`market_session.session_phase`: idle when closed/pre_open; during `entry`
(09:20–14:30 IST) runs a forced cycle every `recommendation_cadence_sec = 600`
unless the one-trade lock is engaged; `no_entry` holds; `flatten` (15:15–15:30)
closes every open position through `close_position`, retrying up to 30 times.
No NSE holiday calendar — weekday check only.

## Findings

_Append-only. Resolved findings are checked off with `resolved <date>,
evidence: <file:line>` and never deleted._

### F-1 — `iv_history.json` corruption aborts the entire cycle — **CRITICAL, blocks 2026-08-10**

`backend/data/iv_history.json` is malformed at line 24789: two ISO timestamps
concatenated with no delimiter —
`"2026-08-01T18:17:30.019920+00:00""2026-08-01T18:17:29.139344+00:00"`. Two
different timestamps at one offset is the signature of two processes
truncate-then-writing the same path concurrently, not of a single bad append.

The severity comes from the call chain, not the file:

1. `IvHistoryStore._read` (`iv_history_store.py:21-26`) calls `json.load` with
   no `try/except` → `JSONDecodeError` on every read.
2. `_build_universe` calls `iv_store.append` **inside the per-symbol loop**
   (`recommendation_engine.py:436`) with no guard.
3. `generate_recommendations` does not wrap `_build_universe`
   (`recommendation_engine.py:919`).
4. `TradingScheduler._entry_tick` stamps `_last_generation_at` **before**
   calling the cycle (`trading_scheduler.py:171-172`), then the exception
   escapes into `_loop`'s broad handler (`trading_scheduler.py:118-121`).

Monday's consequence, concretely: the cycle dies on the first enriched symbol
with `IV > 0`. The scheduler survives but records `tick_error` and goes
`degraded`. Because the cadence timestamp was already stamped, it retries only
once per 600 s — roughly **31 identical failures across the 09:20–14:30 window,
zero recommendations, zero trades**. There is no path to a trade.

Two compounding defects in the same file:

- `_write` (lines 28-31) is a plain truncate-then-write — no temp file, no
  `os.replace`, no lock. This is what caused the corruption and will cause it
  again.
- The store is never pruned: **1609 keys across 8 session dates, 213 symbols,
  814 KB**, and the whole file is rewritten on *every single append*. With 15
  symbols per cycle that is ~15 full-file rewrites per cycle, growing daily —
  which steadily widens the very interleave window that corrupted it.

Blast radius today: 5 test failures — `test_fno_universe`,
`test_market_news` (×2), `test_phase0::test_recommendation_uses_feed_sources`,
`test_universe_enrichment::test_build_universe_prefers_live_marks` — all one
root cause.

Provenance, stated honestly: `backend/data/` is gitignored (`.gitignore:70`), so
the corrupt file is **untracked local runtime state**, never committed, and not
a regression introduced by this branch. I could not verify the state of the
deployed Railway volume from the repo. If that volume is empty, `_read` returns
`{}` there and the crash does not occur in production *yet* — but the
non-atomic write means production can reach this state on its own. So: a
**guaranteed local blocker** and an **unquantified production risk**. Deleting
the file clears the symptom; only the guard plus the atomic write fixes the
defect. Ledger: `rec-2026-08-08-iv-history-store-resilience`.

### F-2 — The same defect class sits on the trade ledger — **HIGH**

`learning_service.py` `_read` (305-310) and `_write` (313-315) are the same
unguarded `json.load` and the same non-atomic truncate-then-write, applied to
`learning_store.json` — the file holding open trades, the one-trade lock and
realized P&L. Corrupting it would (a) raise uncaught through
`get_active_trade_id` inside the entry tick, killing cycles exactly as F-1 does,
and (b) make `effective_min_confidence` catch the exception and **silently** fail
closed from the 0.70 bootstrap floor to the 0.80 config floor
(`confidence_floor.py:37-41`) — the engine gets stricter with no visible signal.

Not yet observed failing; proposed on a mechanism a sibling store has already
demonstrated in this deployment. The fix is deliberately asymmetric to F-1: a
regenerable cache should degrade to empty, a financial ledger must never
silently do so. Ledger: `rec-2026-08-08-learning-store-atomic-write`.

Worth noting the house pattern already exists —
`ConfidenceCalibrator.reload` (`confidence_calibrator.py:29-34`) guards its
`json.loads` correctly. These two stores are the exceptions, not a missing
convention.

### F-3 — Budget exhaustion is indistinguishable from missing data — **MEDIUM**

`_history_for` returns `[]` when the shared deadline expires
(`recommendation_engine.py:378-379`); `fetch_daily_closes` returns `[]` on any
Breeze exception (`candle_history.py:65-67`). Downstream both look identical to
a genuine data gap: GARCH unusable, reason `insufficient_or_flat_history`,
symbol ineligible for all three strategies. The 90 s budget is shared, and
enrichment runs first — 15 symbols × (spot + chain) at 700 ms minimum spacing
consumes much of it before a single candle is fetched. A coverage abort caused
by running out of time reads exactly like one caused by an empty market.
Ledger: `rec-2026-08-08-candle-budget-silent-empty`.

### F-4 — `vega_scalping` is structurally ineligible for the first ~50 min daily — **MEDIUM**

`IvHistoryStore` is keyed by session date and `compute_iv_zscore` sees only the
current session, with `min_observations = 5`. Samples accrue one per cycle at a
600 s cadence, so `iv_z_score` cannot become usable before the 5th cycle —
about 09:20 + 40–50 min. `eligible_vega_scalping` requires it, so vega coverage
is 0/15 and a `STRATEGY_COVERAGE_ABORT` is guaranteed every morning.

Beyond the cold start, the statistic itself is thin: a −2.0σ threshold on 5
same-session observations asserts a distributional claim the sample cannot
support. The store already holds 213 symbols × 8 session dates — the baseline
data exists, only the key scheme prevents using it.
Ledger: `rec-2026-08-08-iv-zscore-session-warmup`.

### F-5 — `min_eligible_symbols = 6` is inert; the real bar is 9 of 15 — **MEDIUM (clarity)**

`scanned` is `EnrichmentStats.requested`, which `enrich_many` sets to
`len(capped)` — the `max_symbols` cap of 15, not the 213-name universe
(`universe_enrichment.py:658-661`). So the ratio test needs 0.60 × 15 = **9**
eligible symbols while the count test needs 6. The ratio always binds. Anyone
reading the config will believe the bar is 6 when it is 9.

On the relaxations generally — `max_symbols=15`, `generation_budget_sec=90`,
`min_coverage_ratio=0.60`, `min_eligible_symbols=6`,
`response_cache_ttl_sec=900` are **test scaffolding**, allowed only to probe
whether a paper trade lands on 2026-08-10. They are open questions each run,
not settled or owner-approved values. And the trap for the next run is worth
stating now, before there is any result to rationalise: **if a trade lands
because the gate was loosened, that is evidence the loop works end to end — it
is not evidence the gate was too tight.** Those two conclusions must not be
merged. Ledger: `rec-2026-08-08-min-eligible-symbols-is-inert`.

### F-6 — The confidence floor gates on a score, not a probability — **MEDIUM**

Confidence is `min(0.95, score + 0.05)` (`recommendation_engine.py:979`), then
penalised by failure memory, then passed through a calibrator that has no
artifact to load — so every recommendation is `uncalibrated`/`heuristic`. The
0.70 bootstrap floor therefore means "score ≥ 0.65 after penalty", not "70%
chance of winning". The name invites a probability reading nothing supports,
and the outcome map can only be fitted from real closed outcomes, of which
there are 0 — the system cannot bootstrap out of this on its own.
Ledger: `rec-2026-08-08-confidence-floor-is-not-a-probability`.

### F-7 — Empty earnings calendar disables one third of the strategy matrix — **LOW/MEDIUM**

`backend/data/earnings_calendar.json` is literally `{}`. `days_to_earnings` is
`None` for every symbol, so `eligible_gamma_scalping`'s earnings-gap branch —
the only path that does **not** require GARCH — can never fire. That leaves
gamma dependent on the same fragile candle fetch as F-3. The seeded INFY
earnings-gap failure memory describes a mode the engine currently cannot select.
Ledger: `rec-2026-08-08-empty-earnings-calendar`.

### F-8 — Monday preconditions outside the engine (one line each)

- `SUPERVISION_MODE` defaults to `supervised` and `.env.example` ships
  `supervised`; unless it is `fully_autonomous`, `autonomous_execution_for`
  returns "approval required" and the scheduler only warms the cache.
- A valid Breeze session token is required Monday morning; `enrich_many` fails
  fast without one and `fetch_daily_closes` returns `[]`, taking GARCH — and
  therefore all coverage — to zero.
- No NSE holiday calendar (`market_session.py:33`, weekday check only). Guruji's
  territory; noted and moving on.

## Change ledger

_Append-only. In-scope commits since the previous review, paired with the
metric deltas observed after they landed._

**First run — no baseline.** Change attribution is skipped entirely rather than
inventing a baseline commit to diff against. Attribution begins on the next run,
using `c25caa5` as the anchor. When it does begin it will be labelled
correlational, with the sample size stated beside every claim: reliability
counters accrue hundreds of events per session and reach a usable sample within
days; P&L is at most one trade per day and will not be attributable for a long
time.

## Trend notes

_How the numbers moved since the previous run. Empty until two runs exist._

No trend exists. One data point is not a trend, and the one data point that
exists is a non-trading day with its metric objects deliberately omitted. The
first genuine comparison is possible after 2026-08-10.

## Maturity statement

Real closed trades: **0**. The maturity gate is ~30 real closed trades per
module before P&L is even directional. The volatility edge is **not validated**
and no OOS walk-forward evidence for SH-4 expectancy has been produced. Nothing
in this review should be read as evidence that the strategy makes money; it is
entirely an assessment of whether the machinery can run at all.
