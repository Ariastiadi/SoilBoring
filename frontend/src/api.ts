// Origin of the backend. Empty = same origin (Docker/nginx and the Vite dev proxy).
// Every request path below already starts with "/api", so a trailing "/api" or "/"
// in VITE_API_URL (older docs told people to use "/api") is stripped to avoid "/api/api".
const BASE = String(import.meta.env.VITE_API_URL ?? "")
  .trim()
  .replace(/\/+$/, "")
  .replace(/\/api$/, "");

export type User = {
  email: string
  role: 'admin' | 'general'
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

export type SummaryResponse = {
  period: "weekly" | "monthly"
  text: string
  stats?: SummaryStats
  highlights?: string[]
  narrative?: string | null
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
    const detail = await readErrorDetail(response);
    const error = new Error(`${message}: ${detail || response.status}`) as Error & { status?: number };
    error.status = response.status;
    throw error;
  }
  return response.json() as Promise<T>;
}

export async function login(email: string, password: string) {
  const r = await fetch(`${BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  // A wrong password is a 401 too, but it must not look like an expired session.
  return parseJson<{ token: string; email: string; role: User['role']; expires_in: number }>(r, "Login failed", { skipUnauthorizedHandler: true });
}

export async function postReport(data: any) {
  const r = await fetch(`${BASE}/api/reports`, {
    method: "POST",
    headers: buildHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(data),
  });
  return parseJson<{ status: string }>(r, "Failed to post report");
}

export async function listReports() {
  const r = await fetch(`${BASE}/api/reports`, {
    headers: buildHeaders(),
  });
  return parseJson<any[]>(r, "Failed to list reports");
}

export async function updateReport(boreholeId: string, data: any) {
  const r = await fetch(`${BASE}/api/reports/${encodeURIComponent(boreholeId)}`, {
    method: "PUT",
    headers: buildHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(data),
  });
  return parseJson<{ status: string }>(r, "Failed to update report");
}

export async function deleteReport(boreholeId: string) {
  const r = await fetch(`${BASE}/api/reports/${encodeURIComponent(boreholeId)}`, {
    method: "DELETE",
    headers: buildHeaders(),
  });
  return parseJson<{ status: string }>(r, "Failed to delete report");
}

export async function askAI(question: string, context?: string, history?: Array<{ role: string; content: string }>) {
  const r = await fetch(`${BASE}/api/ai/analyze`, {
    method: "POST",
    headers: buildHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ question, context, history }),
  });
  return parseJson<any>(r, "AI error");
}

export async function getSummary(period: "weekly" | "monthly", filters?: Record<string, string | number>) {
  const params = new URLSearchParams({ period })
  if (filters) {
    Object.entries(filters).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') {
        params.set(key, String(value))
      }
    })
  }
  const r = await fetch(`${BASE}/api/summaries?${params.toString()}`, { headers: buildHeaders() });
  return parseJson<SummaryResponse>(r, "Failed to get summary");
}

export async function getDashboard() {
  const r = await fetch(`${BASE}/api/dashboard`, { headers: buildHeaders() });
  return parseJson<DashboardResponse>(r, "Failed to get dashboard");
}

export async function listUsers() {
  const r = await fetch(`${BASE}/api/users`, {
    headers: buildHeaders(),
  })
  return parseJson<User[]>(r, "Failed to load users")
}

export async function createUser(payload: { email: string; password: string; role: User['role'] }) {
  const r = await fetch(`${BASE}/api/users`, {
    method: "POST",
    headers: buildHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  })
  return parseJson<User>(r, "Failed to create user")
}

export async function deleteUser(email: string) {
  const r = await fetch(`${BASE}/api/users/${encodeURIComponent(email)}`, {
    method: "DELETE",
    headers: buildHeaders(),
  })
  return parseJson<{ status: string }>(r, "Failed to delete user")
}

export async function changePassword(currentPassword: string, newPassword: string) {
  const r = await fetch(`${BASE}/api/auth/change-password`, {
    method: "POST",
    headers: buildHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
  return parseJson<{ token: string; email: string; role: User['role']; expires_in: number }>(r, "Could not change the password");
}

export async function resetUserPassword(email: string, password: string) {
  const r = await fetch(`${BASE}/api/users/${encodeURIComponent(email)}/password`, {
    method: "PUT",
    headers: buildHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ password }),
  });
  return parseJson<{ status: string }>(r, "Could not reset the password");
}

// Downloads all logs of one project as an AGS4 file (the browser saves it).
export async function downloadAgs(project: string) {
  const r = await fetch(`${BASE}/api/export/ags?${new URLSearchParams({ project })}`, { headers: buildHeaders() });
  if (!r.ok) {
    await parseJson<unknown>(r, "AGS4 export failed");
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

// Optional organisation name shown in the title bar (build-time setting).
export const ORG_NAME = String(import.meta.env.VITE_ORG_NAME ?? "").trim();
export const APP_TITLE = ORG_NAME ? `${ORG_NAME} · Soil Boring Ops` : "Soil Boring Ops";
