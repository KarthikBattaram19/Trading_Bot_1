# Guruji_for_Bhale_Bullodu Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `Guruji_for_Bhale_Bullodu` project skill — a git-delta-driven bot health, change-tracking, and P0/P2 roadmap-gating reviewer for this repo — per the approved spec.

**Architecture:** A single `.claude/skills/Guruji_for_Bhale_Bullodu/SKILL.md` instructions file drives the review process each run: read state → digest git changes since last review → run engineering health checks → check the P0–P2 checklist in `.cursor/rules/must-fix-before-claiming-performance.mdc` against real code → reconcile a persistent backlog → report in chat → update state. Two lightweight tracking docs (`Docs/bot_health/STATE.md`, `Docs/bot_health/BACKLOG.md`) persist across runs and are seeded now with the real findings already produced during design (`Docs/bot_health/SAMPLE_REPORT.md`), so the skill's first live run picks up from today's real state instead of re-deriving it.

**Tech Stack:** Markdown-only (skill instructions + tracking docs); no application code changes. Verification is a dry run against the live repo (pytest + grep-based checks), not unit tests, since this is process documentation, not code.

## Global Constraints

- Skill name/directory: `Guruji_for_Bhale_Bullodu` (user-specified; exact casing/underscores as given — overrides the hyphens-only convention from generic skill-authoring guidance).
- The skill is read-only with respect to trading code. It may only write `Docs/bot_health/STATE.md` and `Docs/bot_health/BACKLOG.md`.
- `.cursor/rules/must-fix-before-claiming-performance.mdc` is read fresh every run — never cached or copied into the skill body.
- P0 > P1 > P2 ordering from that rule file governs recommendation priority; the skill never invents its own ordering.
- No "edge proven" / "top-retail performance" language may be produced by the skill unless P0 items are Done and P1 item 3 has checked-in OOS evidence.
- Below 30 closed paper_sim trades per module (the architecture's own promotion threshold, `Docs/architecture.md` §2.3.1/§21), reports lead with engineering health; at/above it, trade metrics get equal-or-greater billing.

---

### Task 1: Seed the tracking docs from today's real findings

**Files:**
- Create: `Docs/bot_health/STATE.md`
- Create: `Docs/bot_health/BACKLOG.md`
- Reference (read-only, do not modify): `Docs/bot_health/SAMPLE_REPORT.md`

**Interfaces:**
- Consumes: nothing (first artifacts in the chain).
- Produces: `STATE.md` with a `Last reviewed commit:` line and `Last closed-trade count seen:` line that Task 2's SKILL.md instructions read on every run; `BACKLOG.md` with `## P0`, `## P1`, `## P2`, `## Other` headings and checkbox items that Task 2's SKILL.md instructions append to / check off on every run.

- [ ] **Step 1: Write `Docs/bot_health/STATE.md`**

```markdown
# Guruji_for_Bhale_Bullodu — State

Last reviewed commit: 31e928fc0dd73deb49d631a4e77d73979b353b3f
Last reviewed at: 2026-08-02T19:59:54+05:30
Last closed-trade count seen: 0
```

(This is the HEAD commit at the time the design's manual dry run — `Docs/bot_health/SAMPLE_REPORT.md` — was produced. Seeding it here means the skill's first real run treats everything from this point forward as new, instead of re-walking full history the human already reviewed.)

- [ ] **Step 2: Write `Docs/bot_health/BACKLOG.md`**

```markdown
# Guruji_for_Bhale_Bullodu — Backlog

Findings are bucketed under the priority headings from
`.cursor/rules/must-fix-before-claiming-performance.mdc` (read fresh each
run — this file does not redefine that priority order, only tracks status
against it). Items outside that rule's scope go under "Other" and stay
deprioritized behind any open P0/P1 item.

## P0 — integrity of the trading loop

- [ ] Build real `POST /approve` and `POST /reject` endpoints in
  `backend/routers/decisions.py`, make the `paper_sim` ledger the single
  source of truth, and exclude seed/demo records from `/learning` metrics.
  (first seen 2026-08-02, evidence: `backend/routers/decisions.py:1`,
  `backend/data/learning_store.json` — all records currently `"seed": true`)
- [ ] Persist kill-switch armed state and the open-position book so they
  survive a process restart — currently in-memory globals only.
  (first seen 2026-08-02, evidence: `backend/routers/bot.py:24`
  `_kill_switch_armed = False`)

## P1 — proof of edge

- [ ] No walk-forward/OOS replay evidence exists yet for SH-4 expectancy
  claims — blocked on the P0-1 item above producing real closed trades to
  replay against. (first seen 2026-08-02)
- [ ] No skew/term-structure regime filter module exists under
  `backend/quant` — India VIX level alone doesn't meet the rule's
  Definition of Done for this item. (first seen 2026-08-02, evidence:
  `grep -rli "skew\|term_structure" backend/quant` → no matches)

## P2 — tradeable quality & live safety

- [ ] Confirm whether existing cost/Greeks-limit modules
  (`backend/quant/costs/transaction_cost.py`,
  `backend/quant/risk/greeks_limits.py`,
  `backend/quant/gamma/hedge_optimizer.py`) feed an explicit delta/vega-target
  sizing calc in ranking, or whether that wiring still needs building.
  (first seen 2026-08-02, needs follow-up read)
- [ ] No fill/reconcile state machine found — required before any live
  micro-capital phase. (first seen 2026-08-02, evidence:
  `grep -rli "reconcile\|fill_state\|order_state" backend --include=*.py`
  excluding tests → no matches)

## Other — deferred behind open P0/P1

- [ ] RAG chat was shipped then un-shipped pending a Track B rebuild plan —
  not blocking, tracked for awareness only. (first seen 2026-08-02)
```

- [ ] **Step 3: Verify the files parse as the report format expects**

Run: `grep -c "^## " "Docs/bot_health/BACKLOG.md"`
Expected: `4` (P0, P1, P2, Other headings present)

Run: `grep -c "Last reviewed commit:" "Docs/bot_health/STATE.md"`
Expected: `1`

- [ ] **Step 4: Commit**

```bash
git add Docs/bot_health/STATE.md Docs/bot_health/BACKLOG.md
git commit -m "Seed Guruji_for_Bhale_Bullodu tracking docs from approved dry-run findings"
```

---

### Task 2: Write the skill instructions

**Files:**
- Create: `.claude/skills/Guruji_for_Bhale_Bullodu/SKILL.md`

**Interfaces:**
- Consumes: `Docs/bot_health/STATE.md` (`Last reviewed commit:` SHA), `Docs/bot_health/BACKLOG.md` (existing checkbox items), `.cursor/rules/must-fix-before-claiming-performance.mdc` (P0–P2 items + Definition of Done bullets, read fresh), `Docs/architecture.md` §2.3.1/§21 (30-closed-trades threshold), `backend/data/learning_store.json` (trade counts).
- Produces: an updated `Docs/bot_health/STATE.md` (new SHA/timestamp/trade-count), an updated `Docs/bot_health/BACKLOG.md` (new findings appended under the correct heading, resolved findings checked off with a resolution date), and a chat report following the structure in `Docs/bot_health/SAMPLE_REPORT.md` §1–§6.

- [ ] **Step 1: Create the skill directory**

```bash
mkdir -p ".claude/skills/Guruji_for_Bhale_Bullodu"
```

- [ ] **Step 2: Write `.claude/skills/Guruji_for_Bhale_Bullodu/SKILL.md`**

```markdown
---
name: Guruji_for_Bhale_Bullodu
description: Use when starting work in this repo, after a batch of changes has landed, or when asked about bot status, performance, gaps, concerns, or what's next — tracks every change since the last review, checks engineering health and the P0-P2 must-fix backlog against real code, and reports a prioritized roadmap toward a trustworthy, consistently profitable bot.
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
```

- [ ] **Step 3: Verify frontmatter is well-formed**

Run: `python -c "import yaml,sys; d=open('.claude/skills/Guruji_for_Bhale_Bullodu/SKILL.md').read().split('---')[1]; yaml.safe_load(d); print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add ".claude/skills/Guruji_for_Bhale_Bullodu/SKILL.md"
git commit -m "Add Guruji_for_Bhale_Bullodu bot-health and roadmap-gating skill"
```

---

### Task 3: Dry-run verification against the live repo

**Files:**
- No new files. Uses everything from Task 1 and Task 2.
- Test: manual verification steps below (this is process documentation, not code — verification is behavioral, not `pytest`).

**Interfaces:**
- Consumes: `.claude/skills/Guruji_for_Bhale_Bullodu/SKILL.md` (Task 2), `Docs/bot_health/STATE.md` / `BACKLOG.md` (Task 1).
- Produces: confidence that the skill's instructions are followable and its checks are real (not decorative) before treating the build as done.

- [ ] **Step 1: Confirm today's dry run already covered the "first report" case**

`Docs/bot_health/SAMPLE_REPORT.md` (produced during design, before this
plan) already demonstrates the report shape end-to-end using real repo
evidence. Task 1 seeded `STATE.md`/`BACKLOG.md` from that same run, so
there is no separate "first invocation" test to repeat — confirm by reading
`Docs/bot_health/SAMPLE_REPORT.md` §5 and `Docs/bot_health/BACKLOG.md`
side by side.

Expected: the P0/P1/P2/Other items in both files match 1:1.

- [ ] **Step 2: Prove the invariant check isn't decorative**

In a scratch copy (do not touch the working tree):

```bash
git worktree add ../guruji-invariant-check-scratch HEAD
```

In `../guruji-invariant-check-scratch`, temporarily comment out one
`OPTIONS_ONLY_REQUIRED` raise (e.g. in
`backend/execution/__init__.py` or wherever the shared gate lives — find it
with `grep -rn "OPTIONS_ONLY_REQUIRED" backend/ | grep -i "def \|raise"`),
then re-run the grep check from SKILL.md step 3:

```bash
grep -rl "OPTIONS_ONLY_REQUIRED" backend/
```

Expected: the file with the commented-out raise still matches the grep
(proving the check needs to inspect *behavior*, not just presence of the
string) — confirm the SKILL.md step 3 instruction says to verify the code
still raises/rejects, not merely that the string exists in the file. Fix
the instruction if it would have produced a false "Done".

Remove the scratch worktree when finished:

```bash
git worktree remove ../guruji-invariant-check-scratch --force
```

- [ ] **Step 3: Confirm at least one P0/P1/P2 item is correctly NOT marked Done**

Re-read `backend/routers/decisions.py` and confirm it still contains no
`POST` route as of current HEAD.

Run: `grep -n "@router.post" backend/routers/decisions.py`
Expected: no output (confirms P0-1 correctly stays Not-done — this is the
real behavior the skill's evidence-citing instruction depends on).

- [ ] **Step 4: Record the verification outcome**

No file changes needed if all three steps pass as expected. If Step 2
surfaces a gap in the SKILL.md instructions, apply the fix, re-run Step 2,
then commit:

```bash
git add ".claude/skills/Guruji_for_Bhale_Bullodu/SKILL.md"
git commit -m "Tighten Guruji invariant-check instruction after dry-run verification"
```

(Only run this commit if Step 2 actually required a change.)

---

### Task 4: Commit the already-modified design spec and pending rule file

**Files:**
- Modify: `Docs/superpowers/specs/2026-08-02-trading-bot-health-skill-design.md` (already edited earlier this session — rename to Guruji_for_Bhale_Bullodu)
- Create (from working tree, already edited): `.cursor/rules/must-fix-before-claiming-performance.mdc`

**Interfaces:**
- Consumes: nothing new.
- Produces: a clean working tree with all skill-related work committed.

- [ ] **Step 1: Check status**

Run: `git status --short`
Expected: only skill-related files pending (the design spec edit and the
`.mdc` rule file); the unrelated `Docs/stitch_bhale_bullodu_trading_cockpit.zip`
must NOT be added.

- [ ] **Step 2: Stage and commit**

```bash
git add "Docs/superpowers/specs/2026-08-02-trading-bot-health-skill-design.md" ".cursor/rules/must-fix-before-claiming-performance.mdc"
git commit -m "Rename bot-health skill to Guruji_for_Bhale_Bullodu; add Definition-of-Done criteria to must-fix rule"
```

- [ ] **Step 3: Confirm clean tree for skill-related paths**

Run: `git status --short -- .claude Docs/bot_health Docs/superpowers .cursor`
Expected: no output.
