# Trading Bot 1 — Volatility Trading (Phase 0)

Paper-first volatility bot: ICICI Direct Breeze marks (data-only), in-house `paper_sim`, Next.js dashboard.

## Quick start (local)

```powershell
copy .env.example .env
# Edit .env — ICICI_DIRECT_* (never commit .env)

python -m pip install -r backend\requirements-dev.txt
cd frontend && npm ci && cd ..

.\scripts\dev\check-env.ps1
.\scripts\dev\start-backend.ps1   # terminal 1
.\scripts\dev\start-frontend.ps1  # terminal 2
```

- API: http://127.0.0.1:8000/health
- Docs: `Docs/implementation_plan.md`, `Docs/LOCAL_DEV.md`, `Docs/architecture.md`

## Commit & Push Policy

- Always commit AND push after a task is verified green; never leave work only staged.
- Before committing, run `git status` and report any pre-existing unrelated working-tree changes. Never sweep unrelated files into a commit.
- When the user asks for N separate commits, stage explicitly per commit with `git add <paths>` and verify with `git diff --cached --name-only` before each commit.
- Include doc changes (`*.md`) in the same commit as the code they describe unless told otherwise.

## Subagent & Worktree Rules

- Before dispatching a subagent to a worktree, `git fetch origin && git rebase origin/main` so the branch is not behind main.
- Ensure any uncommitted approved artifacts from the current session are committed before creating the worktree from origin.
- Subagents must commit only inside their assigned worktree, never directly onto main.
- Never nest worktrees inside another worktree.

## Testing

```powershell
python -m pytest                       # backend/ tests; asyncio_mode=auto
python -m pytest -m "not integration"  # default CI selection — skips live/broker checks
```

- Run the full suite with `python -m pytest` (NOT bare `pytest` — it is not on the Git Bash PATH on this machine).
- Report the exact passing test count from real terminal output. Never restate a count reported by a subagent without re-running the suite yourself.
- All tests must pass before any commit, merge, or push.

## Shell Environment

- Both PowerShell and Git Bash are available on this machine. `pytest` is not on the Git Bash PATH — always use `python -m pytest`.
- Do NOT use PowerShell here-strings (`@"..."@`) for commit messages — they leak stray `@` characters into the message.
- Write multi-line commit messages with `git commit -F -` and a heredoc, or repeated `-m` flags.

## Architecture

- `backend/` — FastAPI app (`main.py`), `routers/`, `services/`, `paper_sim/` (fill engine), `quant/` (signals), `execution/`, `integrations/` (Breeze), `models/`, `schemas/`, `analytics/`, `knowledge/`, `llm/`
- `frontend/` — Next.js dashboard (`src/`), deployed to Vercel
- `infra/` — cloud inventory / provisioning (GCP)
- `Docs/` — architecture, implementation plan, deploy guides (source `.md` at repo root, exported to `Docs/*.pdf`)

## Deploy

- Backend → Railway, see `Docs/RAILWAY_DEPLOY.md` (use Option A: empty Root Directory)
- Frontend → Vercel (`frontend/`)

## Docs → PDF

```powershell
python scripts/md_to_pdf.py architecture.md implementation_plan.md -o Docs
```
Re-run after editing `architecture.md` or `implementation_plan.md`. Mermaid blocks render as text placeholders in PDF only.

## ICICI Direct Breeze API — vendor constraints

Authoritative source: [Breeze API Reference](https://api.icicidirect.com/breezeapi/documents/index.html). Don't invent request shapes — use vendor docs. Project mapping: `Docs/architecture.md` §8.9 / §11.8–11.15.

- **Do not implement GTT** (Good Till Triggered orders) — out of scope for this project.
- Order APIs only from a **registered static IP**; static IP change ≤ once/week.
- Unregistered algo: **single API key** for order routing.
- ≤ **10 combined order ops/sec** (place/modify/cancel/square-off).
- **No market orders** — limit only.
- No Margin / Option Plus place-modify-cancel via Breeze.
- Rate envelope: ~100 calls/min, ~5000/day (non-order APIs count too).
- NSE equity/futures/options only — treat BSE/MCX as unavailable unless docs change.
- Resolve `session_token` via `customerdetails` before signed calls (`X-Checksum` = `token ` + SHA256(`timestamp`+payload+`secret_key`)).

## Cloud / GCP

- Primary region is **`asia-south1` (Mumbai)** — for Indian markets (NSE/BSE/NFO), ICICI Direct/Breeze, IST. Never use `us-west1` or other US regions for this project's cloud inventory.
- When provisioning infra, create/update `infra/cloud-inventory.yaml` with all services co-located in `asia-south1` (Cloud Run, Artifact Registry, Cloud SQL, Memorystore, Filestore, VPC connector). Keep `Docs/architecture.md` §17.8 and `Docs/context.md` aligned.

## Recommendation engine review

The `recommendation-engine-analyst` agent (`.claude/agents/`) owns depth on the
signal → strategy → gating → `paper_sim` fill → learning path: metrics, P&L,
and whether past recommendations actually helped. It runs on demand (a daily
16:00 IST routine is planned but not yet created), is read-only with respect to
trading code, and keeps its state in
`Docs/bot_health/{RECOMMENDATION_ENGINE_REVIEW.md,DAILY_JOURNAL.md,recommendation_metrics.jsonl,recommendation_ledger.jsonl,dashboard.html}`.

Use it for "how is the engine performing / why isn't it trading well". Use
`Guruji_for_Bhale_Bullodu` for repo-wide health (P0–P2 backlog, CI, safety
invariants). They are complements — don't run one expecting the other's output.

## Priority backlog — must-fix before claiming performance

Full source of truth: `.cursor/rules/must-fix-before-claiming-performance.mdc`, checked each run by the `Guruji_for_Bhale_Bullodu` skill (`.claude/skills/Guruji_for_Bhale_Bullodu/`) against `Docs/bot_health/BACKLOG.md`.

Do not treat P&L targets, Sharpe goals, or "edge proven" language as met until P0–P1 are real in code with evidence:

- **P0**: wire recommend → supervised approve → `paper_sim` → learning as one real ledger (no fills outside `paper_sim`); enforce breakers/market-hours durably (survives restart, not dashboard-only).
- **P1**: walk-forward/replay OOS evidence for SH-4 expectancy before "top performing" claims; skew/term/India VIX regime filters + IV quality checks.
- **P2**: delta/vega-based position sizing with real costs; fill/reconcile FSM before live micro-capital (Phase 5).

When asked to improve this project or "make it better," prefer closing P0 over net-new strategy/UI features, and never imply the vol edge is validated without OOS evidence.

## Scope Discipline

- When asked to remove a feature, first enumerate EVERY touchpoint (backend, frontend UI, API routes, config, tests, docs) and confirm the list with the user before editing anything.
- When the user asks for a written artifact (audit/report markdown file), produce the file first with your best analysis, then ask follow-up questions — do not stop and ask instead of writing.
- Never record temporary test scaffolding or relaxed thresholds as settled decisions in state/backlog docs; label them TEMPORARY with a removal owner.
