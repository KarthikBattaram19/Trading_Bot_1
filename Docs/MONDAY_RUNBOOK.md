# Monday Runbook — First Autonomous Closed Paper Trade

Target: Monday 2026-08-10 (and every trading day after). The backend now runs a
background **TradingScheduler** (`backend/services/trading_scheduler.py`,
started automatically on app boot) that generates recommendation cycles during
NSE hours, opens the top pick autonomously when `SUPERVISION_MODE=fully_autonomous`,
and flattens every open paper_sim position at 15:15–15:30 IST through the real
close path (which feeds `/learning/dashboard`).

## Session phases (IST, config: `session_schedule` in trading_parameters.defaults.json)

| Window | Phase | Scheduler behavior |
|---|---|---|
| before 09:15 / weekend | closed | idle |
| 09:15–09:20 | pre_open | idle (feeds settle) |
| 09:20–14:30 | entry | ensure γ–θ automation running; fresh recommendation cycle every 10 min (skipped while one-trade locked) |
| 14:30–15:15 | no_entry | automation keeps running; no new entries |
| 15:15–15:30 | flatten | close every open position via `PaperEngine.close_position`, retrying every 30s tick on stale marks |

Breeze budget: ≤ ~37 cycles × ~75 calls ≈ 2,800/day worst case — inside the
~100/min and 5,000/day envelope (spacing 700ms enforced by the rate limiter).

## Morning checklist (~08:45 IST)

1. **Breeze daily login** (manual, cannot be automated):
   customer portal → Breeze app login (`https://api.icicidirect.com/apiuser/login?api_key=<AppKey>`)
   → capture `API_Session` → set `ICICI_DIRECT_SESSION_TOKEN` on Railway.
2. **Verify Railway env vars**:
   - `EXECUTION_MODE=paper` (never live)
   - `SUPERVISION_MODE=fully_autonomous`  ← owner decision 2026-08-07 (paper only)
   - `SCHEDULER_AUTOSTART=1` (or unset — default on; `0` disables)
   - exactly **1 replica**, no scale-to-zero / sleep
3. **09:05 smoke**:
   - `GET /health/integrations` → Breeze auth OK
   - `GET /api/v1/scheduler/status` → `state: running`, `phase: pre_open`

## During the day

- 09:30–10:30: watch `GET /api/v1/scheduler/status` — `generations` should
  increment every ~10 min; `last_actions` shows per-cycle summaries
  (`executed: true` means the trade opened). Vega scalping becomes eligible
  ~10:10 once 5 intraday IV points accumulate; simple-vol/gamma can fire earlier.
- **Confidence floor**: the bootstrap floor **0.70** is active automatically until
  the first real closed trade exists; it then reverts to 0.80 on the next cycle
  (`backend/services/confidence_floor.py`). Emergency lever:
  `MIN_RECOMMENDATION_CONFIDENCE` env var (clamped 0.50–0.95).
- If no trade by ~12:00: check the recommendation `analysis_notes` for which gate
  blocks (coverage vs confidence vs liquidity) via `GET /api/v1/recommendations`.
- 14:30: entries stop by design. 15:15–15:30: watch `flatten_attempts` /
  `flatten_closed` in scheduler status. Fallback if flatten keeps failing:
  `POST /api/v1/paper-sim/positions/{id}/close` manually before 15:29.
- EOD: `GET /api/v1/learning/dashboard` → `closed_trade_count: 1`.

## Failure levers

| Symptom | Lever |
|---|---|
| Breeze 401/session errors mid-day | re-do the daily login, update `ICICI_DIRECT_SESSION_TOKEN`, restart |
| Nothing clears the confidence floor | set `MIN_RECOMMENDATION_CONFIDENCE=0.65` (restart applies it) |
| Flatten failing at the bell | manual `POST /paper-sim/positions/{id}/close` |
| Restart mid-day with open position | boot reconciliation closes the orphaned learning record at 0 PnL and releases the one-trade lock (position PnL for the day is lost — ledger persistence is still a backlog item) |

## Known limitations (tracked in Docs/bot_health/BACKLOG.md)

- paper_sim ledger is still in-memory: a restart loses the open position itself
  (reconciliation prevents the lock deadlock but not the data loss). Avoid
  redeploys/restarts while a position is open.
- No NSE holiday calendar — the scheduler treats every weekday as a trading day.
- Vega-scalp IV z-score stop (−3σ/−4σ) is still not enforced; the session-close
  flatten now is (via the scheduler).
