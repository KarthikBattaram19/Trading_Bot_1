# Daily Runbook — Autonomous Paper Session

The backend runs a background **TradingScheduler**
(`backend/services/trading_scheduler.py`, started automatically on app boot):
it generates recommendation cycles during NSE hours, opens the top pick when
`SUPERVISION_MODE=fully_autonomous`, and flattens every open paper_sim position
at 15:15–15:30 IST through the real close path (which feeds
`/learning/dashboard`).

There is **no forced-trade mode**. If a day produces no trade, that is the gates
doing their job on the day's data — it is not a failure to be tuned away. The
one-trade-on-a-deadline scaffolding (relaxed coverage caps, a 0.70 bootstrap
confidence floor, a `MIN_RECOMMENDATION_CONFIDENCE` env lever) was removed on
2026-08-08; see "Why there are no levers" below.

## Session phases (IST, config: `session_schedule` in trading_parameters.defaults.json)

| Window | Phase | Scheduler behavior |
|---|---|---|
| before 09:15 / weekend | closed | idle |
| 09:15–09:20 | pre_open | idle (feeds settle) |
| 09:20–14:30 | entry | ensure γ–θ automation running; fresh recommendation cycle every 15 min (skipped while one-trade locked) |
| 14:30–15:15 | no_entry | automation keeps running; no new entries |
| 15:15–15:30 | flatten | close every open position via `PaperEngine.close_position`, retrying every 30s tick on stale marks |

## Scan capacity and the Breeze budget

`backend/services/scan_capacity.py` derives how many underlyings a cycle may
scan, from the paced call budget rather than a hand-set `max_symbols`:

```
enrichment window = generation_budget_sec (120s) × enrichment_budget_frac (0.70) = 84s
wall-clock cap    = 84s / (5 calls × 0.7s)                                       = 24
daily cap         = breeze_daily_call_budget (3500) / (21 cycles × 7 calls)      = 23
max_symbols       = min(24, 23)                                                  = 23
min_eligible      = ceil(min_coverage_ratio 0.80 × 23)                           = 19
→ 23 × 7 × 21 = 3381 Breeze calls/day, inside the ~5000/day vendor envelope
```

`validate_scan_capacity()` runs in the FastAPI lifespan: a configuration where
those numbers cannot all hold **refuses to boot** with the offending arithmetic
in the message. A silently-truncated scan that publishes nothing is exactly the
failure mode this replaced.

## Morning checklist (~08:45 IST)

1. **Breeze daily login** (manual, cannot be automated):
   customer portal → Breeze app login (`https://api.icicidirect.com/apiuser/login?api_key=<AppKey>`)
   → capture `API_Session` → set `ICICI_DIRECT_SESSION_TOKEN` on Railway.
2. **Verify Railway env vars**:
   - `EXECUTION_MODE=paper` (never live)
   - `SUPERVISION_MODE` — `fully_autonomous` for unattended paper sessions,
     `supervised` if you want to approve each entry yourself
   - `SCHEDULER_AUTOSTART=1` (or unset — default on; `0` disables)
   - `MIN_RECOMMENDATION_CONFIDENCE` — **must not be set**; the var is no longer
     read, and leaving a stale value in the dashboard is misleading
   - exactly **1 replica**, no scale-to-zero / sleep
3. **09:05 smoke**:
   - `GET /health/integrations` → Breeze auth OK
   - `GET /api/v1/scheduler/status` → `state: running`, `phase: pre_open`

## During the day

- 09:30 onward: `GET /api/v1/scheduler/status` — `generations` should increment
  every ~15 min; `last_actions` shows per-cycle summaries (`executed: true`
  means a trade opened). Vega scalping becomes eligible ~10:10 once 5 intraday
  IV points accumulate; simple-vol/gamma can fire earlier.
- No trade by midday? Read `analysis_notes` in `GET /api/v1/recommendations` —
  it now carries the derived scan capacity line plus the per-strategy
  `STRATEGY_COVERAGE` rows, so you can see which gate actually bound. **Record
  it; do not loosen it.** A gate that blocks on thin data is information about
  the day, and repeated blocks are input to the
  `recommendation-engine-analyst` review, not a config emergency.
- 14:30: entries stop by design. 15:15–15:30: watch `flatten_attempts` /
  `flatten_closed` in scheduler status. Fallback if flatten keeps failing:
  `POST /api/v1/paper-sim/positions/{id}/close` manually before 15:29.
- EOD: `GET /api/v1/learning/dashboard` → `closed_trade_count`.

## Why there are no levers

| Removed 2026-08-08 | Why |
|---|---|
| `bootstrap_min_confidence` 0.70 | A floor that loosens *because* nothing has traded yet inverts the purpose of a floor. 0.80 applies from the first cycle. |
| `MIN_RECOMMENDATION_CONFIDENCE` env var | An out-of-band threshold change with no audit trail, reachable from a dashboard at 12:00 on a slow day. |
| `max_symbols` (hand-set 15, previously 40) | Now derived from the call budget, so it cannot silently contradict it. |
| `min_coverage_ratio` 0.60, `min_eligible_symbols` 6 | Restored to 0.80 / derived. The old 0.80-of-20 gate was unreachable because the *budget* was wrong, not because the gate was strict. |

## Genuine failure levers (operational, not gate-loosening)

| Symptom | Lever |
|---|---|
| Breeze 401/session errors mid-day | re-do the daily login, update `ICICI_DIRECT_SESSION_TOKEN`, restart |
| Flatten failing at the bell | manual `POST /paper-sim/positions/{id}/close` |
| Restart mid-day with open position | boot reconciliation closes the orphaned learning record at 0 PnL and releases the one-trade lock (position PnL for the day is lost — ledger persistence is still a backlog item) |
| App refuses to boot with `UnsatisfiableScanConfig` | read the message: it names which of budget / daily envelope / cache TTL is inconsistent and what to raise. Never satisfy it by lowering `min_coverage_ratio`. |

## Known limitations (tracked in Docs/bot_health/BACKLOG.md)

- paper_sim ledger is still in-memory: a restart loses the open position itself
  (reconciliation prevents the lock deadlock but not the data loss). Avoid
  redeploys/restarts while a position is open.
- No NSE holiday calendar — the scheduler treats every weekday as a trading day.
- Vega-scalp IV z-score stop (−3σ/−4σ) is still not enforced; the session-close
  flatten now is (via the scheduler).
- P1 walk-forward/OOS evidence is still absent: no claim about edge or
  expectancy is supported yet, trade or no trade.
