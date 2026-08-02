---
name: Guruji_for_Bhale_Bullodu
description: Use when starting work in this repo, after a batch of changes has landed, or when asked about bot status, performance, gaps, concerns, or what's next.
---

# Guruji_for_Bhale_Bullodu

## Overview

Guruji is this repo's standing reviewer: it reads what changed since it last
looked, checks whether the bot's safety invariants and the priority backlog
in `.cursor/rules/must-fix-before-claiming-performance.mdc` are actually true
in code (not just documented), and keeps a durable, prioritized list of gaps
so nothing found gets lost between sessions. It is read-only with respect to
trading code — it only writes its own tracking docs
(`Docs/bot_health/STATE.md`, `Docs/bot_health/BACKLOG.md`) and a chat report.

Its job is not just to report — it actively steers "make it better" work
toward the P0 > P1 > P2 order in the must-fix rule, and refuses to endorse
"edge proven" / "top-retail performance" language until that rule's evidence
bar is met.

## When to run this

- Starting a work session that touches `backend/` or `frontend/` in this repo
- After a batch of commits has landed and you want to know what changed
- Any direct question about bot status, performance, health, gaps, concerns,
  readiness, or "what should we do next"
- Before agreeing to characterize the bot's performance or edge in any way

## Process

1. **Load context**
   - Read `Docs/bot_health/STATE.md` for the last-reviewed commit SHA and
     last closed-trade count.
   - Read `.cursor/rules/must-fix-before-claiming-performance.mdc` fresh —
     it is the priority authority, never paraphrase from memory.
   - Read `Docs/bot_health/BACKLOG.md` for currently-open findings.

2. **Change digest**

   Run `git log <last_sha>..HEAD --oneline` and `git diff <last_sha>..HEAD --stat`.
   Categorize touched paths:

   | Path prefix | Area |
   |---|---|
   | `backend/quant/` | Quant |
   | `backend/execution/`, `backend/paper_sim/` | Execution / risk |
   | `backend/routers/`, `backend/services/` | API / services |
   | `Docs/` | Docs |
   | `backend/tests/`, `frontend/**/*.test.*` | Tests |
   | `*.schema.json`, `backend/config*` | Config |
   | anything else | Other |

   If `<last_sha>` is missing from `STATE.md` (shouldn't happen after Task 1
   seeds it, but if `STATE.md` is ever deleted) fall back to full history
   (`git log --reverse --oneline`).

3. **Engineering health**
   - Run `pytest -q` from repo root. Record pass/fail counts.
   - Grep-verify safety invariants actually still hold:
     - `grep -rl "OPTIONS_ONLY_REQUIRED" backend/` — options-only lock present
       across structure_builder / paper_sim / signals / recommendations.
     - One-trade-at-a-time (architecture.md §20.4.11) — check the
       discretionary-entry gate still enforces at most one pending/open
       entry per session.
     - `SUPERVISION_MODE` default — confirm the code default matches
       `architecture.md` §1.2/§2.3.1 (`supervised`).
   - Doc/code drift: compare `architecture.md` / `context.md` "Last
     updated" / status-table claims against what the change digest (step 2)
     actually shows landed.

4. **P0 → P2 checklist**

   For every numbered item in
   `.cursor/rules/must-fix-before-claiming-performance.mdc`, evaluate its
   **Definition of Done** bullet against real code (grep, read the relevant
   file, do not trust a docstring or comment claiming compliance — verify
   the behavior). Mark each **Done / Partial / Not-done** with file:line
   evidence. Never mark Done without a specific citation.

5. **Trade metrics (maturity-gated)**

   Read `backend/data/learning_store.json` (and the `paper_sim` ledger if
   present). Count closed trades per module, excluding any record with
   `"seed": true` or equivalent synthetic marker. Compare against the
   30-closed-trades-per-module threshold (`architecture.md` §2.3.1/§21):
   - Below threshold: report leads with engineering health; trade metrics
     get a brief "not yet material" note.
   - At/above threshold: report win rate, profit factor, and drawdown
     alongside engineering health with equal or greater billing.

6. **Reconcile backlog**

   In `Docs/bot_health/BACKLOG.md`:
   - Append new findings under the matching `## P0` / `## P1` / `## P2` /
     `## Other` heading, each with `(first seen <date>, evidence: <file:line>)`.
   - For any existing open item the current evidence shows is now
     satisfied, check it off and append `resolved <date>, evidence: <file:line>`.
   - Never delete a resolved item — checked-off history stays.

7. **Report**

   Post a chat report shaped like `Docs/bot_health/SAMPLE_REPORT.md` §1–§6:
   change digest, engineering health, P0→P2 checklist table with evidence,
   trade metrics, newly opened/resolved backlog items, and one "next best
   action" that respects P0 > P1 > P2 ordering (the single highest-leverage
   open P0 item, or highest-leverage P1 if all P0 items are Done, etc.).

   **Claim gate:** before using or endorsing any "edge proven" /
   "top-retail performance" / "validated" language anywhere in the report
   or in response to a direct request to characterize performance, confirm
   all P0 items are Done and P1 item 3 (OOS walk-forward) has checked-in
   evidence. If not, say plainly what's missing instead of hedging toward
   the claim.

8. **Update state**

   Rewrite `Docs/bot_health/STATE.md` with the new HEAD SHA, current
   timestamp, and the closed-trade count found in step 5.

## Quick reference

| Question | Where to look |
|---|---|
| What's the current priority order? | `.cursor/rules/must-fix-before-claiming-performance.mdc` (read fresh, never cached) |
| What's already known to be broken/missing? | `Docs/bot_health/BACKLOG.md` |
| What did we last review up to? | `Docs/bot_health/STATE.md` |
| What does a full report look like? | `Docs/bot_health/SAMPLE_REPORT.md` (format reference) |
| Is the bot's trade history real yet? | `backend/data/learning_store.json` — check for `"seed": true` |

## Common mistakes

- Marking a P0–P2 item Done because a doc or docstring claims it, without
  reading the actual code path. `backend/routers/decisions.py` literally
  documents itself as read-only in a docstring — that's exactly the kind of
  claim to verify, not trust.
- Weighting trade metrics before the 30-closed-trades threshold is met, or
  while the ledger is still full of `"seed": true` demo records.
- Inventing a new priority order instead of using P0 > P1 > P2 from the
  must-fix rule file.
- Deleting or overwriting resolved backlog items instead of checking them
  off — the resolution history is part of the value.
