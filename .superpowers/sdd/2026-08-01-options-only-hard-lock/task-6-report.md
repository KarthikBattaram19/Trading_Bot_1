# Task 6 Report: Paper-sim automation no stock rehedge legs

## Summary

- `_position_greeks` now skips residual NSE/BSE cash legs instead of modeling them as `type="stock"`.
- Legacy `increase_hedge` execution is mapped to `adjust_call_put_mix`, so automation rehedges by changing option legs only.
- Automation tests now cover the `adjust_call_put_mix` default, cash-leg skipping in Greeks construction, and `increase_hedge` remaining options-only.

## Verification

- Red run: `python -m pytest backend/tests/test_automation.py -v` failed on the new cash-leg and `increase_hedge` assertions before implementation.
- Green run: `python -m pytest backend/tests/test_automation.py -v` passed: 11 passed, 2 warnings.
- Lints: no linter errors found for `backend/paper_sim/automation.py` and `backend/tests/test_automation.py`.
