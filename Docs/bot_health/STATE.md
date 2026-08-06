# Guruji_for_Bhale_Bullodu — State

Last reviewed commit: 96d09201dc144ae33fabd39a84c1e2887cf8e60f
Last reviewed at: 2026-08-06T00:00:00+05:30
Last closed-trade count seen (by module): none yet — learning_store.json still
  has 3 `trd_seed_*` fixture outcomes on disk, but `/learning` dashboard metrics
  exclude them (0 real closed / 0 real open / 0 real failure-memory rows).
  Real closes now flow from `PaperEngine.close_position` → `record_ledger_close`.
  Still zero real closes: today's prod cycle published 0 recommendations
  (STRATEGY_COVERAGE_ABORT on all 3 strategies). Fixed the `_spot_ltp`
  stock_code bug same day (BACKLOG.md "Other" section) — code-verified
  correct, but after-hours re-test still showed low live coverage due to
  Breeze quote 503s outside market hours; needs an intraday re-check to
  confirm coverage clears the 80%/20 floor.
Last test result seen: 320 passed / 0 failed
