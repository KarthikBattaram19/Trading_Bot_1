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

Nor is there any measurement continuity. Changes land on the recommendation
engine regularly, but nothing records what the numbers looked like before and
after, so "did that help?" has never been answerable. Without that loop the bot
cannot converge on consistency or profit — it can only accumulate changes.

## Objective

**Drive the bot toward being consistently profitable, reliable and stable — and
prove it with measurement rather than assertion.**

Every run serves that objective by answering three questions: what did the
recommendation engine do today, what did it earn or lose, and what single change
would most improve the next day. The agent is the feedback instrument that makes
"is this getting better?" a question with a numeric answer.

An explicit honesty constraint sits on top of this objective. "High profit" is a
destination, not a claim the agent may make on the way there. Until there is
out-of-sample walk-forward evidence and a materially-sized sample of real closed
trades (per `.cursor/rules/must-fix-before-claiming-performance.mdc` and the
~30-per-module threshold in `architecture.md` §21), the agent reports observed
numbers and calls them provisional. An agent that flatters the bot is worse than
no agent, because it removes the signal the owner is relying on.

## Goal

A reusable, read-only subagent that on each invocation:

1. Rebuilds an accurate picture of how the recommendation pipeline works today.
2. Reads real paper-trade evidence to judge how it is actually performing.
3. Quantifies performance, reliability and stability — including P&L — and
   attributes movement in those metrics to specific changes made to the engine.
4. Reports gaps, constraints and ranked recommendations that make paper trading
   more reliable and stable while improving its measured performance.
5. Records the day's actions and changes durably, so the owner can verify later
   what happened and why.

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
actually does.

The 2026-08-07 coverage relaxation is a standing agenda item for this agent:
`max_symbols` 40→15, `generation_budget_sec` 20→90, `min_coverage_ratio`
0.80→0.60, `min_eligible_symbols` 20→6. Per the owner (2026-08-08) these were
allowed **only** to find out whether the bot could produce one successful paper
trade on Monday 2026-08-10 — they are a test scaffold, not approved permanent
defaults. After that date the agent must treat every one of them as an open
question and, on each run, give a reasoned position on whether it should stay,
tighten, or be replaced by a better gate — with evidence from the cycle data
about what the relaxation actually let through. The agent must never describe
these values as settled or owner-approved.

**4. Maturity gate the performance claims.**
Follow the same discipline as Guruji: below ~30 real closed trades per module,
performance numbers are reported as directional only, never as evidence of edge.
The agent must never characterize the vol edge as validated absent OOS
walk-forward evidence (per `.cursor/rules/must-fix-before-claiming-performance.mdc`).

**5. Compute the metric set and attribute movement to changes.**
See "Metrics and change attribution" below.

**6. Rank the recommendations.**
Each recommendation carries: the observed problem with `file:line` evidence, the
mechanism by which it degrades reliability/stability/performance, the proposed
change, and an impact/effort read. Ordered by expected impact. Recommendations
that would close an open P0 item outrank net-new features.

**7. Reconcile the recommendation ledger.**
See "Recommendation lifecycle" below — detect which prior recommendations have
since been implemented, and measure what they did.

**8. Append the day's journal entry.**
See "Daily journal" below.

## Recommendation lifecycle

Every recommendation the agent makes gets a stable ID and is tracked from
proposal through to measured outcome. This is the agent's memory: without it,
each run would re-propose the same fixes and never learn whether any of them
worked.

Stored in `Docs/bot_health/recommendation_ledger.jsonl`, one record per
recommendation:

| Field | Meaning |
|---|---|
| `id` | Stable slug, e.g. `rec-2026-08-08-spot-code-fallback` |
| `proposed_date` | When first raised |
| `stage` | Which pipeline stage it targets (signals, strategy selection, gating, fill, feedback…) |
| `problem` / `proposed_change` | With `file:line` evidence |
| `expected_impact` | What metric it should move, and in which direction |
| `status` | `proposed` → `implemented` → `measured` → `validated` \| `regressed` \| `inconclusive`; or `rejected` / `superseded` |
| `implemented_date`, `implemented_sha` | Detected from git, see below |
| `baseline_metrics` | Metric snapshot immediately before implementation |
| `observed_effect` | Metric deltas after, with sample size |
| `verdict` | The agent's read: did it do what it was supposed to? |

**Detecting implementation.** Each run the agent diffs `git log` since the last
review against open `proposed` recommendations, matching on the files and
symbols the recommendation named. A match promotes the record to `implemented`,
stamps the SHA and date, and freezes the pre-change metrics as `baseline_metrics`.
Detection is a heuristic, so the agent states its confidence and the owner can
correct a mis-linked record; a wrong link is visible rather than silent.

**Measuring effect.** Once implemented, the agent tracks the recommendation's
target metric across subsequent sessions and moves it to `measured`, then to a
final verdict once the sample supports one. A recommendation whose metric moved
the wrong way is marked `regressed` and raised prominently — this is the most
valuable output the ledger produces, and the agent must never quietly drop it.

Implemented recommendations appear in every surface: the chat summary, the
review doc, the day's journal entry, and their own dashboard section.

## Metrics and change attribution

The agent computes three metric families each run, plus P&L. Every metric is
stored as a dated row so trends are computable, not re-derived from prose.

**Performance (P&L)** — realized P&L for the session and cumulative; equity
curve; win rate; average win vs average loss; profit factor; max drawdown;
P&L split by strategy (SH-4 module) and by underlying.

**Reliability — did the machine do its job?** Cycles attempted vs completed;
`STRATEGY_COVERAGE_ABORT` count and reason mix; enrichment success ratio
(symbols with usable marks / attempted); spot and option-chain fetch failure
rates; gate-rejection funnel (candidates in → surviving each gate → submitted);
scheduler tick health; flatten-window completion (did every open position
actually close by 15:30?).

**Stability — is behavior consistent day to day?** Variance of daily P&L;
confidence calibration error (predicted confidence vs realized win rate, bucketed);
strategy-mix churn (does the engine pick wildly different strategies on similar
regimes?); recommendation churn within a session; parameter/config drift since
the previous run.

**Change attribution.** Each run reads `git log`/`git diff` since the previously
reviewed SHA and builds a **change ledger**: every commit that touched an
in-scope file, what it changed, and the metric deltas observed in the sessions
after it landed. This is the "how is every change impacting the bot" view.

This attribution is correlational and the agent must label it as such. With a
handful of trades, a P&L move after a commit is far more likely to be noise than
effect. The agent states the sample size next to every attribution claim and,
below a usable sample, reports the change alongside the metric movement without
asserting causation. Reliability and stability metrics (cycle completion,
coverage aborts, fetch failure rates) reach a usable sample far sooner than P&L
does — they are hundreds of events per day, not one trade — so early runs will
legitimately have confident reliability attribution and only provisional P&L
attribution. The agent should lean on that asymmetry rather than pretending both
are equally well-evidenced.

## Output

**1. Persisted narrative:** `Docs/bot_health/RECOMMENDATION_ENGINE_REVIEW.md` —
modeled on the `STATE.md` + `BACKLOG.md` pattern:

- Header: last-reviewed HEAD SHA, run timestamp, real (non-seed) closed-trade
  count, test result.
- **Pipeline map** — the current as-built stage description, plus a mermaid
  diagram of the stages and their drop conditions, rewritten each run so it
  never goes stale.
- **Findings** — append-only, checked off with `resolved <date>, evidence:` when
  a later run confirms the fix. Resolved findings are never deleted.
- **Change ledger** — commits since last review and the metric deltas after them.
- **Trend notes** — how the numbers moved since the previous run.

**2. Metrics history:** `Docs/bot_health/recommendation_metrics.jsonl` — one JSON
line per run holding the full metric set for that date. Append-only, git-tracked,
and the single source the dashboard reads. Keeping it machine-readable and
separate from the prose is what makes trends and change attribution computable
across runs instead of re-parsed from narrative.

**3. Visual dashboard:** a self-contained HTML page published as a private
Artifact, regenerated each run from the JSONL history.

Its organizing principle is the **pipeline itself**. Events and changes are laid
out in the sequential order a candidate flows through the recommendation engine,
so the owner reads the dashboard the same way the bot reads the market:

```
Signals → Feature assembly → Strategy selection → Ranking & gating
        → Execution gates → Fill (paper_sim) → Outcome & learning feedback
```

Every change, event and recommendation is tagged to the stage it belongs to and
rendered under that stage's section, in that order. A stage's section shows what
happened there this session, what changed there recently, how many candidates it
dropped, and which open recommendations target it. This makes the failure
location obvious at a glance — a funnel that collapses at "Feature assembly"
points somewhere entirely different than one that collapses at "Execution gates."

**Sections, in order:**

1. **Headline strip** — session P&L, cumulative P&L, real closed trades, win
   rate, cycles completed. Each with its delta vs the previous session.
2. **Pipeline walkthrough** — the seven stages above, in sequence. Per stage:
   candidates in/out (the funnel), this session's events, changes that landed
   here recently, and open recommendations targeting it.
3. **Impact** — what the changes actually did. The recommendation ledger
   rendered as a timeline: proposed → implemented (with SHA) → measured, each
   with its target metric plotted before/after the implementation date and its
   verdict badge (`validated` / `regressed` / `inconclusive`). Regressions
   surface at the top of this section, not buried.
4. **Optimization** — where the headroom is. Ranked open recommendations with
   expected metric movement; the largest drop-offs in the pipeline funnel;
   parameters currently pinned to test-scaffold values (the 2026-08-07
   relaxations) with the case for revisiting each.
5. **Progress** — is this converging? Equity curve with commit markers; win rate
   and profit factor trends; reliability trends (coverage ratio, enrichment
   success, cycle completion); confidence calibration plot against the diagonal;
   stability trend (rolling P&L variance); and a cumulative count of
   recommendations validated vs regressed vs still open.
6. **Journal excerpt** — the latest daily entry, with a link to the full file.

Charts must degrade honestly at low sample size — an equity curve with two
points is drawn as two points, not smoothed into a trend line, and panels
without enough data say so rather than rendering an empty axis. A "progress"
section that implies a trend from three data points would actively mislead the
decision it exists to inform.

**4. Daily journal:** `Docs/bot_health/DAILY_JOURNAL.md` — append-only, newest
entry at the top, one dated section per run recording what the bot did and what
was changed, so the owner can verify later. Each entry:

- Session summary: cycles run, recommendations published, trades opened/closed,
  session P&L.
- Every decision the bot made and why (strategy chosen, confidence, gates passed).
- Every code/config change that landed that day in scope, with commit SHA and
  the pipeline stage it touched.
- **Recommendations implemented since the last entry** — pulled from the ledger:
  which ones went in, their SHA, and their current measurement status.
- What the agent recommended today, and the running status of every open prior
  recommendation.

Those last two matter most: they close the loop, so a recommendation the owner
ignored, or one that was implemented and failed to help, is visible rather than
quietly forgotten.

**5. Recommendation ledger:** `Docs/bot_health/recommendation_ledger.jsonl` —
the lifecycle store described above. The agent's memory across runs.

**6. Chat summary:** what changed since last review, headline metrics,
recommendations implemented since last run and their measured effect, top open
findings, the dashboard URL, and one "next best action."

## Scheduling

The agent runs **on demand** (invoked directly, or by the Agent tool when a
question matches its description) and **daily after market close**.

The daily run is a Claude Code scheduled routine (created via the `schedule`
skill) firing at **16:00 IST, Monday–Friday** — 30 minutes after the 15:30 flatten
window, so the session's trades are closed and the ledger is settled. It runs the
same process, updates all four outputs, and does not require the owner's machine
to be on.

An agent cannot literally invoke itself; the routine is the mechanism that makes
the daily cadence real. Two consequences the implementation must handle:

- **Non-trading days.** The scheduler is weekday-based and this repo has no NSE
  holiday calendar (a known open item). On a day with no session the agent writes
  a short "no session" journal entry and skips metric computation rather than
  emitting a row of zeros that would corrupt the trend series.
- **Cloud environment.** The routine runs without the owner's local `.env` or
  live Breeze credentials. It reads committed state (`learning_store.json`, the
  JSONL history, git) and the deployed backend's read-only endpoints — it must
  not depend on a live broker session.

## Access

Read-only with respect to all trading code. Granted tools: `Read`, `Grep`,
`Glob`, `Bash` (for `git log`/`git diff`, `pytest`, and reading JSON ledgers),
`Write`, and `Artifact` (to publish the dashboard).

`Write` and `Edit` are scoped by its system prompt to exactly five paths:

- `Docs/bot_health/RECOMMENDATION_ENGINE_REVIEW.md`
- `Docs/bot_health/recommendation_metrics.jsonl`
- `Docs/bot_health/recommendation_ledger.jsonl`
- `Docs/bot_health/DAILY_JOURNAL.md`
- the dashboard HTML source file it publishes

Writing anywhere else — any file under `backend/`, `frontend/`, or `.cursor/` —
is out of bounds. It proposes changes to trading code; a human or a follow-up
task applies them.

The dashboard is published as a **private** Artifact. It contains the owner's
trading performance data, so the agent never shares the URL beyond this repo's
owner and never publishes anything that would present the bot's results as
validated or externally endorsed.

This mirrors Guruji's model and this repo's standing caution around trading
logic: the agent that judges the engine is not the agent that edits it. That
separation is deliberate and load-bearing — an agent that could both tune a
threshold and grade the result would be marking its own homework, on a system
where the grade is money.

## Deliverables

1. `.claude/agents/recommendation-engine-analyst.md` — the agent definition:
   frontmatter (`name`, `description`, `tools`) plus a system prompt encoding
   the objective, process, metric set, output contract and write-scope above.
   Its `description` triggers on questions about recommendation quality,
   strategy selection, confidence calibration, paper-trade performance, P&L, or
   "why isn't the engine trading well" — and explicitly defers repo-wide health
   questions to `Guruji_for_Bhale_Bullodu`.
2. A scheduled routine firing 16:00 IST on weekdays that invokes it.
3. Seeded output files: `RECOMMENDATION_ENGINE_REVIEW.md`,
   `recommendation_metrics.jsonl`, `recommendation_ledger.jsonl`,
   `DAILY_JOURNAL.md` — created empty-but-valid so the first scheduled run
   appends rather than bootstraps.

## Risks

- **Attribution noise.** With few trades, per-commit P&L attribution is mostly
  noise. Mitigated by explicit sample-size labeling and by leaning on
  reliability/stability metrics, which reach usable samples much sooner.
- **Metric theater.** A daily dashboard can create the feeling of progress
  without any. The journal's "was the prior recommendation acted on, and did it
  help?" field is the countermeasure — it makes inaction visible.
- **Schedule drift.** If the routine fails silently the trend series develops
  gaps. Each run checks for missing dates since the last entry and notes them.
- **Mis-attributed implementation.** Linking a commit to a recommendation is a
  heuristic match on files and symbols; a coincidental commit could be credited
  with a fix. Mitigated by stating match confidence on every link, so a wrong
  one is correctable rather than silently poisoning the impact measurement.
- **Self-serving grading.** The agent both proposes recommendations and grades
  them, which creates pressure toward `validated` verdicts. Countered by
  requiring the same sample-size discipline for positive verdicts as negative
  ones, and by surfacing `regressed` and `inconclusive` counts as headline
  numbers on the dashboard's Progress section — an agent whose recommendations
  are all quietly "validated" should look suspicious at a glance.

## Non-goals

- Not a replacement for Guruji, and not a second backlog.
- Not an autonomous tuner — it does not adjust thresholds itself.
- Not a backtester — it reads existing evidence; building walk-forward/OOS
  replay is the separate open P1 item.
- Not a profitability guarantee. It measures and recommends; it cannot make an
  edge exist where none is proven.
