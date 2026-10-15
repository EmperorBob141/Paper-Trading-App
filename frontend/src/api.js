// Thin wrapper over the Python server's /api routes.
async function request(method, path, body) {
  const res = await fetch(`/api${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    credentials: "same-origin",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map((d) => d.msg).join(", ") : data.detail;
    const err = new Error(detail || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
}

export const api = {
  me: () => request("GET", "/me"),
  register: (username, password) => request("POST", "/auth/register", { username, password }),
  login: (username, password) => request("POST", "/auth/login", { username, password }),
  logout: () => request("POST", "/auth/logout"),

  quote: (symbol) => request("GET", `/quote/${encodeURIComponent(symbol)}`),
  history: (symbol, range) => request("GET", `/history/${encodeURIComponent(symbol)}?range=${range}`),
  search: (q) => request("GET", `/search?q=${encodeURIComponent(q)}`),
  indices: () => request("GET", "/indices"),
  marketStatus: () => request("GET", "/market-status"),

  performance: (period) => request("GET", `/performance?period=${period}`),
  compare: (range) => request("GET", `/compare?range=${range}`),
  compareSummary: () => request("GET", "/compare/summary"),
  corporateActions: () => request("GET", "/corporate-actions"),
  deposits: () => request("GET", "/deposits"),
  dividends: () => request("GET", "/dividends"),
  settings: (changes) => request("PUT", "/settings", changes),
  portfolio: () => request("GET", "/portfolio"),
  trade: (order) => request("POST", "/trade", order),
  trades: (symbol) => request("GET", `/trades${symbol ? `?symbol=${encodeURIComponent(symbol)}` : ""}`),

  orders: (symbol) => request("GET", `/orders${symbol ? `?symbol=${encodeURIComponent(symbol)}` : ""}`),
  cancelOrder: (id) => request("DELETE", `/orders/${id}`),

  watchlist: () => request("GET", "/watchlist"),
  watch: (symbol) => request("PUT", `/watchlist/${encodeURIComponent(symbol)}`),
  unwatch: (symbol) => request("DELETE", `/watchlist/${encodeURIComponent(symbol)}`),
};
