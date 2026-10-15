const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 });

export const money = (v) => (v == null ? "—" : usd.format(v));
export const signedMoney = (v) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}${usd.format(Math.abs(v))}`);
export const pct = (v) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(2)}%`);
export const big = (v) => (v == null ? "—" : compact.format(v));
export const num = (v, d = 2) => (v == null ? "—" : v.toLocaleString("en-US", { maximumFractionDigits: d }));
export const shares = (v) => (v == null ? "—" : v.toLocaleString("en-US", { maximumFractionDigits: 6 }));
export const tone = (v) => (v == null || v === 0 ? "" : v > 0 ? "up" : "down");

/** How a trade happened, e.g. "Market buy", "Limit sell" or "Dividend reinvested". */
export const tradeLabel = (t) =>
  t.order_type === "dividend" ? "Dividend reinvested" : `${t.order_type === "limit" ? "Limit" : "Market"} ${t.side}`;

// Times are shown in US Central Time.
export const TZ = "America/Chicago";

export const parseUtc = (iso) => new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`);

export function dateTime(iso) {
  return `${parseUtc(iso).toLocaleString("en-US", { timeZone: TZ, month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" })} CT`;
}

/** "8:30 AM CT" */
export const clockTime = (date) => `${date.toLocaleTimeString("en-US", { timeZone: TZ, hour: "numeric", minute: "2-digit" })} CT`;

/** Short day and time, e.g. "Thu, Oct 15, 8:30 AM CT", or "today, 8:30 AM CT". */
export function whenCT(date) {
  const day = (x) => x.toLocaleDateString("en-US", { timeZone: TZ, year: "numeric", month: "numeric", day: "numeric" });
  const today = day(new Date()) === day(date);
  const tomorrow = day(new Date(Date.now() + 86_400_000)) === day(date);
  const prefix = today ? "today" : tomorrow ? "tomorrow" : date.toLocaleDateString("en-US", { timeZone: TZ, weekday: "short", month: "short", day: "numeric" });
  return `${prefix} at ${clockTime(date)}`;
}
