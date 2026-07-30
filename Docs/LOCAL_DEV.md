# Local development — native toolchain (Windows)

> **Policy:** Developers do **not** install Docker Desktop, Podman, or any local container runtime.  
> **Authority:** `architecture.md` §18.2 · Phase 0 item 0.1 in `implementation_plan.md`  
> **Remote builds:** Railway **Nixpacks** (paper) · GCP **Cloud Buildpacks** (live) — no Dockerfiles in this repo

---

## 1. Why no local containers

| Need | Where it runs | Local containers? |
| ---- | ------------- | ----------------- |
| Phase 0–1 API + paper_sim + ICICI Direct marks | Your PC: Python + Node | **No** |
| Postgres / Redis for paper soak | **Railway** plugins | **No** |
| Live DB / cache | **GCP** Cloud SQL + Memorystore (`asia-south1`) | **No** |
| Paper deploy image | **Railway Nixpacks** (remote) | **No** |
| Live Cloud Run image | **Google Cloud Buildpacks** via Cloud Build (remote) | **No** |

---

## 2. Prerequisites

| Tool | Version | Purpose |
| ---- | ------- | ------- |
| Python | 3.11+ | FastAPI backend |
| Node.js | 20+ | Next.js frontend |
| Git | any | Source control |

**Optional later** (`LOCAL_INFRA=native`): PostgreSQL 16 and Redis 7 installed via Windows installer / winget. Not required for Phase 0.

---

## 3. One-time setup

```powershell
cd C:\Project_Volatality_Trading_by_Cursor
copy .env.example .env
# Edit .env: set ICICI_DIRECT_* secrets (server-side only)

python -m pip install -r backend\requirements-dev.txt
cd frontend
npm ci
cd ..

.\scripts\dev\check-env.ps1
```

`LOCAL_INFRA=none` (default) leaves `DATABASE_URL` and `REDIS_URL` empty. Phase 0 uses the in-process `paper_sim` ledger and does not need local Postgres/Redis.

For Track B RAG, embedded Chroma uses `CHROMA_PERSIST_DIRECTORY` (default `./backend/data/chroma`) — no Chroma HTTP process required.

---

## 4. Daily start

**Terminal 1 — backend**

```powershell
.\scripts\dev\start-backend.ps1
```

**Terminal 2 — frontend**

```powershell
.\scripts\dev\start-frontend.ps1
```

Smoke:

| Check | URL / action |
| ----- | ------------ |
| API health | http://127.0.0.1:8000/health |
| Paper-sim | http://127.0.0.1:8000/api/v1/paper-sim/health |
| Feed status | http://127.0.0.1:8000/api/v1/feeds/status |
| Broker test | `POST /api/v1/config/integrations/broker/test` |
| UI | http://127.0.0.1:3000 (set `NEXT_PUBLIC_USE_MOCK_DATA=false` in `frontend/.env.local` to hit the API) |

`/health` reports `local_containers_required: false` and `remote_builder: "nixpacks"`.

---

## 5. Optional native Postgres / Redis

Only when you want local persistence beyond the in-memory paper ledger:

1. Install PostgreSQL 16 and Redis for Windows (winget or vendor installers).
2. Create DB/user matching `.env.example` comments.
3. Set in `.env`:

```env
LOCAL_INFRA=native
DATABASE_URL=postgresql+psycopg://volatality:volatality_dev@localhost:5432/volatality
REDIS_URL=redis://localhost:6379/0
```

Do **not** introduce Docker Compose, Podman Compose, or any local container stack for this.

---

## 6. Paper / live hosting

| Stage | Frontend | Backend | Data | Image build |
| ----- | -------- | ------- | ---- | ----------- |
| Paper | Vercel | Railway | Railway Postgres + Redis | **Nixpacks** (`backend/nixpacks.toml`, `Procfile`) |
| Live | Cloud Run | Cloud Run | Cloud SQL + Memorystore | **Cloud Buildpacks** (`backend/cloudbuild.yaml`) |

Env templates: `infra/env/railway.paper.env.example`, `infra/env/vercel.paper.env.example`.

---

## 7. CI note

GitHub Actions may start Postgres/Redis **service containers on the hosted runner** for integration tests. That is CI infrastructure only — not a developer toolchain and not a project Dockerfile. Local developers never run container commands.
