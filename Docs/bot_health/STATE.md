# Guruji_for_Bhale_Bullodu — State

Last reviewed commit: b065e52ad07f3c061435b41128ea362d80301a06
Last reviewed at: 2026-08-07T09:06:16+05:30
Last closed-trade count seen (by module): **none yet — 0 real closed, 0 real
  open, 0 real failure memories.** `backend/data/learning_store.json` holds 3
  `outcomes`, 1 `open_trades` and 3 `failure_memories`, and the codebase's own
  `is_seed_outcome()` (`backend/analytics/confidence_calibration.py:30`)
  classifies **every one** of them as seed fixtures (`trd_seed_*`). Note the
  rows carry no literal `"seed": true` key — detection is by trade_id prefix /
  snapshot flag, so a naive `row.get("seed")` check wrongly reports 3 real
  closes. Use `is_seed_outcome` when counting.
  Still zero real closes because prod continues to publish 0 recommendations
  (`STRATEGY_COVERAGE_ABORT` on all 3 strategies). The `_spot_ltp` stock_code
  fix landed 2026-08-06 and is code- and test-verified, but the follow-up
  **intraday** re-check during live NSE hours (09:15-15:30 IST) that would
  confirm coverage clears the 80%/20 floor has still not been run — every
  attempt so far has been after close, where Breeze quote 503s dominate.
Last test result seen: 317 passed / 0 failed
  (was 320; the drop is deliberate deletion, not regression — the kill-switch
  removal branch deleted `test_kill_switch_state.py` and related cases. Full
  suite green, and `pytest -m "not integration"` is the CI selection.)

## CI status (both green, verified on GitHub)

- Backend CI `31143370053` — ruff clean, 317 passed. Only annotation is the
  advisory Mypy step (`continue-on-error: true`, 25 pre-existing errors in 14
  files) which does not fail the job.
- Frontend CI `31143370059` — new this cycle; `tsc --noEmit` clean, build ✓ 7/7
  pages.
- Node-20 deprecation annotation cleared on both (actions bumped to node24
  runtimes). `workflow_dispatch` now enabled on both workflows.

## Deployed (verified live, not just "deploy succeeded")

- Vercel Production → `b065e52`, state success. "Review & approve" CTA present
  in the served chunk; stale "no approval queue" copy gone from `/decisions`.
- Railway production → `0e19088`, state success. One commit behind Vercel, but
  `b065e52` touches only `.github/workflows/**`, so no application code is
  missing. `/health` ok, `supervision_mode: supervised`, and
  `POST /decisions/{id}/approve|reject` both return 404 (route present, id not
  found) rather than 405 (route absent).
