# Task 5 Report: Paper-sim open path rejects cash underlying legs

## Status

Done.

## Changes

- Added a paper-sim open-path guard that rejects any NSE/BSE cash underlying leg at the start of `_resolve_and_gate_legs` with `OPTIONS_ONLY_REQUIRED`.
- Removed the legacy index+stock rejection block and numeric spot-cap block from the paper-sim open gate.
- Changed `PaperSimConfig.underlying_price_cap_inr` default to `0.0` and default `rehedge_method` to `adjust_call_put_mix`.
- Aligned paper position and ledger fallback rehedge defaults with `adjust_call_put_mix`.
- Added `backend/tests/test_paper_sim_options_only.py` and updated legacy paper-sim tests away from stock-open / cap assertions.

## Tests

- `python -m pytest backend/tests/test_paper_sim_options_only.py -v`
- `python -m pytest backend/tests/test_paper_sim_options_only.py backend/tests/test_automation.py backend/tests/test_phase1_10_paper_stack.py -v`
- `python -m pytest backend/tests/test_paper_sim.py -v`
- Cursor lints: no linter errors found for touched files.

## Concerns

- Test runs emit existing dependency warnings from `fastapi.testclient`/Starlette and Chroma telemetry; no test failures.
