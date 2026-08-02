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
