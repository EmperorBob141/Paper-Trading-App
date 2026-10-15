import { useEffect, useMemo, useState } from "react";
import { Area, AreaChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api.js";
import { money, TZ } from "../format.js";

export const RANGES = ["1D", "1W", "1M", "3M", "6M", "1Y", "3Y", "5Y", "ALL"];

function labelFor(t, range) {
  const d = new Date(t * 1000);
  if (range === "1D") return `${d.toLocaleTimeString("en-US", { timeZone: TZ, hour: "numeric", minute: "2-digit" })} CT`;
  if (range === "1W") return `${d.toLocaleString("en-US", { timeZone: TZ, weekday: "short", hour: "numeric", minute: "2-digit" })} CT`;
  if (["3Y", "5Y", "ALL"].includes(range)) return d.toLocaleDateString("en-US", { timeZone: TZ, month: "short", year: "numeric" });
  return d.toLocaleDateString("en-US", { timeZone: TZ, month: "short", day: "numeric", year: "numeric" });
}

// Robinhood-style price chart: one line, green when up over the range, red when down, and a dashed
// baseline at the range's starting price. The page shows the readout: onReadout gets the range's
// starting price, latest price and hovered price whenever they change.
export default function PriceChart({ symbol, previousClose, range, onRangeChange, onReadout }) {
  const [points, setPoints] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [hover, setHover] = useState(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError("");
    api.history(symbol, range)
      .then((d) => alive && setPoints(d.points))
      .catch((e) => alive && setError(e.message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [symbol, range]);

  const base = range === "1D" && previousClose ? previousClose : points[0]?.close;
  const last = points[points.length - 1]?.close;
  const color = (last ?? 0) >= (base ?? 0) ? "var(--up)" : "var(--down)";

  useEffect(() => {
    onReadout?.({ base, last, hover, loading });
  }, [base, last, hover, loading, onReadout]);

  const domain = useMemo(() => {
    if (!points.length) return ["auto", "auto"];
    const vals = points.map((p) => p.close).concat(base ?? []);
    const lo = Math.min(...vals), hi = Math.max(...vals);
    const pad = (hi - lo) * 0.08 || hi * 0.01;
    return [lo - pad, hi + pad];
  }, [points, base]);

  return (
    <div className="price-chart">
      <div className="chart-area" onMouseLeave={() => setHover(null)}>
        {error ? (
          <div className="chart-empty">{error}</div>
        ) : loading && !points.length ? (
          <div className="chart-empty">Loading chart…</div>
        ) : (
          <ResponsiveContainer width="100%" height={320}>
            <AreaChart
              data={points}
              margin={{ top: 8, right: 0, bottom: 0, left: 0 }}
              onMouseMove={(s) => setHover(s?.activePayload?.[0]?.payload?.close ?? null)}
            >
              <defs>
                <linearGradient id="fill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={color} stopOpacity={0.18} />
                  <stop offset="100%" stopColor={color} stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="t" hide />
              <YAxis domain={domain} hide />
              {base && <ReferenceLine y={base} stroke="var(--text-muted)" strokeDasharray="2 4" />}
              <Tooltip
                cursor={{ stroke: "var(--text-muted)", strokeWidth: 1 }}
                content={({ active, payload }) =>
                  active && payload?.length ? (
                    <div className="chart-tip">
                      <div className="muted small">{labelFor(payload[0].payload.t, range)}</div>
                      <div>{money(payload[0].payload.close)}</div>
                    </div>
                  ) : null
                }
              />
              <Area type="linear" dataKey="close" stroke={color} strokeWidth={2} fill="url(#fill)" dot={false} activeDot={{ r: 5, strokeWidth: 2, stroke: "var(--bg)" }} isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
      <div className="range-tabs">
        {RANGES.map((r) => (
          <button key={r} className={r === range ? "active" : ""} style={r === range ? { color } : undefined} onClick={() => onRangeChange(r)}>
            {r}
          </button>
        ))}
      </div>
    </div>
  );
}
