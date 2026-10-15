import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Area, AreaChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api.js";
import CompareChart, { SERIES } from "../components/CompareChart.jsx";
import DividendIncome from "../components/DividendIncome.jsx";
import Help from "../components/Help.jsx";
import { money, num, pct, signedMoney, tone } from "../format.js";

const PERIODS = ["1W", "1M", "3M", "6M", "YTD", "1Y", "3Y", "5Y", "ALL"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const shortDate = (d) => new Date(`${d}T12:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
// Long ranges label months as "Nov '25" so they can't be mistaken for "Nov 25th".
const axisDate = (d, long) => {
  const dt = new Date(`${d}T12:00:00`);
  return long
    ? `${dt.toLocaleDateString("en-US", { month: "short" })} '${String(dt.getFullYear()).slice(2)}`
    : dt.toLocaleDateString("en-US", { month: "short", day: "numeric" });
};
const compactMoney = (v) => `$${v >= 1e6 ? `${(v / 1e6).toFixed(2)}M` : v >= 1e4 ? `${(v / 1e3).toFixed(1)}K` : v.toFixed(0)}`;

function Kpi({ label, value, sub, valueTone, help }) {
  return (
    <div className="kpi">
      <div className="kpi-label">
        {label}
        {help && <Help text={help} />}
      </div>
      <div className={`kpi-value ${valueTone || ""}`}>{value}</div>
      {sub && <div className="kpi-sub muted">{sub}</div>}
    </div>
  );
}

function SeriesChart({ series, dataKey, height, color, format, axisFormat = format, baseline, long, fillOpacity = 0.16 }) {
  const ticks = useMemo(() => {
    const n = series.length;
    if (n < 3) return series.map((p) => p.d);
    const count = 5;
    return Array.from({ length: count }, (_, i) => series[Math.round((i * (n - 1)) / (count - 1))].d);
  }, [series]);
  const id = `g-${dataKey}`;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={series} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={fillOpacity} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <XAxis dataKey="d" ticks={ticks} tickFormatter={(d) => axisDate(d, long)} tick={{ fill: "var(--text-muted)", fontSize: 12 }} axisLine={false} tickLine={false} />
        <YAxis
          domain={["auto", "auto"]}
          orientation="right"
          width={60}
          tickFormatter={axisFormat}
          tick={{ fill: "var(--text-muted)", fontSize: 12 }}
          axisLine={false}
          tickLine={false}
          tickCount={4}
        />
        {baseline != null && <ReferenceLine y={baseline} stroke="var(--text-muted)" strokeDasharray="2 4" />}
        <Tooltip
          cursor={{ stroke: "var(--text-muted)", strokeWidth: 1 }}
          content={({ active, payload }) =>
            active && payload?.length ? (
              <div className="chart-tip">
                <div className="muted small">{payload[0].payload.opening ? `Account opened ${shortDate(payload[0].payload.d)}` : shortDate(payload[0].payload.d)}</div>
                <div>{format(payload[0].value)}</div>
              </div>
            ) : null
          }
        />
        <Area type="linear" dataKey={dataKey} stroke={color} strokeWidth={2} fill={`url(#${id})`} dot={false} activeDot={{ r: 5, strokeWidth: 2, stroke: "var(--bg)" }} isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

// Green for gains, red for losses; intensity grows with size, capped at ±8% a month.
function heat(v) {
  if (v == null) return undefined;
  const a = Math.min(Math.abs(v) / 8, 1) * 0.55 + 0.08;
  return `color-mix(in srgb, ${v >= 0 ? "var(--up)" : "var(--down)"} ${Math.round(a * 100)}%, transparent)`;
}

function MonthlyTable({ rows }) {
  return (
    <div className="table-wrap">
      <table className="table monthly">
        <thead>
          <tr>
            <th>Year</th>
            {MONTHS.map((m) => <th key={m} className="r">{m}</th>)}
            <th className="r">Year</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.year}>
              <td className="sym">{r.year}</td>
              {r.months.map((v, i) => (
                <td key={i} className="r heat" style={{ background: heat(v) }} title={v == null ? "" : `${MONTHS[i]} ${r.year}: ${pct(v)}`}>
                  {v == null ? "" : `${v >= 0 ? "" : "−"}${Math.abs(v).toFixed(1)}`}
                </td>
              ))}
              <td className={`r sym ${tone(r.total)}`}>{r.total == null ? "—" : pct(r.total)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ContributionBars({ items }) {
  const max = Math.max(...items.map((c) => Math.abs(c.gain)), 1);
  return (
    <div className="bars">
      {items.map((c) => (
        <Link to={`/stock/${c.symbol}`} key={c.symbol} className="bar-row" title={c.dividends ? `Includes ${money(c.dividends)} in dividends` : undefined}>
          <span className="bar-label sym">{c.symbol}{!c.held_now && <span className="muted small"> sold</span>}</span>
          <span className="bar-track diverging">
            <span
              className={`bar-fill ${c.gain >= 0 ? "pos" : "neg"}`}
              style={{ width: `${(Math.abs(c.gain) / max) * 50}%`, [c.gain >= 0 ? "left" : "right"]: "50%" }}
            />
          </span>
          <span className={`bar-value ${tone(c.gain)}`}>{signedMoney(c.gain)}</span>
        </Link>
      ))}
    </div>
  );
}

function AllocationBars({ rows }) {
  return (
    <div className="bars">
      {rows.map((r) => (
        <div key={r.label} className="bar-row">
          <span className="bar-label">{r.label}</span>
          <span className="bar-track">
            <span className={`bar-fill ${r.label === "Cash" ? "cash" : "alloc"}`} style={{ width: `${Math.max(r.pct, 0.5)}%` }} />
          </span>
          <span className="bar-value">
            {num(r.pct, 1)}% <span className="muted small">{money(r.value)}</span>
          </span>
        </div>
      ))}
    </div>
  );
}

const diff = (a, b) => (a == null || b == null ? null : a - b);
const pctCell = (v) => <span className={tone(v)}>{v == null ? "—" : pct(v)}</span>;

function MarketComparison({ period }) {
  const [cmp, setCmp] = useState(null);
  const [summary, setSummary] = useState(null);
  useEffect(() => {
    api.compareSummary().then(setSummary).catch(() => setSummary([]));
  }, []);
  const s = cmp?.stats;
  return (
    <>
      <h3 className="section-title">You vs the market</h3>
      <p className="muted small section-sub">Percent change from the same starting point. Click S&amp;P 500 or Nasdaq to hide or show it.</p>
      <CompareChart range={period} showTabs={false} onData={setCmp} height={320} />

      {s && (
        <div className="table-wrap">
          <table className="table compare-table">
            <thead>
              <tr>
                <th />
                <th className="r">Return</th>
                <th className="r">You − index <Help text="Your return minus this index's return over the same period. Positive means you beat it." /></th>
                <th className="r">Volatility <Help text="How much daily returns swing around, scaled to a year. Needs 20 trading days." /></th>
                <th className="r">Sharpe <Help text="Return above Treasury bills per unit of volatility. Higher is better. Needs 20 trading days." /></th>
                <th className="r">Max drawdown <Help text="The biggest fall from a high to a later low in this period." /></th>
                <th className="r">Beta <Help text="How much you tend to move when this index moves 1%. 1.0 moves with it; below 1 is calmer; above 1 is more aggressive. Needs 20 trading days." /></th>
                <th className="r">Correlation <Help text="How closely your daily moves follow this index, from -1 (opposite) to 1 (in lockstep). Needs 20 trading days." /></th>
              </tr>
            </thead>
            <tbody>
              {SERIES.map((x) => {
                const r = s[x.key];
                const vs = x.key === "you" ? null : s[`vs_${x.key}`];
                return (
                  <tr key={x.key}>
                    <td><span className="swatch" style={{ background: x.color }} /><span className="sym">{x.label}</span></td>
                    <td className="r">{pctCell(r.return_pct)}</td>
                    <td className="r">{vs ? pctCell(vs.difference_pct) : ""}</td>
                    <td className="r">{r.volatility_pct == null ? "—" : `${num(r.volatility_pct, 1)}%`}</td>
                    <td className="r">{r.sharpe == null ? "—" : num(r.sharpe)}</td>
                    <td className="r">{pctCell(r.max_drawdown_pct)}</td>
                    <td className="r">{vs ? (vs.beta == null ? "—" : num(vs.beta)) : ""}</td>
                    <td className="r">{vs ? (vs.correlation == null ? "—" : num(vs.correlation)) : ""}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <h3 className="section-title">Returns by time range</h3>
      <p className="muted small section-sub">Ranges marked * are longer than your account's history, so they start when you opened it.</p>
      {summary === null ? (
        <p className="muted small">Loading…</p>
      ) : (
        <div className="table-wrap">
          <table className="table compare-table">
            <thead>
              <tr>
                <th>Range</th>
                {SERIES.map((x) => (
                  <th key={x.key} className="r"><span className="swatch" style={{ background: x.color }} /> {x.label}</th>
                ))}
                <th className="r">You − S&amp;P 500</th>
                <th className="r">You − Nasdaq</th>
              </tr>
            </thead>
            <tbody>
              {summary.map((r) => (
                <tr key={r.range} className={r.range === period ? "current" : ""}>
                  <td className="sym">{r.range}{r.partial ? "*" : ""}</td>
                  <td className="r">{pctCell(r.you)}</td>
                  <td className="r">{pctCell(r.sp)}</td>
                  <td className="r">{pctCell(r.nq)}</td>
                  <td className="r">{pctCell(diff(r.you, r.sp))}</td>
                  <td className="r">{pctCell(diff(r.you, r.nq))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

export default function Performance() {
  const [period, setPeriod] = useState("ALL");
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [allocView, setAllocView] = useState("by_holding");

  useEffect(() => {
    let alive = true;
    setLoading(true);
    api.performance(period)
      .then((d) => alive && (setData(d), setError("")))
      .catch((e) => alive && setError(e.message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [period]);

  if (error) return <div className="empty-state"><p className="error">{error}</p></div>;
  if (!data) return <div className="splash">Crunching your numbers…</div>;

  const d = data;
  const ts = d.trade_stats;
  const young = d.trading_days < 20;
  const long = d.calendar_days > 200;
  const color = d.return_abs >= 0 ? "var(--up)" : "var(--down)";
  const periodName = d.period === "ALL" ? "since you opened your account" : d.period === "YTD" ? "this year" : `over the past ${d.period}`;

  return (
    <div className={`performance ${loading ? "is-loading" : ""}`}>
      <div className="perf-head">
        <div>
          <h1>Performance</h1>
          <div className="muted small">
            {shortDate(d.start_date)} – {shortDate(d.end_date)} · {d.trading_days} trading day{d.trading_days === 1 ? "" : "s"}
          </div>
        </div>
        <div className="range-tabs perf-tabs">
          {PERIODS.map((p) => (
            <button key={p} className={p === period ? "active" : ""} onClick={() => setPeriod(p)}>{p}</button>
          ))}
        </div>
      </div>

      {d.partial && (
        <div className="notice">
          Your account opened on {shortDate(d.account_opened)}, so this covers its whole life rather than the full {d.period}.
        </div>
      )}

      <div className="perf-hero">
        <div className="hero-price">{money(d.end_value)}</div>
        <div className={`hero-change ${tone(d.return_abs)}`}>
          {signedMoney(d.return_abs)} ({pct(d.return_pct)}) <span className="muted">{periodName}</span>
        </div>
        {d.deposits > 0 && (
          <div className="muted small">Includes {money(d.deposits)} of quarterly deposits, which don't count as gains.</div>
        )}
      </div>

      <div className="card chart-card">
        {d.series.length < 2 ? (
          <div className="chart-empty small">Your value chart starts after your first market close.</div>
        ) : (
          <SeriesChart series={d.series} dataKey="value" height={300} color={color} format={(v) => money(v)} axisFormat={compactMoney} baseline={d.start_value} long={long} />
        )}
      </div>

      <div className="kpi-grid">
        <Kpi label="Return" value={pct(d.return_pct)} valueTone={tone(d.return_pct)} sub={signedMoney(d.return_abs)} help="How much your investments gained or lost over this period. Quarterly deposits add to your account value but are left out, so this only measures how your picks did." />
        <Kpi
          label="Annualized return"
          value={d.annualized_pct == null ? "—" : pct(d.annualized_pct)}
          valueTone={tone(d.annualized_pct)}
          sub={d.annualized_pct == null ? "Needs a year of history" : "Per year, compounded"}
          help="The yearly rate that would compound to the same total return. Only shown for periods of a year or more."
        />
        <Kpi
          label="Volatility"
          value={d.volatility_pct == null ? "—" : `${num(d.volatility_pct, 1)}%`}
          sub={d.volatility_pct == null ? "Needs 20 trading days" : "Annualized"}
          help="How much your daily returns swing around, scaled to a year. The S&P 500 is typically around 15 to 20%."
        />
        <Kpi
          label="Sharpe ratio"
          value={d.sharpe == null ? "—" : num(d.sharpe)}
          sub={d.sharpe == null ? "Needs 20 trading days" : `vs ${num(d.risk_free_pct)}% T-bills`}
          help="Return earned above Treasury bills per unit of volatility. Above 1 is good, above 2 is very good."
        />
        <Kpi
          label="Sortino ratio"
          value={d.sortino == null ? "—" : num(d.sortino)}
          sub={d.sortino == null ? "Needs 20 trading days" : "Downside risk only"}
          help="Like Sharpe, but only counts drops as risk, so upside swings don't hurt the score."
        />
        <Kpi
          label="Max drawdown"
          value={pct(d.max_drawdown_pct)}
          valueTone={d.max_drawdown_pct < 0 ? "down" : ""}
          sub={d.max_drawdown_trough ? `${shortDate(d.max_drawdown_peak).replace(/, \d{4}$/, "")} → ${shortDate(d.max_drawdown_trough)}${d.max_drawdown_recovered ? ", recovered" : ""}` : "No drops yet"}
          help="The biggest fall from a high point to a later low in this period."
        />
        <Kpi label="Best day" value={d.best_day ? pct(d.best_day.pct) : "—"} valueTone={tone(d.best_day?.pct)} sub={d.best_day ? shortDate(d.best_day.d) : ""} />
        <Kpi label="Worst day" value={d.worst_day ? pct(d.worst_day.pct) : "—"} valueTone={tone(d.worst_day?.pct)} sub={d.worst_day ? shortDate(d.worst_day.d) : ""} />
        <Kpi label="Up days" value={d.positive_days_pct == null ? "—" : `${num(d.positive_days_pct, 0)}%`} sub={`of ${d.trading_days} trading days`} />
        <Kpi
          label="Below peak"
          value={pct(d.current_drawdown_pct)}
          valueTone={d.current_drawdown_pct < 0 ? "down" : ""}
          sub={d.current_drawdown_pct < -0.005 ? "From this period's high" : "At a high"}
          help="How far your account is right now below its highest value in this period."
        />
      </div>
      {young && <p className="muted small">Risk numbers like volatility and Sharpe need at least 20 trading days of history to mean anything, so they fill in as your account ages.</p>}

      {d.series.length > 2 && (
        <>
          <h3 className="section-title">Drawdown</h3>
          <p className="muted small section-sub">How far below its previous high your account was on each day.</p>
          <SeriesChart series={d.series} dataKey="drawdown_pct" height={160} color="var(--down)" format={(v) => `${num(v, 1)}%`} long={long} fillOpacity={0.3} />
        </>
      )}

      <MarketComparison period={period} />

      <div className="perf-columns">
        <section>
          <h3 className="section-title">What drove your return</h3>
          <p className="muted small section-sub">Dollars each stock added or lost {periodName}, including sales and dividends.</p>
          {d.contributions.length ? <ContributionBars items={d.contributions} /> : <p className="muted">No trades yet.</p>}
        </section>
        <section>
          <h3 className="section-title">Allocation</h3>
          <div className="seg">
            {[["by_holding", "Holdings"], ["by_sector", "Sector"], ["by_type", "Type"]].map(([k, l]) => (
              <button key={k} className={allocView === k ? "active" : ""} onClick={() => setAllocView(k)}>{l}</button>
            ))}
          </div>
          <AllocationBars rows={d.allocation[allocView]} />
        </section>
      </div>

      <h3 className="section-title">Trading activity <span className="muted small">{d.period === "ALL" ? "all time" : periodName}</span></h3>
      <div className="stats-grid trade-stats">
        <div className="stat"><span className="muted">Trades</span><span>{ts.trades} ({ts.buys} buy{ts.buys === 1 ? "" : "s"}, {ts.sells} sell{ts.sells === 1 ? "" : "s"})</span></div>
        <div className="stat"><span className="muted">Limit orders filled</span><span>{ts.limit_orders}</span></div>
        <div className="stat"><span className="muted">Bought</span><span>{money(ts.bought)}</span></div>
        <div className="stat"><span className="muted">Sold</span><span>{money(ts.sold)}</span></div>
        <div className="stat"><span className="muted">Realized gain/loss</span><span className={tone(ts.realized_pl)}>{signedMoney(ts.realized_pl)}</span></div>
        <div className="stat"><span className="muted">Dividends received</span><span>{money(ts.dividends)}</span></div>
        {ts.reinvested ? <div className="stat"><span className="muted">Dividends reinvested</span><span>{money(ts.reinvested)}</span></div> : null}
        <div className="stat"><span className="muted">Winning sales <Help text="Share of your sales that closed at a profit." /></span><span>{ts.win_rate_pct == null ? "—" : `${num(ts.win_rate_pct, 0)}%`}</span></div>
        <div className="stat"><span className="muted">Profit factor <Help text="Total won on winning sales divided by total lost on losing sales. Above 1 means your winners outweigh your losers." /></span><span>{ts.profit_factor == null ? "—" : num(ts.profit_factor)}</span></div>
        <div className="stat"><span className="muted">Average win</span><span className="up">{ts.avg_win == null ? "—" : signedMoney(ts.avg_win)}</span></div>
        <div className="stat"><span className="muted">Average loss</span><span className="down">{ts.avg_loss == null ? "—" : signedMoney(ts.avg_loss)}</span></div>
        <div className="stat"><span className="muted">Largest win</span><span className="up">{ts.largest_win == null ? "—" : signedMoney(ts.largest_win)}</span></div>
        <div className="stat"><span className="muted">Largest loss</span><span className="down">{ts.largest_loss == null ? "—" : signedMoney(ts.largest_loss)}</span></div>
      </div>

      <DividendIncome />

      {d.monthly.length > 0 && (
        <>
          <h3 className="section-title">Monthly returns</h3>
          <p className="muted small section-sub">Percent change in your account each month, since you opened it.</p>
          <MonthlyTable rows={d.monthly} />
        </>
      )}
    </div>
  );
}
