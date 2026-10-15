import { useEffect, useMemo, useState } from "react";
import { CartesianGrid, Customized, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api.js";
import { money, num, parseUtc, pct, tone, TZ } from "../format.js";

export const COMPARE_RANGES = ["1D", "1W", "1M", "3M", "6M", "YTD", "1Y", "3Y", "5Y", "ALL"];

// Fixed identity colors (validated as a set on the dark surface): you are always green,
// the S&P 500 blue, the Nasdaq magenta. They never change with the range or with toggles.
export const SERIES = [
  { key: "you", label: "You", color: "var(--series-you)" },
  { key: "sp", label: "S&P 500", color: "var(--series-sp)" },
  { key: "nq", label: "Nasdaq", color: "var(--series-nq)" },
];

function timeLabel(t, granularity) {
  const d = new Date(t * 1000);
  if (granularity === "intraday") {
    return `${d.toLocaleString("en-US", { timeZone: TZ, weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })} CT`;
  }
  return d.toLocaleDateString("en-US", { timeZone: TZ, month: "short", day: "numeric", year: "numeric" });
}

function tickLabel(t, range) {
  const d = new Date(t * 1000);
  if (range === "1D") return d.toLocaleTimeString("en-US", { timeZone: TZ, hour: "numeric", minute: "2-digit" });
  if (range === "1W") return d.toLocaleDateString("en-US", { timeZone: TZ, weekday: "short" });
  if (["3Y", "5Y", "ALL"].includes(range)) {
    return `${d.toLocaleDateString("en-US", { timeZone: TZ, month: "short" })} '${d.toLocaleDateString("en-US", { timeZone: TZ, year: "2-digit" })}`;
  }
  return d.toLocaleDateString("en-US", { timeZone: TZ, month: "short", day: "numeric" });
}

// Direct labels: each visible series' name and final % at the right end of its line,
// nudged apart vertically so close finishes don't overlap.
function EndLabels({ xAxisMap, yAxisMap, points, shown }) {
  const xScale = Object.values(xAxisMap || {})[0]?.scale;
  const yScale = Object.values(yAxisMap || {})[0]?.scale;
  const last = points[points.length - 1];
  if (!xScale || !yScale || !last) return null;
  const x = xScale(last.t);
  const items = SERIES.filter((s) => shown[s.key] && last[s.key] != null)
    .map((s) => ({ ...s, y: yScale(last[s.key]), ly: yScale(last[s.key]) }))
    .sort((a, b) => a.y - b.y);
  for (let i = 1; i < items.length; i++) {
    if (items[i].ly - items[i - 1].ly < 16) items[i].ly = items[i - 1].ly + 16;
  }
  return (
    <g>
      {items.map((s) => (
        <g key={s.key}>
          <circle cx={x} cy={s.y} r={4} fill={s.color} stroke="var(--bg)" strokeWidth={2} />
          <text x={x + 10} y={s.ly + 4} fontSize={12} fill="var(--text)" fontWeight={600}>
            {s.label} <tspan fill="var(--text-muted)" fontWeight={400}>{pct(last[s.key])}</tspan>
          </text>
        </g>
      ))}
    </g>
  );
}

export default function CompareChart({ range: controlledRange, onRangeChange, height = 340, showTabs = true, onData }) {
  const [ownRange, setOwnRange] = useState("1M");
  const range = controlledRange ?? ownRange;
  const setRange = onRangeChange ?? setOwnRange;
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [shown, setShown] = useState({ you: true, sp: true, nq: true });

  useEffect(() => {
    let alive = true;
    setLoading(true);
    api.compare(range)
      .then((d) => {
        if (!alive) return;
        setData(d);
        setError("");
        onData?.(d);
      })
      .catch((e) => alive && setError(e.message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [range]); // eslint-disable-line react-hooks/exhaustive-deps

  const points = data?.points ?? [];
  const ticks = useMemo(() => {
    const n = points.length;
    if (n < 3) return points.map((p) => p.t);
    return Array.from({ length: 5 }, (_, i) => points[Math.round((i * (n - 1)) / 4)].t);
  }, [points]);
  const stats = data?.stats;
  const empty = !loading && points.length < 2;

  return (
    <div className={`compare ${loading ? "is-loading" : ""}`}>
      <div className="compare-legend">
        {SERIES.map((s) => (
          <button
            key={s.key}
            className={`legend-chip ${shown[s.key] ? "" : "off"}`}
            onClick={() => s.key !== "you" && setShown((v) => ({ ...v, [s.key]: !v[s.key] }))}
            title={s.key === "you" ? undefined : shown[s.key] ? `Hide ${s.label}` : `Show ${s.label}`}
            aria-pressed={shown[s.key]}
          >
            <span className="swatch" style={{ background: s.color }} />
            <span className="legend-name">{s.label}</span>
            <span className={`legend-value ${tone(stats?.[s.key]?.return_pct)}`}>{stats ? pct(stats[s.key].return_pct) : "—"}</span>
          </button>
        ))}
      </div>

      {data?.partial && (
        <div className="notice small">
          Your account opened {parseUtc(data.account_opened).toLocaleDateString("en-US", { timeZone: TZ, month: "short", day: "numeric", year: "numeric" })}, so all three lines start there instead of {range} ago.
        </div>
      )}

      <div className="compare-chart" style={{ height }}>
        {error ? (
          <div className="chart-empty">{error}</div>
        ) : empty ? (
          <div className="chart-empty small">
            {range === "1D" ? "No trading yet since your account opened. Check back once the market is open." : "Not enough market data in this range yet."}
          </div>
        ) : !data ? (
          <div className="chart-empty">Loading…</div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={points} margin={{ top: 12, right: 120, bottom: 0, left: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--border)" strokeOpacity={0.5} />
              <XAxis
                dataKey="t"
                type="number"
                scale="time"
                domain={["dataMin", "dataMax"]}
                ticks={ticks}
                tickFormatter={(t) => tickLabel(t, range)}
                tick={{ fill: "var(--text-muted)", fontSize: 12 }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                orientation="left"
                width={56}
                tickFormatter={(v) => `${v > 0 ? "+" : ""}${num(v, Math.abs(v) < 10 ? 1 : 0)}%`}
                tick={{ fill: "var(--text-muted)", fontSize: 12 }}
                axisLine={false}
                tickLine={false}
                domain={["auto", "auto"]}
              />
              <ReferenceLine y={0} stroke="var(--text-muted)" strokeDasharray="2 4" />
              <Tooltip
                cursor={{ stroke: "var(--text-muted)", strokeWidth: 1 }}
                content={({ active, payload }) => {
                  if (!active || !payload?.length) return null;
                  const p = payload[0].payload;
                  return (
                    <div className="chart-tip compare-tip">
                      <div className="muted small">{p === points[0] && data.partial ? "Account opened" : timeLabel(p.t, data.granularity)}</div>
                      {SERIES.filter((s) => shown[s.key] && p[s.key] != null).map((s) => (
                        <div key={s.key} className="tip-row">
                          <span className="swatch" style={{ background: s.color }} />
                          <span>{s.label}</span>
                          <span className={tone(p[s.key])}>{pct(p[s.key])}</span>
                          <span className="muted">{s.key === "you" ? money(p.you_value) : num(p[`${s.key}_value`])}</span>
                        </div>
                      ))}
                    </div>
                  );
                }}
              />
              {[...SERIES].reverse().map((s) =>
                shown[s.key] ? (
                  <Line
                    key={s.key}
                    type="linear"
                    dataKey={s.key}
                    stroke={s.color}
                    strokeWidth={s.key === "you" ? 2.5 : 2}
                    dot={false}
                    activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--bg)" }}
                    connectNulls
                    isAnimationActive={false}
                  />
                ) : null
              )}
              <Customized component={(props) => <EndLabels {...props} points={points} shown={shown} />} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      {showTabs && (
        <div className="range-tabs">
          {COMPARE_RANGES.map((r) => (
            <button key={r} className={r === range ? "active" : ""} onClick={() => setRange(r)}>{r}</button>
          ))}
        </div>
      )}
    </div>
  );
}
