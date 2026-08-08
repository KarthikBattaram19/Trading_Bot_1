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

**Session summary.** No session. Cycles run: 0. Recommendations published: 0.
Trades opened: 0, closed: 0. Session P&L: none — not zero, absent. Real
(non-seed) closed trades to date: **0**; all 4 records in
`learning_store.json` are seed fixtures (`trd_seed_*`) and are excluded from
every metric. Today's metrics row is written with `session_traded: false`, a
`no_session_reason`, and the `performance`/`reliability`/`stability` objects
omitted, so no fabricated flat line enters the trend series.

**Decisions.** The bot made none — there was no session to make them in. The
review is therefore an assessment of the machinery, not of its judgement.

**Changes landed.** None attributed. First run, no baseline — change
attribution is skipped entirely rather than inventing a baseline commit.
Attribution begins next run, anchored at `c25caa5`.

**Recommendations implemented.** None; the ledger was empty before today.

**Recommended today.** Seven new records, all `proposed`:

| id | stage | severity |
|---|---|---|
| `rec-2026-08-08-iv-history-store-resilience` | `feature_assembly` | critical |
| `rec-2026-08-08-learning-store-atomic-write` | `feedback` | high |
| `rec-2026-08-08-candle-budget-silent-empty` | `feature_assembly` | medium |
| `rec-2026-08-08-iv-zscore-session-warmup` | `feature_assembly` | medium |
| `rec-2026-08-08-min-eligible-symbols-is-inert` | `strategy_selection` | medium |
| `rec-2026-08-08-confidence-floor-is-not-a-probability` | `ranking_gating` | medium |
| `rec-2026-08-08-empty-earnings-calendar` | `feature_assembly` | low/medium |

**The one thing that matters for Monday.** `backend/data/iv_history.json` is
corrupt at line 24789 — two ISO timestamps concatenated, the signature of
concurrent truncate-then-write. `IvHistoryStore._read` has no `try/except`
around `json.load`, `_build_universe` calls `append` unguarded inside the
per-symbol loop, and `generate_recommendations` does not wrap it. So the first
enriched symbol with `IV > 0` kills the whole cycle. The scheduler survives —
its `_loop` swallows the exception — but `_last_generation_at` is stamped
*before* the failing call, so it retries only once per 600 s cadence: about 31
identical failures across 09:20–14:30, zero recommendations, zero trades.

**As the code stands, Monday's first-trade attempt cannot succeed.** Currently
5 tests fail from this single root cause. `backend/data/` is gitignored, so this
is untracked local runtime state, not a committed regression — but the
non-atomic `_write` means production can reach the same state unaided, and the
identical defect sits on `learning_store.json`, which holds the trade ledger.

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
