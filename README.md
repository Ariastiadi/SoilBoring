## Soil Boring Ops – Geotechnical Field Log

Borehole logging for geotechnical field work: logs, strata, SPT, samples, core runs and photos, a printable bore log, AGS4 export, offline use in the field and an AI assistant that runs in the browser. Around the field log it runs the whole job of a soil investigation company: clients, projects, quotations, contracts, CPT (sondir), geophysics/geology/survey work, laboratory tests, engineering analyses, the report with recommendations for the client, and invoices. The steps below guide everyone from first-time users to experienced engineers.

- **Backend:** Python + FastAPI (Uvicorn)
- **Frontend:** React + Vite (TypeScript), Bahasa Indonesia by default with an English option
- **Data:** files in `data/` (logs in `reports.csv`), or a Postgres database when `DATABASE_URL` is set. `scripts/seed_demo_data.py` can fill a fresh install with 123 synthetic 2024 borehole logs for a demo.
- **Live demo deployment:** [soilboring.vercel.app](https://soilboring.vercel.app) (sign-in required)

![Borehole list](docs/assets/en-boreholes.png)

**Borehole profile:** graphic log (column width follows grain size) next to SPT N against depth.

![Borehole profile](docs/assets/en-profile.png)

**New log:** the form in sections, with the required fields checked off beside the submit button.

![New log form](docs/assets/en-new-log.png)

**On a phone:** bottom navigation; each borehole becomes a compact entry.

<img src="docs/assets/en-phone.png" alt="Borehole list on a phone" width="320">

**Project hub:** one project from tender to final report, with its boreholes, CPT, lab tests, analyses, report, quotation, contract and invoices.

![Project hub](docs/assets/en-project-hub.png)

**Pile capacity from SPT:** allowable capacity for each pile length, from the borehole's strata and SPT.

![Pile capacity analysis](docs/assets/en-analysis-pile.png)

**Invoice (print / PDF):** VAT, PPh 23 withheld by the client, amount in words and the bank account.

![Invoice](docs/assets/en-invoice-print.png)

---

### Quick Start (fast path)

```bash
# 1) one-time: create the first admin (prompts for a password)
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
python -m backend.app.manage create-user you@example.com --role admin

# 2) optional: demo data
python scripts/seed_demo_data.py

# 3) run backend + frontend together (installs the frontend packages on the first run)
./dev.sh          # macOS/Linux
# or
pwsh ./dev.ps1    # Windows PowerShell
```

Open `http://localhost:5173` and sign in with the account you just created.

---

### Prerequisites

- Python 3.10+
- Node.js 20.19+ (22 LTS recommended)
- Nothing extra for AI: without a server AI, **Geo AI runs Qwen in the browser** (see below). Optionally an Ollama server (`OLLAMA_URL`) for server-side answers and automatic narratives.

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
| `DATA_DIR` | `data/` | Where `reports.csv` and `users.json` live (file mode). |
| `DATABASE_URL` | – | Postgres connection string (e.g. a free Neon database). When set, the logs, users and token secret are stored in the table `soilboring_documents` instead of files. Needed on hosts without a persistent disk, such as Render's free plan. |
| `AUTH_TOKEN_SECRET` | auto-generated | Signing secret for login tokens (min. 16 chars). If unset, a random secret is generated once and stored in `DATA_DIR/.token_secret`. **Set it explicitly in production.** Known weak values such as `change-me-please` are refused. |
| `AUTH_TOKEN_TTL` | `28800` | Token lifetime in seconds (8 h). |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | – | If both are set and no users exist yet, the first admin is created at startup. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_SSL` | – | Optional mail server for password-reset emails (see *Account security*). |
| `APP_BASE_URL` | Vercel production URL | Site address used in emailed links; never taken from the request. |
| `ALLOW_FIRST_RUN_SETUP` | `true` | While no account exists, the sign-in page offers to create the first admin (limited to `ADMIN_EMAIL` when that is set). Set `false` to turn this off. |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Comma-separated browser origins allowed to call the API cross-origin (`*` is not accepted). Not needed when UI and API share one origin (Docker). |
| `OLLAMA_URL` | *(empty = server AI off)* | e.g. `http://localhost:11434/api/chat`, or `https://ollama.com/api/chat` with `OLLAMA_API_KEY` and a cloud model such as `gpt-oss:120b`. Without it, Geo AI runs Qwen in the browser. |
| `OLLAMA_MODEL` | `gpt-oss:120b-cloud` | Model name. |
| `OLLAMA_API_KEY` | – | Bearer token for hosted/proxied Ollama endpoints. |
| `ORG_NAME` | – | Organisation name shown in the title bar and login page and used in AGS4 exports (e.g. `PT Geoteknik Nusantara`). |
| `APP_TIMEZONE` | `Asia/Jakarta` | Time zone for "today", report timestamps and the last-7/30-days views. |
| `LOG_LEVEL` | `INFO` | Python log level. |

> **File mode: run a single Uvicorn worker.** Files are guarded by locks inside one process. With `DATABASE_URL` the data, the sign-in lockout and the locks live in Postgres, so several workers or serverless instances are fine (only the AI narrative cache stays per process).

#### 2) Frontend

```bash
cd frontend
npm install
npm run dev    # http://localhost:5173
```

In development Vite proxies `/api/*` to `http://localhost:8000` (change with `VITE_BACKEND_URL`; `dev.sh`/`dev.ps1` set it from `BACKEND_PORT`), so no `.env` is needed. Set `VITE_API_URL` only when the API lives on a different host, e.g. `VITE_API_URL=http://192.168.1.20:8000` (and add the UI origin to `CORS_ORIGINS`).

Both dev servers bind to `0.0.0.0` by default so they are reachable on your LAN. Override with `BACKEND_HOST/BACKEND_PORT` or `FRONTEND_HOST/FRONTEND_PORT` if needed.

---

### Authentication & Roles

- Every API endpoint except `/api/auth/login`, `/api/auth/setup` (first admin only), `/api/config` and the health checks requires a signed-in user.
- **First admin:** on a fresh install with no accounts, the sign-in page shows **Create admin account**; the first account created there is an admin and the form disappears afterwards. Alternatives: `ADMIN_EMAIL`/`ADMIN_PASSWORD` at startup, or the CLI below.
- Users live in `data/users.json` (never committed to git). Manage them in the **Users** tab (admins) or with the CLI:

  ```bash
  python -m backend.app.manage create-user someone@example.com --role general
  python -m backend.app.manage list-users
  ```

- Passwords are stored as salted PBKDF2-HMAC-SHA256 (600k iterations). Entries from older versions (`sha256$...` or plain text in a hand-edited file) still work and are upgraded automatically on the next successful login.
- Minimum password length is 8. After 5 failed sign-ins for an email, further attempts are blocked for 15 minutes.
- Everyone can change their own password under **Account & security** (bottom of the side menu; on phones under *More*). Admins can set a new password for another user with **Reset Password** in the Users tab.
- Roles:
  - **admin**: everything, including users, company settings and the activity log.
  - **manager** (project leader / commercial): projects, clients, quotations, contracts, reports, analyses; can edit any log.
  - **general** (field): creates logs, CPT and other field work and edits only their own; sees projects without the contract value.
  - **lab**: laboratory tests and their results.
  - **finance**: invoices and payments, price list, quotations and contracts.
- An admin cannot remove their own account, and the last admin can never be removed.
- Tokens are signed with `AUTH_TOKEN_SECRET` and expire per `AUTH_TOKEN_TTL`. Changing or resetting a password, or removing the account, ends every other session of that user.
- In a hand-edited `users.json`, each entry needs a `"role"` of `admin`, `manager`, `general`, `lab` or `finance`. A missing or unknown role is treated as `general` (a warning is logged), never as admin.
- Emails only need the form `name@domain`, so intranet addresses such as `ops@site.local` work.

---

### Data Schema

`data/reports.csv` headers:

```
BoreholeID, ProjectName, SiteName, Latitude, Longitude, GroundElevation_mRL,
StartDate, EndDate, DrillingMethod, DrillRig, CoreSize, BoreholeDiameter_mm, TargetDepth_m, FinalDepth_m,
CasingInstalled_mm, GroundwaterDepth_m, GroundwaterEncountered, SoilDescription,
USCS_Class, Avg_SPT_N60, Contractor, LoggingGeologist, Remarks, SubmittedBy
```

Rules enforced by the API:

- `BoreholeID`, `ProjectName`, `SiteName`, `StartDate`, `EndDate`, `DrillingMethod`, `FinalDepth_m` and `Contractor` are required.
- `CoreSize` is empty or a wireline size `AQ`, `BQ`, `NQ`, `HQ`, `PQ`. Choosing one in the form fills the nominal hole diameter (48, 60, 75.7, 96, 122.6 mm). Logs saved by older versions simply have these two columns empty.
- `BoreholeID` must be unique (case-insensitive); a duplicate returns `409`. It may not contain `/ \ ? # %` or control characters.
- Dates use `YYYY-MM-DD` and `StartDate` may not be after `EndDate`; numeric fields must be finite numbers; latitude/longitude must be in range.
- `SubmittedBy` is set from the signed-in user and `BoreholeID` cannot be changed after creation; clients cannot overwrite them.
- A `reports.csv` saved by Excel as "CSV UTF-8" (with a byte-order mark) is read normally.
- Writes are atomic (temp file + rename), so a crash can never leave a half-written CSV. A CSV with *fewer* known columns is migrated on the next write; one with *unknown* columns is rejected with `409` instead of being overwritten.

---

### Features at a Glance

The side menu (bottom bar on phones, the rest under *More*) is grouped the way a soil investigation job runs. Each role sees only its own groups.

- **Commercial operations**
  - **Projects:** status from tender → contract → ongoing → reporting → completed, project leader, services and contract value. A project's page (the hub) gathers its boreholes (logs whose *Project* is the project name), CPT, field worksheets, lab tests, analyses, reports, quotations, contracts and invoices, each with an *Add* button that fills in the project.
  - **Clients:** contractors, state-owned companies (BUMN), private owners and government agencies, each with a price tier (client or internal/group price).
  - **Quotations:** items picked from the price list (client or internal price) or pasted from Excel; discount, VAT 11% and total calculated; numbered QUO-YYYY-NNN; mobilisation/demobilisation priced or stated as excluded; a price check flags items below the internal price and refuses items below a minimum selling price; printable with the company letterhead, the exclusions and the amount in words.
  - **Contracts:** contract number, value (incl. VAT), dates, signatories, payment terms in % and the signed documents. Each term shows its invoice, or a *Create invoice* button.
- **Field work**
  - **Boreholes** (start page) and **New log** — see below.
  - **CPT / sondir:** mechanical sondir (kg/cm²) or electric CPT/CPTu (MPa, kPa) — readings pasted from Excel or read from the data logger's CSV file. Interpretation: corrected cone resistance qt, friction ratio, pore pressure ratio Bq, soil behaviour type index Ic and zone (Robertson 2009), su for clays, φ' for sands, and the dissipation test (t50, ch after Teh & Houlsby).
  - **Field worksheets:** one form per kind of work, with the company's document numbers, calculation, charts, an *Example* fill, the standards it follows, a field QC status (waiting / passed / redo) and an A4 print: daily report and daily HSE report, field work instruction, coordinate table; GPS point description and logsheet, topographic points, traverse (Bowditch adjustment, closure 1:X), levelling (rise & fall, misclosure); pocket penetrometer, SPT correction (N60, (N1)60), field vane shear, permeability (falling, rising and constant head; Lugeon packer test), test pit, field CBR, plate load test; resistivity 1D and 2D (geometric factor, apparent resistivity, pseudo-section), downhole and crosshole seismic (interval velocities, Gmax, Vs30), thermal resistivity (needle probe).
  - **Coordinates & maps:** latitude/longitude ⇄ UTM (WGS84) for a pasted table, and Google Earth (KML) files of the points or of a whole project (boreholes, CPT and field points).
- **Laboratory**
  - **Laboratory tests:** raw data per test with the calculation, chart and standard of each: water content & density, specific gravity, grain size with hydrometer, Atterberg limits, Proctor compaction, CBR, unconfined compression, UU and CU triaxial (Mohr circles), direct shear, consolidation (e–log p, Cc, Cr, σ'p, cv), swelling, Los Angeles abrasion, sulfate soundness and slake durability. Results feed the engineering analyses.
  - **Sample register:** every sample taken in the boreholes, with the tests requested or done on it. Tick samples and tests to send a laboratory instruction (the tests appear as *requested*), and print sample labels with a QR code; the lab form reads the label code.
  - **Results summary:** all finished results per sample in one table, exported to CSV or printed for the report.
- **Engineering**
  - **Engineering analyses:** shallow foundation bearing capacity (Vesic/De Beer/Hansen factors) and a bearing table over several widths and depths (with a warning below FS 3), pile capacity from SPT (Decourt) with a capacity-versus-length chart, consolidation settlement (2:1 stress spread), liquefaction (Idriss & Boulanger 2014), SPT correction, and the seismic site class and design spectrum after SNI 1726:2019 (whose PGA_M can be taken as amax in the liquefaction analysis). *Use field and lab data* fills the inputs from the borehole's strata, SPT, groundwater and lab results. All results are preliminary and say so.
  - **Client reports:** the soil investigation report: summary, scope, every borehole, CPT, field activity, lab result and analysis of the project, recommendations and the prepared / reviewed / approved signatures, printed as one document.
- **Finance:** **Invoices** (from a contract term or free items; VAT, PPh 23 withholding, payments, outstanding and overdue status; printable) and the **Price list** (client price, internal/group price, minimum price, standard exclusions; import from Excel; a rate build-up per item — equipment, labour, consumables, operations and overhead per hour × hours per unit, plus contingency, risk premium and margins — gives the cost per unit and the calculated internal and client prices next to the published ones).
- **Work queue:** **Approvals** — every document with an approval flow goes drafter → reviewer → approver (submit, review, approve, return with a note, reopen), with its history; records in review are locked, approved ones cannot be deleted, and one person cannot review or approve their own submission (switchable in company settings for very small teams). **Management overview** for directors: commercial pipeline, contracts, receivables and NPAR, projects against budget, guarantees, equipment, maintenance, purchasing, assets and performance.
- **Commercial ERP:** **Pricing & budgeting decisions** (project cost budget from the price list's cost per unit, mobilisation, a 16-factor project difficulty index with region zones A–N giving the risk premium, margin, bid price, minimum client price and cost/revenue ratio; an approved decision turns into a quotation), **client decisions**, **weekly work plans** (Gantt, weekly budget drawdown and realisation, S-curve, checks against the pricing decision), **bank guarantees & SKBDN** (expiry warnings), contracts of kind contract, SPK, SPMK or subcontract, **client cards** (payment record, rating) and **receivables** (aging by due date and by invoice date; invoices older than 90 days move to the NPAR committee, with collection notes). Factors, premiums, margins and limits are set in **Pricing policy**.
- **Logistics, purchasing, assets and people:** **equipment register** (live status, calibration and service due), **mobilisation & demobilisation**, **maintenance work orders** (parts, costs, downtime), **vendors**, **procurement cards** (request, quotation comparison with a minimum number of quotes, approval) and **purchase orders** (goods receipt, vendor invoice), **fixed assets** (tax depreciation after PMK 72/2023 groups 1–4 and buildings, book depreciation after PSAK 216, schedules, disposals) and **work plan & performance cards** (weighted KPIs and competencies; staff see only their own card).
- **Data & references**
  - **Geo AI:** questions in plain language, answered from the logs, with the data rows used shown as evidence.
  - **Summaries** and **Dashboard.**
  - **Worksheet list:** every worksheet by document number (01 General … 05 Laboratory), opened blank or filled with example data.
  - **Standards:** the SNI and ASTM standards per kind of work.
- **Administration** (admins): **Users**, the **Activity** log and **Company settings** (name, address, NPWP, bank account and signatory printed on quotations, invoices, worksheets and reports).
- Attachments (contracts, lab sheets, field data) are PDF, JPEG, PNG, CSV, TXT, ZIP, XLSX or DOCX up to 5 MB each and are stored with the data, so on the free Neon plan they share its 0.5 GB.
- Business API: `GET /api/schemas` (record definitions and what the signed-in role may open), `GET/POST /api/records/{entity}`, `GET/PUT/DELETE /api/records/{entity}/{id}` (send `expected_updated_at` with `PUT` to detect conflicting edits; a record still referenced elsewhere cannot be deleted), `POST /api/analyses/run`, `GET /api/worksheets` (worksheet list with standards and examples), `POST /api/worksheets/calc` (calculate without saving), `GET /api/samples`, `POST /api/tools/coordinates`, `POST /api/tools/kml`, `GET /api/export/kml?project_id=`, `POST /api/files`, `GET /api/files/{id}`. Entities: `clients`, `projects`, `rates`, `quotes`, `contracts`, `cpt`, `field_activities`, `lab_tests`, `analyses`, `project_reports`, `invoices`, `settings`.
- **About:** primer on soil boring with the Indonesian standards (SNI) used in practice.
- **Language:** Bahasa Indonesia (default) or English, switched at the bottom of the side menu. Messages from the server, calculation notes, summary texts and dates (dd/mm/yyyy) follow the chosen language.

### Depth data, profile, bore log sheet, photos and map

Open a borehole from the **Boreholes** list. Its section menu holds:

- **Profile:** the borehole to depth scale: a graphic log whose column width follows grain size (fine soils narrow, coarse soils wide), USCS labels, samples, groundwater and end of hole, next to SPT N plotted against depth (hollow points = refusal).
- **Strata:** from/to depth, USCS group, soil or rock description. Layers may not overlap; a new row starts where the previous one ended.
- **SPT:** blows for the 150 mm seating drive and the two 150 mm test increments; N is calculated. For refusal (e.g. 50 blows) enter the test penetration reached in mm (reported as `50/80mm`). Decimal commas (1,5) are accepted.
- **Samples:** depth range, AGS4 sample type (U, UT, TW, P, D, B, SPTLS, C, W) and reference.
- **Core runs:** TCR, SCR and RQD in % (SCR ≤ TCR, RQD ≤ SCR are checked).
- **Photos:** core boxes and site photos from the camera or the gallery; they are reduced to at most 1600 px (JPEG) in the browser before upload and stored with the data (max. 30 per borehole, 2 MB each).
- **History:** every change to the log, its depth data and photos, with user and time.
- **Bore log (print / PDF):** an A4 sheet per 15 m (one sheet up to 20 m) with header data, depth scale, graphic log (patterns by USCS group), descriptions, samples, SPT N graph, core TCR/RQD bars, groundwater and end of hole. Use the browser's *Save as PDF*.

Changes are saved with the bar at the bottom (*Save depth data* / *Discard changes*). If someone else saved the same borehole in the meantime, saving is refused (`409`) instead of overwriting their work. The **map** (*Show map* on the Boreholes page) places every borehole with coordinates on OpenStreetMap; click a point to open it.

A borehole's status in the list: *Drilling now* while its end date is today or later; *Depth data complete* when strata reach the final depth (within 0.5 m) and there is at least one SPT; otherwise *incomplete* or *no depth data yet*.

The depth data also goes into the AGS4 export (GEOL, ISPT, SAMP, CORE). API: `GET/PUT /api/details/{BoreholeID}` (send `expected_updated_at` to detect conflicting edits), `GET /api/depth-overview` (strata and SPT of every borehole, for the list), `POST /api/photos`, `GET/DELETE /api/photos/{id}`.

### Working offline in the field

The app is installable ("Add to home screen") and keeps its own files in the browser, so it opens without a connection. A log submitted while offline is kept on the device, tied to the user who made it, and sent with that user's sign-in when the connection is back (also retried every minute and when the app is reopened). Waiting logs appear at the top of the Boreholes list as *Waiting to be sent*; a log the server refuses (e.g. the Borehole ID already exists) stays there with the reason, to retry or discard. Viewing data, depth data and photos needs a connection.

### Account security

- **Two-step verification (TOTP):** *Account & security* → scan the QR code with any authenticator app (Google/Microsoft Authenticator, Aegis, ...). Sign-in then asks for the 6-digit code. Admins can turn it off for a user who lost their phone.
- **Recovery codes:** 10 one-time codes, created when two-step verification is turned on or at any time on the same page. Each one can replace an authenticator code, or set a new password via *Forgot password?* on the sign-in page.
- **Password reset by email:** optional. Set `SMTP_HOST`, `SMTP_PORT` (587, or 465 for SSL), `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, and `APP_BASE_URL` (on Vercel the production domain is used automatically). The link is valid for 30 minutes and works once.
- **Sign-in lockout:** 5 failed attempts per email in 15 minutes. The counter is stored with the data (file or database), so it holds across several app instances.
- **Activity log:** admins see every change (logs, depth data, photos, accounts) in the *Activity* tab; other users see the history of a borehole. The newest 5000 events are kept; passwords and codes are never logged.

### AI without an API key: Qwen on this device

Geo AI works on every deployment, also without any AI server or key: the browser runs a small open model (Qwen 2.5 1.5B or 0.5B, GGUF from Hugging Face) with llama.cpp compiled to WebAssembly ([wllama](https://github.com/ngxson/wllama)), the same approach as the browser engine of [talkdude](https://github.com/Ariastiadi/talkdude).

- Open **Geo AI**, pick a model and press **Download** once (about 1 GB for 1.5B, 400 MB for 0.5B). It stays in the browser's private storage; later visits start right away and answers work offline.
- The server only supplies the most relevant data rows (`POST /api/ai/prompt`, sized for the model's short context); the question and the answer never leave the browser. No cost, no account, no usage limit.
- Summaries and Dashboard then offer **Write summary with Qwen (this device)** instead of the server narrative.
- The engine (`wllama.wasm`) is fetched from jsDelivr and checked against the SHA-256 of the exact version in `package-lock.json`. The page is cross-origin isolated (COOP/COEP) so the model can use several CPU threads; WebGPU is used on desktops when available.
- Needs a recent Chrome, Edge or Firefox (Safari uses a slower compatibility build); not in private windows. Small models give simpler answers than large server models; when `OLLAMA_URL` is set, Geo AI offers both.

---

### AGS4 export

Choose a project in the **Project** filter of the Boreholes page and pick **Export → AGS4 for the chosen project** (or call `GET /api/export/ags?project=<name>`). The file follows AGS4 edition 4.1.1, the ground-investigation data format read by gINT, HoleBASE, OpenGround and similar tools, and passes the official AGS4 checker ([python-ags4](https://pypi.org/project/python-ags4/), used in the tests).

| App field | AGS4 |
| --- | --- |
| BoreholeID, ground level, final depth, start/end date, lat/long (as D:M:S, WGS84), site | `LOCA` |
| Drilling method | `LOCA_TYPE` / `HDPH_TYPE` (standard codes: W, RO, RC, AUGH, SCP, HA; other methods get M1, M2 … listed in `ABBR`) |
| Hole 0 m to final depth, drill rig (`HDPH_EXC`), wireline core size (`HDPH_BTYP`), logging geologist, contractor | `HDPH` |
| Borehole / casing diameter (nominal Q-series hole size when only the core size was logged) | `HDIA` / `CDIA` |
| Groundwater depth (when encountered) | `WSTG` |
| USCS class, average SPT N60, target depth, soil description, remarks | `LOCA_REM` |
| Strata (from/to, USCS, description) | `GEOL` |
| Each SPT (seating, test drive, N or refusal) | `ISPT` |
| Samples (depth, type, reference) | `SAMP` |
| Core runs (TCR, SCR, RQD) | `CORE` |

Depth groups are only written for boreholes that have depth data; nothing is invented from the log's single soil description or average N60. Text is converted to ASCII as AGS4 requires (é → e).

---

### Project Structure

```
backend/
  app/
    auth.py            # users, password hashing, tokens, login throttle, 2FA, recovery codes
    details.py         # depth data (strata, SPT, samples, core runs) and photos
    audit.py           # activity log
    mailer.py          # optional password-reset email (SMTP)
    analytics.py       # dashboard/summary stats, AI context, narrative cache
    models.py          # request validation
    ollama_client.py
    storage.py         # locked, atomic CSV storage
    manage.py          # admin CLI
    ags.py             # AGS4 export
    config.py          # ORG_NAME, APP_TIMEZONE
    docstore.py        # file or Postgres (DATABASE_URL) storage
    entities.py        # definitions of the business records (served at /api/schemas)
    records.py         # validation, totals, numbering, references, files, permissions
    engineering.py     # bearing capacity, pile capacity, settlement, liquefaction
    analysis_runner.py # runs an analysis from borehole and lab data
    calcbase.py        # shape of worksheet results (values, tables, charts, notes)
    sheets.py, sheets_field.py, sheets_lab.py  # worksheet definitions: fields, standards, examples
    calc_field.py, calc_lab.py, cpt_calc.py    # worksheet and CPT calculations
    seismic.py         # site class and design spectrum (SNI 1726:2019)
    geo.py             # UTM conversion and KML files
    routers/           # auth, users, reports, boreholes, ai, summaries, dashboard, export, records, worksheets
  tests/               # pytest suite
frontend/
  src/
    App.tsx            # side menu / bottom bar, pages
    tabs/              # Boreholes (DailyReportData), New log (DailyReportForm), Geo AI, Summaries,
                       #   Dashboard, Users, Activity, About, Business (projects ... invoices), Analyses,
                       #   Worksheets (worksheet list, standards, coordinates, sample register, lab summary)
    records.tsx        # forms, lists and views built from /api/schemas
    worksheets.tsx     # worksheet results, charts, example and calculate tools
    nav.ts             # page keys and links between pages
    BoreholeDetail.tsx # depth data, photos, history of one borehole
    Profile.tsx        # graphic log + SPT plot, mini soil columns
    BoreLog.tsx        # printable A4 bore log
    BoreholeMap.tsx    # Leaflet map
    soil.tsx           # USCS patterns, colours, grain-size widths
    ui.tsx             # page heading, dd/mm/yyyy date field, icons
    i18n.ts, i18n-id.ts# Bahasa Indonesia / English, server messages translated
    outbox.ts          # logs saved offline
    localai.ts, LocalAI.tsx  # Qwen in the browser
    api.ts, Login.tsx, Security.tsx, ChangePassword.tsx, unsaved.ts, styles.css
  public/              # sw.js (offline), manifest.webmanifest, icons
scripts/
  seed_demo_data.py    # synthetic demo logs
archive/               # original templates and spec (not used at runtime)
data/                  # runtime data; contents are git-ignored
Dockerfile             # single-service image (UI + API), used by Render
render.yaml            # Render blueprint
pyproject.toml, vercel.json  # Vercel deployment
```

---

### Tests & CI

```bash
pip install -r backend/requirements.txt -r backend/requirements-dev.txt
python -m pytest backend/tests -q
cd frontend && npm ci && npx tsc -b && npm run build
```

GitHub Actions (`.github/workflows/ci.yml`) runs on every push to `main` and on pull requests: backend tests on Python 3.10 and 3.11, the same tests against Postgres, the frontend build with `npm audit`, and a build plus smoke test of all Docker images.

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

Other settings: `AUTH_TOKEN_TTL`, `HTTP_PORT` (default 80), `OLLAMA_URL`, `OLLAMA_MODEL`, `OLLAMA_API_KEY`. The Docker UI always talks to its own origin (`/api` is proxied by nginx).

Manage users inside the stack as the app user, e.g. `docker compose exec -u app backend python -m backend.app.manage create-user you@example.com --role admin`.

Notes:

- Data persistence: `./data` on the host is bind-mounted at `/app/data`. The backend runs as an unprivileged user; on start the container fixes the ownership of `./data` for it.
- Ollama on the host: the default `OLLAMA_URL` is `http://host.docker.internal:11434/api/chat` (works on Linux too thanks to `extra_hosts`). For a containerized Ollama, add an `ollama` service and point `OLLAMA_URL` at `http://ollama:11434/api/chat`, with a volume for the models.
- The nginx proxy allows AI requests up to 180 s. Both services have health checks (backend: `/api/health`, frontend: the start page).
- Terminate TLS in front of this stack (reverse proxy or load balancer); the app itself speaks plain HTTP.

---

### Deploy on Vercel (free) with a Neon database

Vercel's Hobby plan and Neon's free Postgres need no credit card, and both accept "Sign in with GitHub". `pyproject.toml` and `vercel.json` hold the whole setup: Vercel builds the UI (`frontend/dist`) and runs the FastAPI app as one function, which serves the API and the UI from the same address.

1. **Vercel:** Add New → Project → import this repository; keep the detected settings.
2. **Database:** in the Vercel project open *Storage* → *Create* → **Neon** (free) and connect it with the prefix `DATABASE`; Vercel then sets `DATABASE_URL` itself. Or create a Neon project yourself and add its connection string as `DATABASE_URL`.
3. Optionally add `ORG_NAME`, `APP_TIMEZONE`, `ADMIN_EMAIL` under *Environment Variables*. Then deploy.
4. Open the site: as long as no account exists, the sign-in page offers **Create admin account**. Do this right after the first deploy (or set `ADMIN_EMAIL`, so only that address can be used).

Without `DATABASE_URL` the app still starts, but keeps its data in `/tmp`, which Vercel wipes regularly. The app page, `sw.js` and the manifest are served with an ETag taken from their content, so every deployment reaches the browsers (asset files are cached for a year under hashed names). `vercel.json` places the function in `cle1` (Ohio), next to Neon's AWS US East 2; pick the matching Vercel region if your database lives elsewhere. Every push to `main` redeploys.

### Deploy on Render with a Neon database

Render's web service has no persistent disk and Neon's free Postgres keeps the data. Render may ask new accounts for a credit card even for the free plan.

1. **Neon:** create a project and copy the connection string (`postgresql://...`). Keep Neon and Render in the same region (`render.yaml` uses Ohio, matching Neon's AWS US East 2); every request talks to the database, so a long distance between them makes the app slow.
2. **Render:** New → Blueprint → pick this repository. Render reads `render.yaml` and creates one Docker web service from the root `Dockerfile` (UI and API together).
3. When asked, fill in `DATABASE_URL` (the Neon string), `ADMIN_EMAIL` and `ADMIN_PASSWORD` (the first admin, created while there are no users; or leave the password empty and use **Create admin account** on the sign-in page), and optionally `ORG_NAME`. `AUTH_TOKEN_SECRET` is generated by Render.
4. After the first sign-in, remove `ADMIN_PASSWORD` from the service's environment (the account stays).

Notes: the free service sleeps after 15 minutes without visitors, and the first request then takes about a minute. Every push to `main` redeploys. To move to a VPS later (Docker Compose, Coolify, Dokploy …) keep `DATABASE_URL`, or export the logs as CSV first.

To try the database mode locally: `DATABASE_URL=postgresql://user:pass@localhost:5432/db uvicorn backend.app.main:app` (the table is created automatically).

---

### Upgrading from an earlier version

1. **Back up `data/users.json` before pulling.** It is no longer tracked by git, so `git pull` removes the old tracked copy from your working tree. The previous file also lived in the public history of this repository: consider every password in it exposed and change them (Change Password, or Reset Password in the Users tab).
2. Set `AUTH_TOKEN_SECRET` (Docker requires it). Everyone has to sign in again once.
3. The AI, dashboard and summary endpoints now require sign-in; any script calling them needs a bearer token from `/api/auth/login`.
4. `OLLAMA_URL` no longer has a localhost default; set it to turn AI on.
5. Docker: the `./data` folder is re-owned by the container's app user on first start.
6. Check that every entry in `data/users.json` has `"role": "admin"` or `"role": "general"`; an entry without a role is now a general user.

---

### Tips for New Users

- Ensure the backend (`http://localhost:8000`) and frontend (`http://localhost:5173`) are both running.
- If you see auth errors, verify your account exists (`python -m backend.app.manage list-users`).
- To reset logs, delete `data/reports.csv`; it is recreated on the next save.

### Tips for Power Users

- In development, point `VITE_API_URL` at a remote backend to use the UI against a shared server (and set `CORS_ORIGINS` there). The Docker image always uses its own origin.
- Set `DATA_DIR` to an external volume to keep field logs on shared storage.
- Put the app behind HTTPS and keep `AUTH_TOKEN_SECRET` out of version control.
- Override `OLLAMA_MODEL`/`OLLAMA_URL` to plug in your own model or hosted AI endpoint.

---

### License & Credits

Licensed under the [GNU General Public License v3.0](LICENSE).

SoilBoring was originally created by **Abu Hanifah** ([abuhanifah86/SoilBoring](https://github.com/abuhanifah86/SoilBoring)). This repository continues that work with security, data-integrity, testing and deployment improvements.
