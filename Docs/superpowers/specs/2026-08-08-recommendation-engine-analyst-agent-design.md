# Recommendation Engine Analyst — subagent design

**Date:** 2026-08-08
**Status:** Approved (design), pending implementation plan

## Problem

The recommendation pipeline is the largest and least-reviewed part of this bot.
`recommendation_engine.py` alone pulls from GARCH and IV z-score signals, ATM
liquidity history, earnings calendar, universe enrichment, strategy coverage,
SH-4 strategy selection, confidence calibration and the confidence floor — and
then hands its picks to `paper_sim` to fill. When paper trading underperforms or
publishes nothing, there is no standing way to answer *why*: which stage dropped
the candidate, whether the strategy choice matched spec, whether confidence was
calibrated, or whether the fill model made the outcome unrealistic.

The existing `Guruji_for_Bhale_Bullodu` skill covers repo-wide health — P0–P2
backlog compliance, safety invariants, CI, doc drift. It deliberately does not
go deep on quant/strategy quality. That depth is the gap this agent fills.

## Goal

A reusable, read-only subagent that on each invocation:

1. Rebuilds an accurate picture of how the recommendation pipeline works today.
2. Reads real paper-trade evidence to judge how it is actually performing.
3. Reports gaps, constraints and ranked recommendations that make paper trading
   more reliable and stable while improving its measured performance.

## Scope

**In scope — the full signal → paper-trade-outcome path:**

| Stage | Files |
|---|---|
| Signals | `backend/quant/signals/garch.py`, `iv_zscore.py`; `backend/quant/{pricing,risk,costs,gamma,analytics}/` |
| Feature assembly | `backend/services/quant_snapshot.py`, `signals.py`, `universe_enrichment.py`, `atm_liquidity*.py`, `iv_history_store.py`, `candle_history.py`, `earnings_calendar.py`, `market_news.py` |
| Strategy choice | `backend/services/strategy_selection.py` (SH-4), `strategy_coverage.py` |
| Ranking & gating | `backend/services/recommendation_engine.py`, `recommendation_cycle.py`, `confidence_calibrator.py`, `confidence_floor.py` |
| Execution gates | `backend/execution/{risk_gate,circuit_breakers,options_only,broker_router}.py`, `backend/services/trade_executor.py` |
| Fill & outcome | `backend/paper_sim/{engine,chain,structure_builder,fill_model,ledger,automation,freshness}.py` |
| Feedback loop | `backend/services/learning_service.py`, `backend/analytics/confidence_calibration.py` |
| Trigger | `backend/services/trading_scheduler.py`, `market_session.py` |

Execution and `paper_sim` fill quality are explicitly **in** scope (owner
decision 2026-08-08): a recommendation that is sound but fills unrealistically
produces the same bad outcome as a bad recommendation, and the two cannot be
separated when reading the ledger.

**Out of scope:** CI, deploy, frontend, repo-wide backlog bookkeeping, Breeze
vendor integration mechanics, `knowledge/` RAG. If the agent stumbles on a
finding in Guruji's territory it notes it in one line and moves on — it does not
duplicate Guruji's P0–P2 checklist.

## Process (the agent's run loop)

**1. Model the pipeline as-built.**
Read the in-scope files and produce a current, concrete description of each
stage: what it consumes, what it emits, what causes it to drop a candidate.
Never trust a docstring's claim about behavior — read the code path.

**2. Read the evidence.**
- `backend/data/learning_store.json` — closed outcomes and open trades,
  **excluding any record with `"seed": true`** (`is_seed_outcome`).
- `paper_sim` ledger state (in-memory only today — note that P0-2c limitation
  when reasoning about what history actually survives).
- `backend/data/{atm_liquidity_history,iv_history,daily_price_history,earnings_calendar}.json`
  for feed coverage and staleness.
- Recent cycle behavior: gate rejection reasons, `STRATEGY_COVERAGE_ABORT`
  outcomes, enrichment stats, marks-usable counts.
- `pytest backend/tests/ -q -m "not integration"` for the tests covering these
  modules; a newly failing recommendation-path test is itself a finding.

**3. Compare against spec.**
Cross-reference `Docs/Trading_Strategies.md` (SH-4 table), `Docs/Trading_Parameters.md`,
and `backend/config/trading_parameters.defaults.json` against what the code
actually does. Config drift and thresholds that were relaxed for a specific
reason (e.g. the 2026-08-07 coverage relaxation: `max_symbols` 40→15,
`min_coverage_ratio` 0.80→0.60, `min_eligible_symbols` 20→6) are of particular
interest — the agent should ask whether each relaxation is still earning its
keep or is now masking a real problem.

**4. Maturity gate the performance claims.**
Follow the same discipline as Guruji: below ~30 real closed trades per module,
performance numbers are reported as directional only, never as evidence of edge.
The agent must never characterize the vol edge as validated absent OOS
walk-forward evidence (per `.cursor/rules/must-fix-before-claiming-performance.mdc`).

**5. Rank the recommendations.**
Each recommendation carries: the observed problem with `file:line` evidence, the
mechanism by which it degrades reliability/stability/performance, the proposed
change, and an impact/effort read. Ordered by expected impact. Recommendations
that would close an open P0 item outrank net-new features.

## Output

**Persisted:** `Docs/bot_health/RECOMMENDATION_ENGINE_REVIEW.md` — modeled on the
`STATE.md` + `BACKLOG.md` pattern:

- Header: last-reviewed HEAD SHA, run timestamp, real (non-seed) closed-trade
  count, test result.
- **Pipeline map** — the current as-built stage description, rewritten each run
  so it never goes stale.
- **Findings** — append-only, checked off with `resolved <date>, evidence:` when
  a later run confirms the fix. Resolved findings are never deleted.
- **Trend notes** — how the numbers moved since the previous run.

**Chat:** a summary — what changed since last review, the top findings, and one
"next best action."

## Access

Read-only with respect to all trading code. Granted tools: `Read`, `Grep`,
`Glob`, `Bash` (for `git log`/`git diff`, `pytest`, and reading JSON ledgers),
and `Write`. `Write` is granted solely so it can maintain
`Docs/bot_health/RECOMMENDATION_ENGINE_REVIEW.md`; its system prompt states that
writing to any other path is out of bounds. `Edit` is not granted, so it cannot
modify an existing source file even by mistake. It proposes changes; a human or
a follow-up task applies them.

This mirrors Guruji's model and this repo's standing caution around trading
logic: the agent that judges the engine is not the agent that edits it.

## Deliverable

A single file: `.claude/agents/recommendation-engine-analyst.md`, with
frontmatter (`name`, `description`, `tools`) and a system prompt encoding the
process above. Its `description` triggers on questions about recommendation
quality, strategy selection, confidence calibration, paper-trade performance, or
"why isn't the engine trading well" — and explicitly defers repo-wide health
questions to `Guruji_for_Bhale_Bullodu`.

## Non-goals

- Not a replacement for Guruji, and not a second backlog.
- Not an autonomous tuner — it does not adjust thresholds itself.
- Not a backtester — it reads existing evidence; building walk-forward/OOS
  replay is the separate open P1 item.
