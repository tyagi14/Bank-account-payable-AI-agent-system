export const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:18000";
export const LINKS = {
  grafana: process.env.NEXT_PUBLIC_GRAFANA_URL || "http://localhost:13002",
  langfuse: process.env.NEXT_PUBLIC_LANGFUSE_URL || "http://localhost:13001",
};

export async function api(path, { token, ...init } = {}) {
  const headers = { ...(init.body && !(init.body instanceof FormData) ? { "Content-Type": "application/json" } : {}), ...(init.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${API}${path}`, { ...init, headers });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail || body));
  return body;
}

export const money = (cents) => (cents == null ? "-" : `$${(cents / 100).toLocaleString(undefined, { minimumFractionDigits: 2 })}`);
