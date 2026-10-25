import { lang, t, translateServer } from "./i18n";

// Origin of the backend. Empty = same origin (Docker/nginx and the Vite dev proxy).
// Every request path below already starts with "/api", so a trailing "/api" or "/"
// in VITE_API_URL (older docs told people to use "/api") is stripped to avoid "/api/api".
const BASE = String(import.meta.env.VITE_API_URL ?? "")
  .trim()
  .replace(/\/+$/, "")
  .replace(/\/api$/, "");

export type Role = 'admin' | 'manager' | 'general' | 'lab' | 'finance'
export type User = {
  email: string
  role: Role
  totp_enabled?: boolean
}

export type SummaryStats = {
  as_of: string
  boreholes: number
  projects: string[]
  sites: string[]
  avg_final_depth_m: number | null
  avg_groundwater_depth_m: number | null
  avg_spt_n60: number | null
  total_meterage_m: number
  method_breakdown: Record<string, number>
  uscs_breakdown: Record<string, number>
  top_contractor?: string | null
  period_range?: SummaryPeriodRange
  period_label?: string | null
}

export type SummaryPeriodRange = { from?: string | null; to?: string | null }

// Prompt for the browser's on-device AI when the server has no AI configured.
export type NarrativePrompt = { instruction: string; context: string }

export type SummaryResponse = {
  period: "weekly" | "monthly"
  text: string
  stats?: SummaryStats
  highlights?: string[]
  narrative?: string | null
  narrative_prompt?: NarrativePrompt | null
  period_range?: SummaryPeriodRange
  period_label?: string | null
}

export type DashboardRecent = {
  borehole_id?: string | null
  project?: string | null
  site?: string | null
  start_date?: string | null
  final_depth_m?: number | null
  groundwater_depth_m?: number | null
  method?: string | null
}

export type DashboardResponse = {
  total_boreholes: number
  avg_final_depth_m: number | null
  avg_groundwater_depth_m: number | null
  total_meterage_m: number
  active_projects: number
  project_list?: string[]
  method_breakdown?: Record<string, number>
  uscs_breakdown?: Record<string, number>
  top_contractor?: string | null
  recent_reports?: DashboardRecent[]
  narrative?: string | null
  narrative_prompt?: NarrativePrompt | null
  period_range?: SummaryPeriodRange
  period_label?: string | null
}

let authToken: string | null = null;
let unauthorizedHandler: (() => void) | null = null;

export function setAuthToken(token: string | null) {
  authToken = token;
}

export function getAuthToken() {
  return authToken;
}

export function setUnauthorizedHandler(handler: (() => void) | null) {
  unauthorizedHandler = handler;
}

function buildHeaders(init?: HeadersInit) {
  const headers = new Headers(init || {});
  if (authToken) {
    headers.set("Authorization", `Bearer ${authToken}`);
  }
  return headers;
}

// Turns FastAPI error bodies ({detail: "..."} or a list of validation errors) into one readable line.
async function readErrorDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    const detail = body?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((item: any) => {
          const last = Array.isArray(item?.loc) ? item.loc[item.loc.length - 1] : "";
          // Model-level errors point at "body"/"query" itself, which is not a field name.
          const field = last === "body" || last === "query" || last === "path" ? "" : last;
          const text = String(item?.msg ?? "").replace(/^Value error, /, "");
          return field && !text.includes(String(field)) ? `${field}: ${text}` : text;
        })
        .filter(Boolean)
        .join("; ");
    }
  } catch {
    // body was not JSON
  }
  return "";
}

async function parseJson<T>(response: Response, message: string, opts?: { skipUnauthorizedHandler?: boolean }): Promise<T> {
  if (!response.ok) {
    if (response.status === 401 && unauthorizedHandler && !opts?.skipUnauthorizedHandler) {
      unauthorizedHandler();
    }
    const detail = translateServer(await readErrorDetail(response));
    const error = new Error(`${message}: ${detail || response.status}`) as Error & { status?: number };
    error.status = response.status;
    throw error;
  }
  return response.json() as Promise<T>;
}

export type Session = { token: string; email: string; role: User['role']; expires_in: number };

export async function login(email: string, password: string, otp?: string) {
  const r = await fetch(`${BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(otp ? { email, password, otp } : { email, password }),
  });
  // A wrong password is a 401 too, but it must not look like an expired session.
  return parseJson<Session>(r, t("Login failed"), { skipUnauthorizedHandler: true });
}

// True on a fresh deployment with no accounts: the sign-in page then offers to create the first admin.
export async function getSetupStatus(): Promise<boolean> {
  try {
    const r = await fetch(`${BASE}/api/auth/setup`);
    if (!r.ok) return false;
    const body = await r.json();
    return body?.needed === true;
  } catch {
    return false;
  }
}

export async function setupFirstAdmin(email: string, password: string) {
  const r = await fetch(`${BASE}/api/auth/setup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  return parseJson<Session>(r, t("Setup failed"), { skipUnauthorizedHandler: true });
}

export async function postReport(data: any) {
  // A weak field connection can hang for minutes: give up after 30 s (the log is then kept offline).
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30000);
  try {
    const r = await fetch(`${BASE}/api/reports`, {
      method: "POST",
      headers: buildHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(data),
      signal: controller.signal,
    });
    return await parseJson<{ status: string }>(r, t("Failed to post report"));
  } finally {
    clearTimeout(timer);
  }
}

/** One log by Borehole ID (case-insensitive), or null. */
export async function getReport(boreholeId: string): Promise<Record<string, string> | null> {
  const wanted = boreholeId.trim().toLowerCase();
  const rows = await listReports();
  return rows.find(r => String(r?.BoreholeID || "").trim().toLowerCase() === wanted) ?? null;
}

export async function listReports() {
  const r = await fetch(`${BASE}/api/reports`, {
    headers: buildHeaders(),
  });
  return parseJson<any[]>(r, t("Failed to list reports"));
}

export async function updateReport(boreholeId: string, data: any) {
  const r = await fetch(`${BASE}/api/reports/${encodeURIComponent(boreholeId)}`, {
    method: "PUT",
    headers: buildHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(data),
  });
  return parseJson<{ status: string }>(r, t("Failed to update report"));
}

export async function deleteReport(boreholeId: string) {
  const r = await fetch(`${BASE}/api/reports/${encodeURIComponent(boreholeId)}`, {
    method: "DELETE",
    headers: buildHeaders(),
  });
  return parseJson<{ status: string }>(r, t("Failed to delete report"));
}

export async function askAI(question: string, context?: string, history?: Array<{ role: string; content: string }>) {
  const r = await fetch(`${BASE}/api/ai/analyze`, {
    method: "POST",
    headers: buildHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ question, context, history }),
  });
  return parseJson<any>(r, t("AI error"));
}

// System prompt plus the relevant data rows, sized for the on-device AI's short context.
export async function getAIPrompt(question: string, maxChars: number) {
  const r = await fetch(`${BASE}/api/ai/prompt`, {
    method: "POST",
    headers: buildHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ question, max_chars: Math.max(1000, Math.min(60000, Math.floor(maxChars))) }),
  });
  return parseJson<{ system: string; context: string }>(r, t("AI error"));
}

export async function getSummary(period: "weekly" | "monthly", filters?: Record<string, string | number>) {
  const params = new URLSearchParams({ period, lang: lang() })
  if (filters) {
    Object.entries(filters).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') {
        params.set(key, String(value))
      }
    })
  }
  const r = await fetch(`${BASE}/api/summaries?${params.toString()}`, { headers: buildHeaders() });
  return parseJson<SummaryResponse>(r, t("Failed to get summary"));
}

export async function getDashboard() {
  const r = await fetch(`${BASE}/api/dashboard?lang=${lang()}`, { headers: buildHeaders() });
  return parseJson<DashboardResponse>(r, t("Failed to get dashboard"));
}

export async function listUsers() {
  const r = await fetch(`${BASE}/api/users`, {
    headers: buildHeaders(),
  })
  return parseJson<User[]>(r, t("Failed to load users"))
}

export async function createUser(payload: { email: string; password: string; role: User['role'] }) {
  const r = await fetch(`${BASE}/api/users`, {
    method: "POST",
    headers: buildHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  })
  return parseJson<User>(r, t("Failed to create user"))
}

export async function deleteUser(email: string) {
  const r = await fetch(`${BASE}/api/users/${encodeURIComponent(email)}`, {
    method: "DELETE",
    headers: buildHeaders(),
  })
  return parseJson<{ status: string }>(r, t("Failed to delete user"))
}

export async function changePassword(currentPassword: string, newPassword: string) {
  const r = await fetch(`${BASE}/api/auth/change-password`, {
    method: "POST",
    headers: buildHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
  return parseJson<{ token: string; email: string; role: User['role']; expires_in: number }>(r, t("Could not change the password"));
}

export async function resetUserPassword(email: string, password: string) {
  const r = await fetch(`${BASE}/api/users/${encodeURIComponent(email)}/password`, {
    method: "PUT",
    headers: buildHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ password }),
  });
  return parseJson<{ status: string }>(r, t("Could not reset the password"));
}

// Downloads all logs of one project as an AGS4 file (the browser saves it).
export async function downloadAgs(project: string) {
  const r = await fetch(`${BASE}/api/export/ags?${new URLSearchParams({ project })}`, { headers: buildHeaders() });
  if (!r.ok) {
    await parseJson<unknown>(r, t("AGS4 export failed"));
  }
  const match = /filename="([^"]+)"/.exec(r.headers.get("Content-Disposition") || "");
  const filename = match ? match[1] : "export.ags";
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return filename;
}

export const APP_NAME = "Soil Boring Ops";

export function appTitle(orgName: string) {
  return orgName ? `${orgName} · ${APP_NAME}` : APP_NAME;
}

// Public, non-secret settings (organisation name) from the backend's ORG_NAME.
export type PublicConfig = { org_name: string; ai_server: boolean; email_reset: boolean }

let publicConfig: Promise<PublicConfig> | null = null

export function getPublicConfig(): Promise<PublicConfig> {
  if (!publicConfig) {
    publicConfig = (async () => {
      try {
        const r = await fetch(`${BASE}/api/config`);
        if (!r.ok) throw new Error(String(r.status));
        const body = await r.json();
        return {
          org_name: typeof body?.org_name === "string" ? body.org_name.trim() : "",
          ai_server: body?.ai_server === true,
          email_reset: body?.email_reset === true,
        };
      } catch {
        publicConfig = null; // try again next time
        return { org_name: "", ai_server: false, email_reset: false };
      }
    })();
  }
  return publicConfig;
}


// ---------------------------------------------------------------------------
// Depth data, photos, activity log
// ---------------------------------------------------------------------------

export type Layer = { top: number; base: number; uscs: string; description: string }
export type SPTTest = {
  depth: number; seat: number; inc1: number; inc2: number | null; penetration_mm: number | null; remarks: string
  n?: number; reported?: string
}
export type Sample = { top: number; base: number | null; type: string; ref: string; remarks: string }
export type CoreRun = { top: number; base: number; tcr: number | null; scr: number | null; rqd: number | null; remarks: string }
export type PhotoMeta = {
  id: string; caption: string; depth: number | null; content_type: string; size: number; added_at: string; added_by: string
}
export type Details = {
  borehole_id: string
  layers: Layer[]; spt: SPTTest[]; samples: Sample[]; core: CoreRun[]; photos: PhotoMeta[]
  updated_at?: string; updated_by?: string
}
export type AuditEvent = { at: string; user: string; action: string; target: string; changes?: Record<string, unknown> }

const enc = (id: string) => encodeURIComponent(id)

export type DepthOverview = Record<string, {
  layers: Array<{ top: number; base: number; uscs: string }>
  spt: Array<{ depth: number; n: number | null }>
  samples: number; core: number; photos: number
}>

export async function getDepthOverview() {
  const r = await fetch(`${BASE}/api/depth-overview`, { headers: buildHeaders() });
  return parseJson<DepthOverview>(r, t("Failed to load depth data"));
}

export async function getDetails(boreholeId: string) {
  const r = await fetch(`${BASE}/api/details/${enc(boreholeId)}`, { headers: buildHeaders() });
  return parseJson<Details>(r, t("Failed to load depth data"));
}

export async function saveDetails(boreholeId: string, data: Pick<Details, 'layers' | 'spt' | 'samples' | 'core'> & { expected_updated_at?: string }) {
  const r = await fetch(`${BASE}/api/details/${enc(boreholeId)}`, {
    method: "PUT",
    headers: buildHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(data),
  });
  return parseJson<Details>(r, t("Failed to save depth data"));
}

export async function uploadPhoto(payload: { borehole_id: string; content_type: string; data_base64: string; caption: string; depth: number | null }) {
  const r = await fetch(`${BASE}/api/photos`, {
    method: "POST",
    headers: buildHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  return parseJson<PhotoMeta>(r, t("Failed to upload photo"));
}

/** Photos need the sign-in header, so they are fetched and shown through blob: URLs. */
export async function photoBlob(photoId: string): Promise<Blob> {
  const r = await fetch(`${BASE}/api/photos/${enc(photoId)}`, { headers: buildHeaders() });
  if (!r.ok) throw new Error(t("Photo: {status}", { status: r.status }));
  return r.blob();
}

export async function deletePhoto(photoId: string) {
  const r = await fetch(`${BASE}/api/photos/${enc(photoId)}`, { method: "DELETE", headers: buildHeaders() });
  return parseJson<{ status: string }>(r, t("Failed to delete photo"));
}

export async function getActivity(target?: string, limit = 200) {
  const params = new URLSearchParams({ limit: String(limit) })
  if (target) params.set("target", target)
  const r = await fetch(`${BASE}/api/audit?${params}`, { headers: buildHeaders() });
  return parseJson<AuditEvent[]>(r, t("Failed to load activity"));
}

// ---------------------------------------------------------------------------
// Account security
// ---------------------------------------------------------------------------

export type Me = { email: string; role: User['role']; totp_enabled: boolean; recovery_codes_left: number }

export async function getMe() {
  const r = await fetch(`${BASE}/api/auth/me`, { headers: buildHeaders() });
  return parseJson<Me>(r, t("Failed to load account"));
}

async function postJson<T>(path: string, body: unknown, message: string, auth = true) {
  const r = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: auth ? buildHeaders({ "Content-Type": "application/json" }) : { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  return parseJson<T>(r, message, { skipUnauthorizedHandler: !auth });
}

export const startTwoFactor = () => postJson<{ secret: string; otpauth_uri: string }>("/api/auth/2fa/setup", {}, t("Setup failed"))
export const enableTwoFactor = (code: string) => postJson<{ recovery_codes: string[] }>("/api/auth/2fa/enable", { code }, t("Could not turn on two-step verification"))
export const disableTwoFactor = (password: string, code: string) => postJson<{ status: string }>("/api/auth/2fa/disable", { password, code }, t("Could not turn off two-step verification"))
export const newRecoveryCodes = (password: string) => postJson<{ recovery_codes: string[] }>("/api/auth/recovery-codes", { password }, t("Could not create recovery codes"))
export const resetWithCode = (email: string, recovery_code: string, new_password: string, otp?: string) =>
  postJson<{ status: string }>("/api/auth/reset-with-code", { email, recovery_code, new_password, ...(otp ? { otp } : {}) }, t("Reset failed"), false)
export const requestResetEmail = (email: string) => postJson<{ status: string; email_enabled: boolean }>("/api/auth/forgot", { email }, t("Request failed"), false)
export const resetWithToken = (token: string, new_password: string) =>
  postJson<{ status: string }>("/api/auth/reset", { token, new_password }, t("Reset failed"), false)

export async function resetUserTwoFactor(email: string) {
  const r = await fetch(`${BASE}/api/users/${encodeURIComponent(email)}/2fa`, { method: "DELETE", headers: buildHeaders() })
  return parseJson<{ status: string }>(r, t("Failed to turn off two-step verification"))
}


// ---------------------------------------------------------------------------
// Business records (clients, projects, quotations, contracts, field work, lab,
// analyses, reports, invoices, settings) — see backend/app/entities.py
// ---------------------------------------------------------------------------

export type FieldDef = {
  name: string
  type: string
  label: string
  section?: string
  required: boolean
  options: Array<[string, string] | [string, string, string]> | null
  options_filter: string | null
  ref: string | null
  min: number | null
  max: number | null
  maxlen: number
  help: string
  fields: FieldDef[] | null
  max_items: number
  list: boolean
  readonly: boolean
  default: unknown
  variants_by: string | null
  variants: Record<string, FieldDef[]> | null
  private: boolean
}
export type EntityDef = {
  name: string
  label: string
  label_one: string
  fields: FieldDef[]
  title: string
  number_field: string
  singleton: boolean
  group: string
  can_read: boolean
  can_create: boolean
}
export type Schemas = Record<string, EntityDef>
export type Rec = Record<string, any> & { id: string, _can_edit?: boolean, updated_at?: string }
export type FileMeta = { id: string, name: string, type: string, size: number }

export async function getSchemas() {
  const r = await fetch(`${BASE}/api/schemas`, { headers: buildHeaders() });
  return parseJson<Schemas>(r, t("Failed to load"));
}

export async function listRecords(entity: string, projectId?: string) {
  const q = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  const r = await fetch(`${BASE}/api/records/${entity}${q}`, { headers: buildHeaders() });
  return parseJson<Rec[]>(r, t("Failed to load"));
}

export async function getRecord(entity: string, id: string) {
  const r = await fetch(`${BASE}/api/records/${entity}/${encodeURIComponent(id)}`, { headers: buildHeaders() });
  return parseJson<Rec>(r, t("Failed to load"));
}

export async function saveRecord(entity: string, data: Record<string, unknown>, id?: string) {
  const r = await fetch(`${BASE}/api/records/${entity}${id ? `/${encodeURIComponent(id)}` : ""}`, {
    method: id ? "PUT" : "POST",
    headers: buildHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(data),
  });
  return parseJson<Rec>(r, t("Could not save"));
}

export async function deleteRecord(entity: string, id: string) {
  const r = await fetch(`${BASE}/api/records/${entity}/${encodeURIComponent(id)}`, { method: "DELETE", headers: buildHeaders() });
  return parseJson<{ status: string }>(r, t("Could not delete"));
}

export async function uploadFile(file: File): Promise<FileMeta> {
  const buf = new Uint8Array(await file.arrayBuffer());
  let bin = "";
  for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode(...buf.subarray(i, i + 0x8000));
  const type = file.type || (file.name.toLowerCase().endsWith(".csv") ? "text/csv" : "application/octet-stream");
  return postJson<FileMeta>("/api/files", { name: file.name, content_type: type, data_base64: btoa(bin) }, t("Upload failed"));
}

export async function downloadFile(meta: FileMeta) {
  const r = await fetch(`${BASE}/api/files/${encodeURIComponent(meta.id)}`, { headers: buildHeaders() });
  if (!r.ok) throw new Error(t("Download failed"));
  const url = URL.createObjectURL(await r.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = meta.name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function userDirectory() {
  const r = await fetch(`${BASE}/api/users/directory`, { headers: buildHeaders() });
  return parseJson<Array<{ email: string, role: Role }>>(r, t("Failed to load users"));
}

export async function runAnalysis(type: string, inputs: Record<string, unknown>) {
  return postJson<Record<string, any>>("/api/analyses/run", { type, inputs }, t("Calculation failed"));
}

// ---------------------------------------------------------------------------
// Worksheets, sample register, coordinates
// ---------------------------------------------------------------------------

export type SheetInfo = {
  key: string; kind: "field" | "lab" | "page"; group: string; code: string; label: string;
  standards: Array<[string, string]>; example: Record<string, any>; calc: boolean; help: string; link: string;
};

export type CalcResult = {
  error?: string;
  summary?: string;
  values?: Array<{ label: string; value: any; unit: string }>;
  tables?: Array<{ title: string; columns: string[]; rows: any[][] }>;
  charts?: ChartSpec[];
  notes?: string[];
  method?: string;
  lab?: Record<string, any>;
};

export type ChartAxis = { label: string; log?: boolean; reverse?: boolean };
export type ChartSpec = {
  title: string; x: ChartAxis; y: ChartAxis; kind?: "xy" | "value";
  series?: Array<{ name: string; points: Array<[number, number]>; style?: "line" | "points" | "both"; dash?: boolean }>;
  points?: Array<[number, number, number]>; value_label?: string; log_value?: boolean;
};

export type SampleRow = {
  borehole_id: string; project: string; top: number; base: number | null; type: string; ref: string; remarks: string;
  tests: Array<{ id: string; test_type: string; status: string }>;
};

let catalogPromise: Promise<SheetInfo[]> | null = null;
export function getCatalog(): Promise<SheetInfo[]> {
  if (!catalogPromise) {
    catalogPromise = fetch(`${BASE}/api/worksheets`, { headers: buildHeaders() })
      .then(r => parseJson<SheetInfo[]>(r, t("Failed to load")))
      .catch(err => { catalogPromise = null; throw err; });
  }
  return catalogPromise;
}

export async function calcWorksheet(kind: "field" | "lab" | "cpt", key: string, data: Record<string, unknown>) {
  return postJson<CalcResult>("/api/worksheets/calc", { kind, key, data }, t("Calculation failed"));
}

export async function getSamples(project?: string) {
  const q = project ? `?project=${encodeURIComponent(project)}` : "";
  const r = await fetch(`${BASE}/api/samples${q}`, { headers: buildHeaders() });
  return parseJson<SampleRow[]>(r, t("Failed to load"));
}

export type CoordRow = {
  name?: string; latitude?: number | null; longitude?: number | null; easting?: number | null; northing?: number | null;
  zone?: number | null; hemisphere?: string; elevation?: number | null;
};
export type CoordOut = CoordRow & { error?: string; dms?: string };

export async function convertCoordinates(rows: CoordRow[]) {
  return postJson<CoordOut[]>("/api/tools/coordinates", { rows }, t("Calculation failed"));
}

async function saveBlob(r: Response, fallbackName: string) {
  if (!r.ok) {
    const detail = translateServer(await readErrorDetail(r));
    throw new Error(`${t("Download failed")}: ${detail || r.status}`);
  }
  const cd = r.headers.get("Content-Disposition") || "";
  const m = /filename="([^"]+)"/.exec(cd);
  const url = URL.createObjectURL(await r.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = m ? m[1] : fallbackName;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function downloadPointsKml(name: string, points: Array<{ name: string; latitude: number; longitude: number; elevation?: number | null; folder?: string; description?: string }>) {
  const headers = buildHeaders();
  headers.set("Content-Type", "application/json");
  const r = await fetch(`${BASE}/api/tools/kml`, { method: "POST", headers, body: JSON.stringify({ name, points }) });
  await saveBlob(r, "points.kml");
}

export async function downloadProjectKml(projectId: string) {
  const r = await fetch(`${BASE}/api/export/kml?project_id=${encodeURIComponent(projectId)}`, { headers: buildHeaders() });
  await saveBlob(r, "project.kml");
}
