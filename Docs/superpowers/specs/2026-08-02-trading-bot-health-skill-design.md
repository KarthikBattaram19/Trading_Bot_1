# Guruji_for_Bhale_Bullodu — Bot Health & Roadmap Skill — Design Spec

| Field | Value |
|---|---|
| Date | 2026-08-02 |
| Status | Approved for implementation planning |
| Approach | Activity-triggered project skill, git-delta driven, backlog-persisted |
| Authoritative priority source | `.cursor/rules/must-fix-before-claiming-performance.mdc` |

## 1. Goal

Build a Claude Code skill, scoped to this repository, that:

1. Understands the bot end-to-end (architecture, docs, code, current build status).
2. Tracks every change/update to the project since it last looked.
3. Assesses how the bot is doing — engineering health today, shifting toward real trade metrics as paper-sim evidence accumulates.
4. Identifies gaps, concerns, and issues — and keeps a durable, prioritized backlog of them.
5. Actively steers the bot's development toward becoming a robust, trustworthy, consistently profitable system, using the existing P0→P1→P2 priority backlog in `.cursor/rules/must-fix-before-claiming-performance.mdc` as the authoritative ordering — not inventing a new one.
6. Refuses to let "performance proven" / "edge validated" language get used before the evidence bar in that rule file is actually met.

This is a skill (instructions + light bookkeeping files), not new application code. It does not modify trading logic; it only reads the repo, runs existing checks (tests), and writes to its own tracking docs.

## 2. Locked decisions

| Decision | Choice |
|---|---|
| Invocation | Activity-triggered: matched by Claude via normal skill-description matching when starting work in this repo, after a batch of changes, or on direct questions about status/performance/gaps/roadmap. No cron/loop wiring. |
| Change tracking | Git log/diff since last-reviewed commit SHA is the source of truth. A small state file stores the last-reviewed SHA + timestamp; no separate parallel changelog is hand-maintained. |
| Findings persistence | Report-and-backlog: each run outputs a chat report *and* updates a durable `BACKLOG.md` (append new findings, mark resolved ones when their underlying issue is gone). |
| Performance framing | Both engineering health and paper-sim trade metrics, weighted by maturity. Below the architecture's own paper-sim promotion threshold (≥ 30 closed trades per module, `architecture.md` §2.3.1 / §21), the report leads with engineering health. At or above it, trade metrics (win rate, profit factor, Sharpe, drawdown) get equal or greater billing. |
| Roadmap priority | P0 → P1 → P2 from `.cursor/rules/must-fix-before-claiming-performance.mdc`, always. New feature ideas are surfaced only after being explicitly flagged as deferred behind open P0/P1 items, unless the user overrides for a specific request. |
| Claim discipline | The skill will not itself use, and will flag if it sees, "edge proven," "top-retail performance," or equivalent claims unless P0 items are Done and P1 item 3 (OOS walk-forward) has checked-in evidence. |
| Scope of edits | Read-only on trading code. The only files it writes are its own tracking docs (`Docs/bot_health/STATE.md`, `Docs/bot_health/BACKLOG.md`) and its own chat report. |

## 3. Components

### 3.1 `Docs/bot_health/STATE.md`

Minimal state, human-readable:

```markdown
# Bot Health Skill — State

Last reviewed commit: <sha>
Last reviewed at: <ISO date>
Last closed-trade count seen: <n>
```

Read and rewritten each run. Not a history — `git log` is the history.

### 3.2 `Docs/bot_health/BACKLOG.md`

Durable, prioritized findings log. Structure:

```markdown
# Bot Health Backlog

## P0 — integrity of the trading loop
- [ ] <finding> (first seen 2026-08-02, evidence: backend/routers/decisions.py:L42)

## P1 — proof of edge
- [x] <finding> (first seen ..., resolved 2026-08-05, evidence: ...)

## P2 — tradeable quality & live safety
- [ ] ...

## Other (deferred — no open P0/P1 blocking)
- [ ] ...
```

Findings are bucketed under the must-fix rule's own P0/P1/P2 headings so the backlog visibly mirrors that priority order rather than a skill-invented one. Items outside that rule's scope (e.g. a doc typo, a test gap unrelated to the loop) go under "Other" and are explicitly deprioritized under any open P0/P1 item.

### 3.3 SKILL.md instructions (`.claude/skills/Guruji_for_Bhale_Bullodu/SKILL.md`)

The skill body walks through, each run:

1. **Load context**: read `STATE.md` for the last-reviewed SHA; read `.cursor/rules/must-fix-before-claiming-performance.mdc` fresh every run (it is the authority, not a cached copy).
2. **Change digest**: `git log <last_sha>..HEAD` and `git diff --stat`, categorized by area touched (quant / execution / risk-gates / docs / tests / config) using path prefixes (`backend/quant`, `backend/execution`, `backend/paper_sim`, `Docs/`, `backend/tests`, schemas/config).
3. **Engineering health checks**:
   - Run the test suite (`pytest`), record pass/fail counts and any new failures vs. what the last report said.
   - Grep-based invariant checks for the specific rules the project has already committed to breaking would be dangerous: options-only hard lock (`OPTIONS_ONLY_REQUIRED`), one-trade-at-a-time (§20.4.11), `SUPERVISION_MODE` default, ATM/liquidity gate presence.
   - Doc/code drift: compare `architecture.md` / `context.md` status tables and "Last updated" claims against what the change digest actually shows landed in code.
4. **P0–P2 checklist against the must-fix rule**: for each numbered item in the rule file, determine Done / Partial / Not-done from the actual code (e.g. for P0-1, confirm one ledger is the source of truth and approve/reject are real backend endpoints when `SUPERVISION_MODE=supervised` — not just that a router file exists; for P0-2, confirm breaker/kill-switch checks live in the submit path and persist across restart, not only in-memory or dashboard-only). Cite file/line evidence for each verdict.
5. **Trade metrics (maturity-gated)**: read `backend/data/learning_store.json` / paper_sim ledger for closed-trade count, win rate, profit factor, drawdown where present. Compare count against the 30-closed-trades-per-module threshold to decide report emphasis per §2 above.
6. **Reconcile backlog**: append newly found gaps under the correct P0/P1/P2/Other bucket in `BACKLOG.md`; check off + annotate resolution date for any previously open item the current evidence shows is now fixed.
7. **Report**: concise chat output — what changed since last run, P0/P1/P2 status table with evidence pointers, engineering health scorecard, trade metrics (if material), newly opened and newly resolved backlog items, and a short "next best action" recommendation that respects P0 > P1 > P2 ordering.
8. **Update state**: rewrite `STATE.md` with the new HEAD SHA, timestamp, and closed-trade count.

## 4. Non-goals

- The skill does not execute trades, change trading parameters, or edit quant/execution code.
- The skill does not replace CI — it reads test results, it does not become the test runner of record.
- The skill does not invent its own priority framework; `.cursor/rules/must-fix-before-claiming-performance.mdc` stays the single source of truth for ordering. If that file changes, the skill's next run picks up the change automatically since it's read fresh each time.

## 5. Testing

Since this is a skill (instructions + two tracking docs), verification is a dry run rather than unit tests:

1. First run against current repo state (no prior `STATE.md`) — confirm it produces a sensible full-history-since-start report and creates both tracking files correctly.
2. Deliberately introduce a violation of one invariant (e.g. temporarily comment out an `OPTIONS_ONLY_REQUIRED` check) in a throwaway branch/worktree and confirm the skill's grep-based check actually flags it — proves the check isn't just decorative.
3. Confirm the P0/P1/P2 checklist produces Partial/Not-done (not a false Done) for at least one currently-incomplete item, using real evidence from the codebase.
