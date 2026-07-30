# Deploy backend to Railway (paper / Phase 0)

**GitHub repo:** [KarthikBattaram19/Trading_Bot_1](https://github.com/KarthikBattaram19/Trading_Bot_1)  
**Railway project:** [Trading Bot project](https://railway.com/project/69b6e84b-a5e7-41c4-8206-e44bace54e40?environmentId=c8d802bb-ce4f-4098-b041-ec332b0442f6)

This monorepo deploys **only the FastAPI backend** on Railway. The Next.js app goes to **Vercel** later (`frontend/`).

---

## 1. Connect GitHub (one-time)

1. Open the [Railway project](https://railway.com/project/69b6e84b-a5e7-41c4-8206-e44bace54e40?environmentId=c8d802bb-ce4f-4098-b041-ec332b0442f6).
2. **+ New** → **GitHub Repo** → authorize Railway if prompted.
3. Choose **`KarthikBattaram19/Trading_Bot_1`**, branch **`main`**.
4. Name the service e.g. `trading-bot-api` (any name is fine).

If a service already exists from a failed build, open it → **Settings** → **Source** → connect **`Trading_Bot_1`** / **`main`**.

---

## 2. Service settings (fixes “Railpack could not determine how to build”)

Use **one** of these layouts ([Railway monorepo guide](https://docs.railway.com/guides/monorepo)):

### Option A — Repo root (simplest; matches current `main`)

| Setting | Value |
| -------- | ----- |
| **Root Directory** | *(empty)* |
| **Config-as-code path** | `/railway.toml` (default if file is at repo root) |
| **Custom start command** | *(leave empty — `railway.toml` sets `bash start.sh`)* |
| **Builder** | Railpack (default) |

Railpack detects Python via root `requirements.txt` and starts via `start.sh` → `backend/scripts/start_remote.sh`.

### Option B — Backend-only root (recommended long-term)

| Setting | Value |
| -------- | ----- |
| **Root Directory** | `backend` |
| **Config-as-code path** | `/backend/railway.toml` (**required** — config path does not follow Root Directory) |
| **Custom start command** | *(empty — uses `bash start.sh`)* |

### Troubleshooting: `No such file ... /app/backend/requirements.txt`

This happens when **Root Directory** is `backend` but **Config-as-code** still points at `/railway.toml` (repo root). Railpack then installs from the root `requirements.txt` shim that referenced `backend/requirements.txt`, which does not exist inside a backend-only build context.

**Fix (pick one):**

1. Set **Config-as-code path** to `/backend/railway.toml` (recommended with Option B), **or**
2. Pull latest `main` — root `requirements.txt` now lists dependencies inline so this pip step succeeds even if the config path is wrong.

---

## 3. Environment variables

In the service → **Variables**, set at least (see `infra/env/railway.paper.env.example`):

```env
EXECUTION_MODE=shadow
SUPERVISION_MODE=supervised
DEFAULT_BROKER=icici_direct
USE_ICICI_DIRECT_SHADOW=true
ALLOW_LIVE_PLACE_ORDER=false
PROCESS_ROLE=all
RAILPACK_PYTHON_VERSION=3.12
```

**ICICI Direct (server-side only):**

```env
ICICI_DIRECT_API_KEY=...
ICICI_DIRECT_API_SECRET=...
ICICI_DIRECT_SESSION_TOKEN=...
```

Optional until Phase 1+: `DATABASE_URL`, `REDIS_URL` from Railway Postgres/Redis plugins.  
After Vercel: `CORS_ORIGINS=https://your-app.vercel.app`

**Never** set `EXECUTION_MODE=live` on Railway.

---

## 4. Deploy and verify

1. **Deploy** → **Redeploy** (or push to `main` for auto-deploy).
2. **Settings** → **Networking** → **Generate domain**.
3. Smoke checks:
   - `GET https://<your-service>.up.railway.app/health` → `status: ok`, `phase: "0"`, `place_order_enabled: false`
   - `GET .../api/v1/paper-sim/health`
   - `POST .../api/v1/config/integrations/broker/test` (with ICICI secrets)

---

## 5. CLI deploy (optional)

From repo root, after [Railway CLI login](https://docs.railway.com/guides/cli):

```powershell
.\scripts\deploy\railway-connect.ps1
npx @railway/cli up --detach
```

Or set a **project token** in Railway → Project → Settings → Tokens, then:

```powershell
$env:RAILWAY_TOKEN = "<project-token>"
npx @railway/cli link -p 69b6e84b-a5e7-41c4-8206-e44bace54e40 -e production
npx @railway/cli up --detach
```

---

## 6. Watch paths (optional)

So frontend-only commits do not rebuild the API:

- Root deploy: `backend/**`, `requirements.txt`, `start.sh`, `railway.toml`
- Root Directory `backend`: `**` under that folder (already in `backend/railway.toml`)
