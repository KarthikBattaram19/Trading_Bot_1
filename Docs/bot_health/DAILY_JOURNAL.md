# Recommendation Engine — Daily Journal

Append-only record of what the bot did and what changed, newest entry first.
Written by the `recommendation-engine-analyst` agent after each session.

Entry format — the agent inserts each new `## <YYYY-MM-DD>` section directly
below the `<!-- ENTRIES BELOW -->` marker at the bottom of this preamble, so the
newest entry is always first and this format spec always stays above them:

- **Session summary** — cycles run, recommendations published, trades
  opened/closed, session P&L.
- **Decisions** — every decision the bot made and why (strategy, confidence,
  gates passed/failed).
- **Changes landed** — in-scope commits that day, with SHA and pipeline stage.
- **Recommendations implemented** — pulled from `recommendation_ledger.jsonl`,
  with SHA and current measurement status.
- **Recommended today** — new recommendations, plus running status of all open
  prior ones.

<!-- ENTRIES BELOW -->

## 2026-08-08

First analyst run. Market closed (Saturday). Reviewed at `c25caa5`.
Production probed at ~15:18 IST — reachable and healthy.

**Session summary.** No session. Cycles run: 0. Recommendations published: 0.
Trades opened: 0, closed: 0. Session P&L: none — not zero, absent. Real
(non-seed) closed trades: **0**, now confirmed on production
(`closed_trade_count: 0`, `realized_pnl: 0.0`, equity at the untouched
₹1,000,000 starting capital) rather than only inferred from the local seed
store. Today's metrics row keeps `session_traded: false`, a `no_session_reason`,
and the metric objects omitted, so no fabricated flat line enters the trend
series.

**Decisions.** The bot made none — there was no session to make them in. The
review is therefore an assessment of the machinery, not of its judgement.

**Changes landed.** None attributed. First run, no baseline — change
attribution is skipped entirely rather than inventing a baseline commit.
Attribution begins next run, anchored at `c25caa5`.

**Recommendations implemented.** None; the ledger was empty before today.

**Recommended today.** Seven new records, all `proposed`:

| id | stage | severity |
|---|---|---|
| `rec-2026-08-08-iv-history-store-resilience` | `feature_assembly` | critical (local/CI) · medium (prod) |
| `rec-2026-08-08-learning-store-atomic-write` | `feedback` | high |
| `rec-2026-08-08-candle-budget-silent-empty` | `feature_assembly` | medium — top-2 Monday risk |
| `rec-2026-08-08-iv-zscore-session-warmup` | `feature_assembly` | medium — top-2 Monday risk |
| `rec-2026-08-08-min-eligible-symbols-is-inert` | `strategy_selection` | medium |
| `rec-2026-08-08-confidence-floor-is-not-a-probability` | `ranking_gating` | medium |
| `rec-2026-08-08-empty-earnings-calendar` | `feature_assembly` | low/medium |

**The corruption finding, and a correction to my own framing.**
`backend/data/iv_history.json` is corrupt at line 24789 — two ISO timestamps
concatenated, the signature of concurrent truncate-then-write.
`IvHistoryStore._read` has no `try/except` around `json.load`;
`_build_universe` reaches the store twice per symbol —
`iv_store.append` at `recommendation_engine.py:436` (guarded by `IV > 0`) and
**`iv_store.series` at line 442, which is unconditional** — so the cycle dies on
the **first symbol with live marks**, not merely the first with positive IV.
`generate_recommendations` does not wrap it, and `_last_generation_at` is
stamped *before* the failing call, so the scheduler retries only once per 600 s:
roughly 31 identical failures across the entry window. That projection assumes
Breeze returns live marks — with no session token the store is never touched and
the failure mode is a coverage abort instead. Both branches end at zero trades.

**I initially wrote that Monday's attempt "cannot succeed" and left production
as an unquantified risk without having checked. That was wrong to leave
unqualified, and the probe moved it against my own claim.** Production declares
no persistent volume, runs a single `uvicorn` process with no `--workers`,
initialised its paper_sim ledger at container boot, and has `generations: 0`
after 1923 ticks — so the corrupt file almost certainly does not exist there.
F-1 is a **local and CI blocker**; it is not Monday's blocker.

**What production actually shows.** `supervision_mode: fully_autonomous`
(already set by the owner — my original F-8 concern about the `supervised`
default does not apply in prod), `scheduler_mode: active`, 1923 ticks with
`last_error: null`, one-trade lock free, no circuit breakers, paper_sim ready at
₹1,000,000. The entry path has never executed there, so Monday is its first-ever
run.

**Revised Monday risks, most binding first.** (1) The Breeze session token — no
token, no live marks, no GARCH, all three strategies abort. (2) Coverage at the
real 9-of-15 bar, where `vega_scalping` is a *guaranteed* abort for the first
~50 minutes and the other two ride on candles that are last in line for a shared
90 s budget. (3) Read `/api/v1/scheduler/status → last_error` first thing on
run 002: a `JSONDecodeError` there would mean F-1 *is* on production and my
downgrade was wrong.

**Not probed, deliberately.** `GET /api/v1/recommendations` is the only endpoint
that reaches the IV store, but it also calls `autonomous_execution_for`, and
production is `fully_autonomous` — it could open a paper position, and it writes
to the very file under investigation. Left alone.

**Test result.** 5 failed, 367 passed (`pytest backend/tests -m "not integration"`).

**Honesty note.** The volatility edge is not validated. No OOS walk-forward
evidence for SH-4 expectancy exists, real closed trades are 0, and the maturity
gate is ~30 per module before P&L is even directional. Nothing here says the
strategy makes money — only whether the machinery can run.

The coverage relaxations (`max_symbols=15`, `generation_budget_sec=90`,
`min_coverage_ratio=0.60`, `min_eligible_symbols=6`,
`response_cache_ttl_sec=900`) remain open questions, not settled values. Noting
the trap ahead of Monday: if a trade lands *because* a gate was loosened, that
shows the loop works end to end — it does not show the gate was too tight.
