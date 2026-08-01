### Task 7 Report: Docs — Trading_Parameters + dependents

**Summary**
- Updated `Docs/Trading_Parameters.md` to v1.9 with the options-only hard lock: Call/Put legs only, no stock/underlying trading, no T11 spot cap, indices allowed when other gates pass.
- Updated dependent docs: `Docs/Trading_Strategies.md`, `Docs/architecture.md`, `Docs/context.md`, `Docs/Paper_Simulator.md`, `Docs/edge_cases.md`, and `Docs/implementation_plan.md`.
- Preserved historical prior/changelog references where useful while making active product rules options-only.

**Verification**
- Ran requested search: `rg -n "options and its underlying|options\+underlying|calls_stock|hedge_method.*stock|max_underlying_price|T11" Docs/`.
- Remaining hits are the new hard-lock statements, historical Prior changelog lines, or design/plan task artifacts.
- `Docs/Paper_Simulator.md` has no hits for the old dual-mode/T11 query.
- Ran `git diff --check`: pass.
- Ran Cursor lints for edited docs: no linter errors.
