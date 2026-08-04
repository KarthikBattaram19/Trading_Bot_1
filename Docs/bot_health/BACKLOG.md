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
- [ ] Persist kill-switch armed state so it survives a process restart —
  currently an in-memory global only. (first seen 2026-08-02, evidence:
  `backend/routers/bot.py:24` `_kill_switch_armed = False`)
- [x] **One-trade lock / active-trade-id were in-memory globals, resetting
  on every restart and letting a second discretionary entry through while
  a position was still open.** `backend/services/trade_executor.py` now
  derives `is_one_trade_locked()` / `get_active_trade_id()` from the
  `paper_sim` open-trades ledger (`learning_store.json`, already disk-persisted
  by `learning_service.register_open_trade` / `record_outcome`) instead of
  module globals, so state survives a restart with no new persistence code.
  Seeded demo records are excluded via `is_seed_outcome` so the bundled
  fixture trade never blocks real entries. (first seen 2026-08-02, evidence:
  `backend/services/trade_executor.py:18-19` `_one_trade_locked = False`;
  resolved 2026-08-04, evidence: `trade_executor.get_active_trade_id`
  reads `get_learning_service().list_open_trades()`;
  `test_lock_survives_simulated_process_restart`,
  `test_seeded_demo_open_trade_does_not_lock`,
  `test_second_entry_blocked_while_one_trade_locked`)

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

- [x] **Live recommendations empty on prod (marks=0):** Breeze optionchain
  calls send empty `right` and `strike_price`
  (`backend/services/universe_enrichment.py` → `get_option_chain` defaults),
  which the vendor rejects with "Either Right or Strike-Price cannot be empty."
  FAQ requires `right="call"` (or put) with empty strike for a side snapshot.
  (first seen 2026-08-03, evidence: prod analysis text +
  `backend/integrations/icici_direct/client.py:290-305`,
  [ICICI option-chain FAQ](https://www.icicidirect.com/faqs/fno/how-to-fetch-option-chain-of-any-stock-code-using-breeze-api);
  resolved 2026-08-03, evidence: `universe_enrichment.py` `_fetch_option_chain_sides`
  fetches `right=call` then `put`;
  `test_enrich_many_fetches_spot_and_chain` asserts both sides)

- [x] **Index spot LTP uses display names first:** `_spot_ltp` calls
  `get_ltp("NSE", "BANKNIFTY")` before falling back to Breeze codes
  (`CNXBAN` / `NIFFIN` / `NIFSEL`). Burns rate budget and surfaces 503 /
  "Stock may not be available" noise. (first seen 2026-08-03, evidence:
  `backend/services/universe_enrichment.py:454-481`;
  resolved 2026-08-03, evidence: `_spot_ltp` tries `_INDEX_SPOT_STOCK_CODE`
  first; `test_index_spot_uses_breeze_stock_code_first`)

- [x] **Coverage gate vs enrichment cap contradiction:** after
  `b64ebe1`, enrichment is capped at `max_symbols=40` /
  `generation_budget_sec=20`, but `strategy_coverage` still requires
  `eligible >= 50` **and** `coverage >= 80%` of scanned (~213). Even perfect
  enrichment of 40 names cannot publish. (first seen 2026-08-03, evidence:
  `backend/config/trading_parameters.defaults.json:36-51`,
  `backend/services/strategy_coverage.py:105`;
  resolved 2026-08-03, evidence: coverage denominator uses
  `enrich_stats.requested`; `min_eligible_symbols` default 20;
  `test_coverage_uses_attempted_denominator_under_enrichment_cap`)
