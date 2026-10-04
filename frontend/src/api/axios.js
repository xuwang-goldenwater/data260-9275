// One Axios instance for every call to the FastAPI backend (PORT_BASE 8275).
//
// withCredentials: true makes the browser send the HTTP-only session cookie
// with every request. JavaScript never sees the cookie itself.
//
// Open the app at http://localhost:5173 (not 127.0.0.1), so the page and the
// API share the host "localhost" and the SameSite=Lax cookie is sent.
import axios from "axios";

const api = axios.create({
  baseURL: "http://localhost:8275",
  withCredentials: true,
  timeout: 10000,            // ms; a hung request fails instead of spinning forever
});

// Every failed request becomes the same small object: { status, message }.
// FastAPI puts the reason in response.data.detail, in one of two shapes:
//   a string  for 401 / 404 / 409  ->  "recall_number F-9001-2026 already exists"
//   a list    for 422 (Pydantic)   ->  [{ loc: ["body", "recall_number"], msg: "..." }]
export function toApiError(err) {
  const status = err.response?.status ?? 0;      // 0 = no response at all
  const detail = err.response?.data?.detail;

  let message;
  if (typeof detail === "string") {
    message = detail;
  } else if (Array.isArray(detail)) {
    message = detail.map((d) => `${d.loc[d.loc.length - 1]}: ${d.msg}`).join("; ");
  } else if (!err.response) {
    message = "Cannot reach the API on port 8275. Is `make run-hw04` running?";
  } else {
    message = `Request failed (${status})`;
  }
  return { status, message };
}

export default api;
