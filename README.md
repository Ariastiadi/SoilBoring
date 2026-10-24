## Soil Boring Ops – Geotechnical Field Log

Comprehensive borehole logging with AI-assisted narratives and dashboards. The steps below guide everyone from first-time users to experienced engineers.

- **Backend:** Python + FastAPI (Uvicorn)
- **Frontend:** React + Vite (TypeScript)
- **Data:** a plain `data/reports.csv` file. It is created on the first saved log; `scripts/seed_demo_data.py` can fill it with 123 synthetic 2024 borehole logs for a demo.

![Login flow](docs/assets/login.gif)

---

### Quick Start (fast path)

```bash
# 1) one-time: create the first admin (prompts for a password)
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
python -m backend.app.manage create-user you@example.com --role admin

# 2) optional: demo data
python scripts/seed_demo_data.py

# 3) run backend + frontend together
./dev.sh          # macOS/Linux
# or
pwsh ./dev.ps1    # Windows PowerShell
```

Open `http://localhost:5173` and sign in with the account you just created.

---

### Prerequisites

- Python 3.10+
- Node.js 18+
- (Optional) An Ollama server for AI narratives. AI is **off until `OLLAMA_URL` is set**; without it the AI endpoints answer with a friendly "AI service unavailable" message and everything else keeps working.

---

### Install & Run (step-by-step)

#### 1) Backend

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

Environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATA_DIR` | `data/` | Where `reports.csv` and `users.json` live. |
| `AUTH_TOKEN_SECRET` | auto-generated | Signing secret for login tokens (min. 16 chars). If unset, a random secret is generated once and stored in `DATA_DIR/.token_secret`. **Set it explicitly in production.** Known weak values such as `change-me-please` are refused. |
| `AUTH_TOKEN_TTL` | `28800` | Token lifetime in seconds (8 h). |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | – | If both are set and no users exist yet, the first admin is created at startup. |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Comma-separated browser origins allowed to call the API cross-origin (`*` is not accepted). Not needed when UI and API share one origin (Docker). |
| `OLLAMA_URL` | *(empty = AI off)* | e.g. `http://localhost:11434/api/chat`. |
| `OLLAMA_MODEL` | `gpt-oss:120b-cloud` | Model name. |
| `OLLAMA_API_KEY` | – | Bearer token for hosted/proxied Ollama endpoints. |
| `LOG_LEVEL` | `INFO` | Python log level. |

> **Run a single Uvicorn worker.** Storage is a CSV file guarded by an in-process lock, and the login throttle and AI cache are in-memory. For multiple workers or instances, move storage to a database first.

#### 2) Frontend

```bash
cd frontend
npm install
npm run dev    # http://localhost:5173
```

In development Vite proxies `/api/*` to `http://localhost:8000` (change with `VITE_BACKEND_URL`), so no `.env` is needed. Set `VITE_API_URL` only when the API lives on a different host, e.g. `VITE_API_URL=http://192.168.1.20:8000` (and add the UI origin to `CORS_ORIGINS`).

Both dev servers bind to `0.0.0.0` by default so they are reachable on your LAN. Override with `BACKEND_HOST/BACKEND_PORT` or `FRONTEND_HOST/FRONTEND_PORT` if needed.

---

### Authentication & Roles

- Every API endpoint except `/api/auth/login` and the health checks requires a signed-in user.
- Users live in `data/users.json` (never committed to git). Manage them in the **Users** tab (admins) or with the CLI:

  ```bash
  python -m backend.app.manage create-user someone@example.com --role general
  python -m backend.app.manage list-users
  ```

- Passwords are stored as salted PBKDF2-HMAC-SHA256 (600k iterations). Entries from older versions (`sha256$...` or plain text in a hand-edited file) still work and are upgraded automatically on the next successful login.
- Minimum password length is 8. After 5 failed sign-ins for an email, further attempts are blocked for 15 minutes.
- **admin**: manages users and can edit/delete any log. **general**: can create logs and can edit/delete only the logs they submitted.
- An admin cannot remove their own account, and the last admin can never be removed.
- Tokens are signed with `AUTH_TOKEN_SECRET` and expire per `AUTH_TOKEN_TTL`.

---

### Data Schema

`data/reports.csv` headers:

```
BoreholeID, ProjectName, SiteName, Latitude, Longitude, GroundElevation_mRL,
StartDate, EndDate, DrillingMethod, BoreholeDiameter_mm, TargetDepth_m, FinalDepth_m,
CasingInstalled_mm, GroundwaterDepth_m, GroundwaterEncountered, SoilDescription,
USCS_Class, Avg_SPT_N60, Contractor, LoggingGeologist, Remarks, SubmittedBy
```

Rules enforced by the API:

- `BoreholeID`, `ProjectName`, `SiteName`, `StartDate`, `EndDate`, `DrillingMethod`, `FinalDepth_m` and `Contractor` are required.
- `BoreholeID` must be unique (case-insensitive); a duplicate returns `409`.
- Dates use `YYYY-MM-DD` and `StartDate` may not be after `EndDate`; numeric fields must be finite numbers; latitude/longitude must be in range.
- `SubmittedBy` is set from the signed-in user and `BoreholeID` cannot be changed after creation; clients cannot overwrite them.
- Writes are atomic (temp file + rename), so a crash can never leave a half-written CSV. A CSV with *fewer* known columns is migrated on the next write; one with *unknown* columns is rejected with `409` instead of being overwritten.

---

### Features at a Glance

- **Borehole Log:** Form-driven capture of project/site, drilling parameters, groundwater, USCS, and SPT stats.
- **Borehole Data:** Filter/search/sort logs, export CSV (spreadsheet-formula safe), and edit/delete rows with confirmations.
- **Dashboard:** KPIs, method and USCS breakdowns, and recent activity with an executive AI brief (cached for 10 minutes; failures are never cached).
- **Summaries:** Weekly (date range) and monthly (month/year) rollups with stats, highlights, and markdown AI narratives.
- **Geo AI:** Q&A backed by the borehole CSV with evidence display. The model only sees the most relevant rows and is told to answer from them.
- **About:** Primer derived from `archive/template/soilboring.md`.

---

### Project Structure

```
backend/
  app/
    auth.py            # users, password hashing, tokens, login throttle
    analytics.py       # dashboard/summary stats, AI context, narrative cache
    models.py          # request validation
    ollama_client.py
    storage.py         # locked, atomic CSV storage
    manage.py          # admin CLI
    routers/           # auth, users, reports, ai, summaries, dashboard
  tests/               # pytest suite
frontend/
  src/                 # React app (api.ts, App.tsx, Login.tsx, tabs/)
scripts/
  seed_demo_data.py    # synthetic demo logs
archive/               # original templates and spec (not used at runtime)
data/                  # runtime data; contents are git-ignored
```

---

### Tests & CI

```bash
pip install -r backend/requirements.txt -r backend/requirements-dev.txt
python -m pytest backend/tests -q
cd frontend && npm ci && npx tsc -b && npm run build
```

GitHub Actions (`.github/workflows/ci.yml`) runs both on every push to `main` and on pull requests.

---

### Docker (single VM)

Build and run the full stack behind one port (frontend at `/`, backend at `/api`):

```bash
cp .env.example .env
# edit .env: set AUTH_TOKEN_SECRET (required) and, for a fresh install, ADMIN_EMAIL / ADMIN_PASSWORD
docker compose build
docker compose up -d
```

`docker compose` refuses to start without `AUTH_TOKEN_SECRET`. Generate one with `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`. Remove `ADMIN_PASSWORD` from `.env` after the first start.

Other settings: `AUTH_TOKEN_TTL`, `HTTP_PORT` (default 80), `OLLAMA_URL`, `OLLAMA_MODEL`, `OLLAMA_API_KEY`, and the `VITE_API_URL` build-arg (leave empty for same-origin).

Notes:

- Data persistence: `./data` on the host is bind-mounted at `/app/data`. The backend runs as an unprivileged user; on start the container fixes the ownership of `./data` for it.
- Ollama on the host: the default `OLLAMA_URL` is `http://host.docker.internal:11434/api/chat` (works on Linux too thanks to `extra_hosts`). For a containerized Ollama, add an `ollama` service and point `OLLAMA_URL` at `http://ollama:11434/api/chat`, with a volume for the models.
- The nginx proxy allows AI requests up to 180 s. Both services have health checks (`/api/health`).
- Terminate TLS in front of this stack (reverse proxy or load balancer); the app itself speaks plain HTTP.

---

### Upgrading from an earlier version

1. **Back up `data/users.json` before pulling.** It is no longer tracked by git, so `git pull` removes the old tracked copy from your working tree. The previous file also lived in the public history of this repository: consider every password in it exposed and change them (Users tab, or delete the account and recreate it).
2. Set `AUTH_TOKEN_SECRET` (Docker requires it). Everyone has to sign in again once.
3. The AI, dashboard and summary endpoints now require sign-in; any script calling them needs a bearer token from `/api/auth/login`.
4. `OLLAMA_URL` no longer has a localhost default; set it to turn AI on.
5. Docker: the `./data` folder is re-owned by the container's app user on first start.

---

### Tips for New Users

- Ensure the backend (`http://localhost:8000`) and frontend (`http://localhost:5173`) are both running.
- If you see auth errors, verify your account exists (`python -m backend.app.manage list-users`).
- To reset logs, delete `data/reports.csv`; it is recreated on the next save.

### Tips for Power Users

- Point `VITE_API_URL` at a remote backend to use the UI against a shared server (and set `CORS_ORIGINS` there).
- Set `DATA_DIR` to an external volume to keep field logs on shared storage.
- Put the app behind HTTPS and keep `AUTH_TOKEN_SECRET` out of version control.
- Override `OLLAMA_MODEL`/`OLLAMA_URL` to plug in your own model or hosted AI endpoint.
