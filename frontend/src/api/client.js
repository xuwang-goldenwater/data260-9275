// All calls to the FastAPI backend (PORT_BASE 8275).
//
// credentials: "include" makes the browser send the HTTP-only session cookie
// with every request. JavaScript never sees the cookie itself; it only learns
// "logged in" or "not logged in" from /api/auth/me.
//
// Use http://localhost:5173 (not 127.0.0.1) in the browser, so the page and
// the API share the host "localhost" and the SameSite=Lax cookie is sent.

const API_BASE = "http://localhost:8275";

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

async function request(path, { method = "GET", body } = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    credentials: "include",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = data?.detail;
    const message = typeof detail === "string" ? detail : `Request failed (${res.status})`;
    throw new ApiError(res.status, message);
  }
  return data;
}

// ---- auth ----
export const login = (email, password) =>
  request("/api/auth/login", { method: "POST", body: { email, password } });
export const logout = () => request("/api/auth/logout", { method: "POST" });
export const me = () => request("/api/auth/me");

// ---- recall notices ----
export const listNotices = (page, pageSize) =>
  request(`/api/notices?page=${page}&page_size=${pageSize}`);
export const getNotice = (id) => request(`/api/notices/${id}`);
export const createNotice = (notice) =>
  request("/api/notices", { method: "POST", body: notice });
export const updateNotice = (id, notice) =>
  request(`/api/notices/${id}`, { method: "PUT", body: notice });
export const deleteNotice = (id) => request(`/api/notices/${id}`, { method: "DELETE" });

export const CATEGORIES = [
  "Undeclared Allergen",
  "Bacterial Contamination",
  "Foreign Material",
  "Mislabeling",
];
