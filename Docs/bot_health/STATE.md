# Guruji_for_Bhale_Bullodu — State

Last reviewed commit: 651c2c56 (Move Improve_Recoemmendation_Engine.md into Docs/)
Last reviewed at: 2026-08-07T21:55:00+05:30
Last closed-trade count seen (by module): **none yet — 0 real closed, 0 real
  open, 0 real failure memories**, verified this run against BOTH the local
  `backend/data/learning_store.json` (only the 4 `trd_seed_*` fixtures) AND
  live prod (`GET /learning/dashboard` → `closed_trade_count: 0`,
  `GET /paper-sim/positions` → `[]`, `GET /paper-sim/account` → equity still
  exactly ₹10,00,000 starting capital, `GET /decisions` → `[]`).
  Root cause is now sharper than "coverage abort": **no recommendation cycle
  runs at all unless someone loads the dashboard during market hours** — there
  is no scheduler in the backend (grep-verified; only WS reconnect and the
  paper_sim γ–θ re-hedge loop exist), generation happens only inside
  `GET /recommendations` on a cold cache. The post-P0 recommend → approve →
  paper_sim loop has therefore never been exercised intraday, and the pending
  `_spot_ltp`-fix coverage re-check (09:15–15:30 IST) remains unrun for the
  same reason. New backlog item added 2026-08-07 (unattended operation /
  scheduler gap, plus: `/decisions` has no durable record of un-acted-on
  packets — they expire with the 90s cache).
Last test result seen: 317 passed / 0 failed (pytest -q, full suite, this run;
  unchanged from previous review — the 3 commits since b065e52 touched only
  docs, a frontend display card, and Guruji state files, no backend code.)

## CI status (as of previous review b065e52 — no backend/frontend code changed since)

- Backend CI `31143370053` — ruff clean, 317 passed. Advisory Mypy step only.
- Frontend CI `31143370059` — `tsc --noEmit` clean, build ✓ 7/7 pages.
- `workflow_dispatch` enabled on both workflows.

## Deployed (verified live this run, 2026-08-07 ~21:45 IST)

- Railway production up: `/api/v1/learning/dashboard`, `/api/v1/decisions`,
  `/api/v1/paper-sim/positions|account` all respond. Account `updated_at`
  2026-08-07T03:21Z (process boot) — untouched all day.
- Vercel Production at `b065e52`+; commits `381d956`/`651c2c5` add the
  supervision-mode display + docs move (not re-verified live this run — no
  behavioral backend change involved).
