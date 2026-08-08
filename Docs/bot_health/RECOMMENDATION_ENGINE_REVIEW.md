# Recommendation Engine — Analyst Review

Maintained by the `recommendation-engine-analyst` agent. Rewritten in full on
every run except the Findings and Change ledger sections, which are append-only.

Scope: the signal → strategy selection → ranking/gating → execution gates →
paper_sim fill → learning feedback path. Repo-wide health (P0–P2 backlog, CI,
safety invariants) belongs to `Guruji_for_Bhale_Bullodu` — see `BACKLOG.md`.

## Run header

Last reviewed commit: `c25caa5cce2fe01571c2269cf147312263f80124`
Last reviewed at: 2026-08-08T15:03:04+05:30 (IST, market closed)
Production probed at: 2026-08-08T15:18+05:30 — reachable, healthy
Real (non-seed) closed trades: **0** (confirmed independently on production)
Last test result: **5 failed, 367 passed** (`pytest backend/tests -m "not integration"`)
Change attribution: **skipped — first run, no baseline.** No prior metrics row
exists, so there is nothing to diff against and no honest way to attribute any
commit to a metric movement. Attribution begins on the second run.

## Headline

The bot has never traded. Every record in `backend/data/learning_store.json` is
a seed fixture, and production confirms it independently:
`closed_trade_count: 0`, `open_trade_count: 0`, `realized_pnl: 0.0`, equity at
the untouched ₹1,000,000 starting capital. So **real closed trades = 0, session
P&L = none, cumulative P&L = none, win rate = undefined**. Those are not zeros
to be plotted; they are absent values, and today's metrics row is written with
`session_traded: false` and the metric objects omitted precisely so a future
trend chart does not read a fabricated flat line at zero.

`backend/data/iv_history.json` is corrupt and the code path around it has no
guard — that part is confirmed and detailed in F-1. **But the production probe
changed what that means for Monday, and it changed it in the direction that is
less favourable to my own initial claim.** The corruption is a local and CI
blocker. On production — which is where Monday actually happens — the corrupt
file almost certainly does not exist, production is already
`fully_autonomous`, the scheduler is healthy, and the binding risks for
2026-08-10 are the **Breeze session token** and the **coverage gates**, not the
corruption. See F-9.

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
**9 of 15**. At the current `max_symbols = 15` the ratio binds harder than the
count; the two swap only if `max_symbols` drops below 10, where
`min_eligible_symbols = 6` would become the binding gate (Finding F-5).
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
including blank and typos, fails closed to "approval required". The repo default
in `supervision_mode.py` and `.env.example` is `supervised`, **but production is
already set to `fully_autonomous`** (F-9). `is_one_trade_locked()` is
ledger-derived from `learning_store.json` open trades (seed-excluded), so it
survives a restart. Then `_pre_submit_checks` (strategy not blocked, all gates
pass, lock free) and a 2% spread cap, then rank-1 → rank-2 → rank-3 fallback.

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
evidence: <file:line>` and never deleted. Corrections are added as dated
**Update** blocks rather than by rewriting the original text._

### F-1 — `iv_history.json` corruption aborts the entire cycle — **CRITICAL locally / CI; see Update for production**

`backend/data/iv_history.json` is malformed at line 24789: two ISO timestamps
concatenated with no delimiter —
`"2026-08-01T18:17:30.019920+00:00""2026-08-01T18:17:29.139344+00:00"`. Two
different timestamps at one offset is the signature of two processes
truncate-then-writing the same path concurrently, not of a single bad append.

The severity comes from the call chain, not the file:

1. `IvHistoryStore._read` (`iv_history_store.py:21-26`) calls `json.load` with
   no `try/except` → `JSONDecodeError` on every read.
2. `_build_universe` reaches the store **twice** inside the per-symbol loop:
   `iv_store.append` at `recommendation_engine.py:436`, guarded only by
   `if live.iv_annualized > 0`, and `iv_store.series` at line **442**, which is
   **unconditional**. Both call `_read`. So the cycle dies on the **first symbol
   with live marks**, whether or not its IV is positive — a strictly wider
   trigger than the append path alone.
3. `generate_recommendations` does not wrap `_build_universe`
   (`recommendation_engine.py:919`).
4. `TradingScheduler._entry_tick` stamps `_last_generation_at` **before**
   calling the cycle (`trading_scheduler.py:171-172`), then the exception
   escapes into `_loop`'s broad handler (`trading_scheduler.py:118-121`).

Consequence where the corrupt file is present: the cycle dies on the first
live-marks symbol. The scheduler survives but records `tick_error` and goes
`degraded`. Because the cadence timestamp was already stamped, it retries only
once per 600 s — roughly **31 identical failures across the 09:20–14:30 window,
zero recommendations, zero trades**.

**That projection is conditional on Breeze returning live marks.** If the
session token is missing or rejected, `enrich_many` fails fast, `live is None`
for every symbol, the store is never touched, and the failure mode is instead a
`STRATEGY_COVERAGE_ABORT` on all three strategies. Both branches end at zero
trades, so "no path to a trade" holds either way — but the failure *mode* is
conditional and should not be asserted as a single certainty.

Two compounding defects in the same file:

- `_write` (lines 28-31) is a plain truncate-then-write — no temp file, no
  `os.replace`, no lock. This is what caused the corruption.
- The store is never pruned: **1609 keys across 8 session dates, 213 symbols,
  814 KB**, and the whole file is rewritten on *every single append*. With 15
  symbols per cycle that is ~15 full-file rewrites per cycle, growing daily.

Blast radius today: 5 test failures — `test_fno_universe`,
`test_market_news` (×2), `test_phase0::test_recommendation_uses_feed_sources`,
`test_universe_enrichment::test_build_universe_prefers_live_marks` — all one
root cause.

Provenance: `backend/data/` is gitignored (`.gitignore:70`), so the corrupt file
is **untracked local runtime state**, never committed, and not a regression
introduced by this branch.

> **Update 2026-08-08 15:18 IST — production probe. I over-stated the
> production severity in the original write-up.**
>
> I labelled the production exposure "unquantified risk" without having
> attempted the read-only endpoint check my own process calls for. Having now
> done it, the evidence says the corrupt file is very unlikely to exist on
> Railway, and therefore **F-1 is a local/CI blocker, not the Monday blocker**:
>
> - `railway.toml` and `Procfile` declare **no persistent volume**, and
>   `Docs/RAILWAY_DEPLOY.md` never mentions one — so `backend/data/` is
>   container-local and rebuilt on deploy.
> - `backend/scripts/start_remote.sh` runs `uvicorn` with **no `--workers`** —
>   a single process. Within one process `generate_recommendations` is
>   serialized by `_response_cache_lock`, so the concurrent-writer mechanism
>   that produced the local corruption has no obvious path on production.
> - `/api/v1/paper-sim/account` reports `updated_at`
>   `2026-08-07T17:46:56.710824Z` against a scheduler `started_at` of
>   `2026-08-07T17:46:56.712753Z` — the ledger was initialised **at container
>   boot**, consistent with a fresh, non-persistent data directory.
> - `/api/v1/scheduler/status` shows `generations: 0` after `ticks: 1923` and
>   `last_error: null`. The entry path has never executed on production, so
>   nothing has yet written to its IV store, and `_read` returns `{}` for a
>   file that does not exist.
>
> **Revised severity: critical for local and CI (it is why 5 tests fail and why
> no local cycle can run); medium for production.** The fix is unchanged and
> still worth doing — it is low effort, removes a whole failure class, and
> stops unbounded file growth — but it is **no longer the top Monday lever.**
>
> **The one thing that would flip this back:** Railway volumes can be attached
> through the dashboard UI without appearing in `railway.toml`. I cannot see
> that UI. If a volume *is* mounted at `backend/data/` and holds a corrupt
> `iv_history.json`, production is blocked exactly as described above. Settling
> this needs either a look at the Railway volume settings or one forced
> recommendation cycle on production during market hours — the latter is a
> state mutation I did not perform (see F-9).

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
demonstrated. The fix is deliberately asymmetric to F-1: a regenerable cache
should degrade to empty, a financial ledger must never silently do so.

Worth noting the house pattern already exists —
`ConfidenceCalibrator.reload` (`confidence_calibrator.py:29-34`) guards its
`json.loads` correctly. These two stores are the exceptions, not a missing
convention.

> **Update 2026-08-08 15:18 IST.** The same single-process / no-volume evidence
> in F-1's update applies here and lowers the production likelihood equally.
> The asymmetric-fix reasoning is unaffected.

### F-3 — Budget exhaustion is indistinguishable from missing data — **MEDIUM → now a top-2 Monday risk**

`_history_for` returns `[]` when the shared deadline expires
(`recommendation_engine.py:378-379`); `fetch_daily_closes` returns `[]` on any
Breeze exception (`candle_history.py:65-67`). Downstream both look identical to
a genuine data gap: GARCH unusable, reason `insufficient_or_flat_history`,
symbol ineligible for all three strategies. The 90 s budget is shared, and
enrichment runs first — 15 symbols × (spot + chain) at 700 ms minimum spacing
consumes much of it before a single candle is fetched. A coverage abort caused
by running out of time reads exactly like one caused by an empty market.

> **Update 2026-08-08 15:18 IST.** With F-1 downgraded for production, this
> becomes one of the two findings most likely to determine Monday's outcome:
> `simple_volatility` and `gamma_scalping` both need GARCH, GARCH needs live
> Breeze candles, and the candles are last in line for a shared 90 s budget.

### F-4 — `vega_scalping` is structurally ineligible for the first ~50 min daily — **MEDIUM → now a top-2 Monday risk**

`IvHistoryStore` is keyed by session date and `compute_iv_zscore` sees only the
current session, with `min_observations = 5`. Samples accrue one per cycle at a
600 s cadence, so `iv_z_score` cannot become usable before the 5th cycle —
about 09:20 + 40–50 min. `eligible_vega_scalping` requires it, so vega coverage
is 0/15 and a `STRATEGY_COVERAGE_ABORT` is guaranteed every morning.

Beyond the cold start, the statistic itself is thin: a −2.0σ threshold on 5
same-session observations asserts a distributional claim the sample cannot
support. The store already holds 213 symbols × 8 session dates locally — the
baseline data exists, only the key scheme prevents using it.

> **Update 2026-08-08 15:18 IST.** This is the only *deterministic* coverage
> abort on the list — it does not depend on Breeze behaviour or timing. On a
> fresh production data directory the local 8-session baseline does not exist
> either, so the cold start applies there in full.

### F-5 — `min_eligible_symbols = 6` is inert at the current cap; the real bar is 9 of 15 — **MEDIUM (clarity)**

`scanned` is `EnrichmentStats.requested`, which `enrich_many` sets to
`len(capped)` — the `max_symbols` cap of 15, not the 213-name universe
(`universe_enrichment.py:658-661`). So the ratio test requires 0.60 × 15 = **9**
eligible symbols while the count test requires 6. **At the current
`max_symbols = 15` the ratio always binds harder.** That relationship is not
universal: the two swap below `max_symbols = 10`, where `0.60 × scanned < 6` and
`min_eligible_symbols` becomes the binding gate. Anyone reading the config today
will believe the bar is 6 when it is 9.

On the relaxations generally — `max_symbols=15`, `generation_budget_sec=90`,
`min_coverage_ratio=0.60`, `min_eligible_symbols=6`,
`response_cache_ttl_sec=900` are **test scaffolding**, allowed only to probe
whether a paper trade lands on 2026-08-10. They are open questions each run,
not settled or owner-approved values. And the trap for the next run is worth
stating now, before there is any result to rationalise: **if a trade lands
because the gate was loosened, that is evidence the loop works end to end — it
is not evidence the gate was too tight.** Those two conclusions must not be
merged.

### F-6 — The confidence floor gates on a score, not a probability — **MEDIUM**

Confidence is `min(0.95, score + 0.05)` (`recommendation_engine.py:979`), then
penalised by failure memory, then passed through a calibrator that has no
artifact to load — so every recommendation is `uncalibrated`/`heuristic`. The
0.70 bootstrap floor therefore means "score ≥ 0.65 after penalty", not "70%
chance of winning". The name invites a probability reading nothing supports,
and the outcome map can only be fitted from real closed outcomes, of which
there are 0 — the system cannot bootstrap out of this on its own.

### F-7 — Empty earnings calendar disables one third of the strategy matrix — **LOW/MEDIUM**

`backend/data/earnings_calendar.json` is literally `{}`. `days_to_earnings` is
`None` for every symbol, so `eligible_gamma_scalping`'s earnings-gap branch —
the only path that does **not** require GARCH — can never fire. That leaves
gamma dependent on the same fragile candle fetch as F-3. The seeded INFY
earnings-gap failure memory describes a mode the engine currently cannot select.

### F-8 — Monday preconditions outside the engine

- ~~`SUPERVISION_MODE` defaults to `supervised`~~ — **corrected 2026-08-08
  15:18 IST: production reports `supervision_mode: "fully_autonomous"` and
  `autonomy: "fully_autonomous"` at `/api/v1/bot/status`.** The owner has
  already set it. The repo default and `.env.example` remain `supervised`, which
  is correct fail-closed behaviour for a fresh checkout, but this is **not** an
  open Monday risk.
- A valid Breeze session token is required Monday morning; `enrich_many` fails
  fast without one and `fetch_daily_closes` returns `[]`, taking GARCH — and
  therefore all coverage — to zero. **This is now the single largest external
  Monday risk** and I cannot verify it ahead of the session.
- No NSE holiday calendar (`market_session.py:33`, weekday check only). Guruji's
  territory; noted and moving on.

### F-9 — Production probe, 2026-08-08 ~15:18 IST — **new**

Ran the read-only endpoints my process specifies. All reachable, all HTTP 200.

| Endpoint | Result |
|---|---|
| `/health` | `status: ok`, `execution_mode: paper`, `live_blocked: false`, `place_order_enabled: false`, `database_configured: false`, `redis_configured: false` |
| `/api/v1/bot/status` | **`supervision_mode: fully_autonomous`**, `scheduler_mode: active`, `one_trade_locked: false`, `active_trade_id: null`, `circuit_breakers_active: []`, `api_health: ok` |
| `/api/v1/scheduler/status` | `state: running`, `phase: closed`, `ticks: 1923`, **`generations: 0`**, `last_generation_at: null`, `last_error: null`, started `2026-08-07T17:46:56Z` |
| `/api/v1/learning/dashboard` | `closed_trade_count: 0`, `open_trade_count: 0`, `win_rate: null`, `failure_memory_count: 0`, "3 bundled demo fixture(s) stored but excluded from metrics" |
| `/api/v1/paper-sim/positions` | `[]` |
| `/api/v1/paper-sim/account` | equity ₹1,000,000 = starting capital, `realized_pnl: 0.0`, `open_positions: 0`, `mark_provider: icici_direct_data_only` |
| `/api/v1/decisions` | `[]` |
| `/api/v1/risk/snapshot` | all greeks 0, `drawdown_pct: 0`, no breaches |

What this establishes:

1. **Zero real trades is confirmed on production**, not just inferred from the
   local seed store. Production independently excludes the 3 bundled fixtures.
2. **Production is configured and ready** — `fully_autonomous`, scheduler
   running clean for 1923 ticks with `last_error: null`, lock free, no breakers.
3. **The entry path has never run in production** (`generations: 0`, and the
   scheduler started Friday 23:16 IST, after close, followed by a weekend). So
   Monday will be its first-ever execution.
4. **F-1's production exposure is low** — see the F-1 update for the volume,
   worker-count and boot-timestamp evidence.

What this does **not** establish, stated plainly rather than guessed:

- Whether `backend/data/iv_history.json` exists on the Railway filesystem. None
  of the read-only endpoints touch that store. The only endpoint that would is
  `GET /api/v1/recommendations`, which calls `run_recommendation_cycle` →
  `_build_universe` → `IvHistoryStore`, and which also invokes
  `autonomous_execution_for`. With production on `fully_autonomous`, that is a
  request that can *open a paper position* and that *writes to the very file
  under investigation*. **I did not call it.** My hard rule is to run nothing
  that mutates repo or broker state, and probing a fault by writing to the
  suspected file would also destroy the evidence.
- Whether Monday's Breeze session token will be valid.

To settle the first point, one of: read the Railway volume settings in the
dashboard; or have the owner run one forced cycle during market hours and
capture `/api/v1/scheduler/status` (`last_error`) plus
`/api/v1/recommendations`. Monday's 09:20 cycle will answer it either way, and
run 002 should read `last_error` first.

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

## What to watch on Monday 2026-08-10

Revised after the production probe, most-binding first:

1. **Breeze session token.** No token → no live marks → no GARCH → all three
   strategies abort on coverage. Nothing downstream matters.
2. **Coverage at the 9-of-15 bar.** `vega_scalping` is a guaranteed abort for
   the first ~50 minutes (F-4). `simple_volatility` and `gamma_scalping` both
   ride on GARCH, which rides on candles that are last in line for the shared
   90 s budget (F-3). This is the most likely place a technically healthy
   production run still produces nothing.
3. **`/api/v1/scheduler/status` → `last_error`.** If it carries a
   `JSONDecodeError`, F-1 *is* present on production after all and the F-1
   update above is wrong — read this field before anything else.
4. **`generations`** climbing above 0 for the first time, and whether
   `executed` ever turns true.

## Maturity statement

Real closed trades: **0**, confirmed on production. The maturity gate is ~30
real closed trades per module before P&L is even directional. The volatility
edge is **not validated** and no OOS walk-forward evidence for SH-4 expectancy
has been produced. Nothing in this review should be read as evidence that the
strategy makes money; it is entirely an assessment of whether the machinery can
run at all.
