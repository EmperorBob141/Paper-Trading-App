import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api.js";
import { money, num, shares } from "../format.js";
import Help from "./Help.jsx";

const monthName = (ym, long) =>
  new Date(`${ym}-15T12:00:00`).toLocaleDateString("en-US", long ? { month: "long", year: "numeric" } : { month: "short" });
const shortDate = (d) => new Date(`${d}T12:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });

/** Group months into years once there are too many bars to read. */
function bars(byMonth) {
  if (byMonth.length <= 36) return byMonth.map((m) => ({ key: m.month, label: monthName(m.month), full: monthName(m.month, true), amount: m.amount }));
  const years = {};
  byMonth.forEach((m) => (years[m.month.slice(0, 4)] = (years[m.month.slice(0, 4)] || 0) + m.amount));
  return Object.entries(years).map(([y, amount]) => ({ key: y, label: y, full: y, amount }));
}

function Tile({ label, value, sub, help, valueClass }) {
  return (
    <div className="kpi">
      <div className="kpi-label">{label}{help && <Help text={help} />}</div>
      <div className={`kpi-value ${valueClass || ""}`}>{value}</div>
      {sub && <div className="kpi-sub muted">{sub}</div>}
    </div>
  );
}

/** Lifetime dividend income on the Performance page (independent of the selected period). */
export default function DividendIncome() {
  const [d, setD] = useState(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    api.dividends().then(setD).catch(() => setD(null));
  }, []);
  if (!d) return null;

  const chooseReinvest = async (reinvest) => {
    if (reinvest === d.reinvest) return;
    setSaving(true);
    try {
      await api.settings({ reinvest_dividends: reinvest });
      setD({ ...d, reinvest });
    } finally {
      setSaving(false);
    }
  };

  const data = bars(d.by_month);
  const yearly = d.by_month.length > 36;
  const max = Math.max(...d.by_symbol.map((s) => s.amount), 1);

  return (
    <section className="dividends">
      <h3 className="section-title">Dividend income <span className="muted small">all time</span></h3>
      <div className="dividend-head">
        <p className="muted small section-sub">
          Cash your stocks and ETFs have paid you since you opened your account. It counts toward your returns.{" "}
          {d.reinvest
            ? "Each dividend is reinvested in the stock that paid it, at that day's closing price."
            : "Each dividend is added to your cash on its ex-dividend date."}{" "}
          Your choice applies to dividends from now on.
        </p>
        <div className="payout-choice">
          <span className="muted small">Receive dividends as</span>
          <div className="segmented" role="radiogroup" aria-label="Receive dividends as">
            {[[false, "Cash"], [true, "Reinvest"]].map(([value, label]) => (
              <button key={label} type="button" role="radio" aria-checked={d.reinvest === value}
                className={d.reinvest === value ? "active" : ""} disabled={saving} onClick={() => chooseReinvest(value)}>
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="kpi-grid four">
        <Tile label="Lifetime dividends" value={d.total ? `+${money(d.total)}` : money(0)} valueClass={d.total ? "up" : ""}
          sub={`${d.payments} payment${d.payments === 1 ? "" : "s"}${d.reinvested_total ? `, ${money(d.reinvested_total)} reinvested` : ""}`} />
        <Tile label="Last 12 months" value={money(d.last_12m)} />
        <Tile label="Monthly average" value={money(d.total / Math.max(d.by_month.length, 1))} sub={`over ${d.by_month.length} month${d.by_month.length === 1 ? "" : "s"}`} />
        <Tile
          label="Expected next 12 months"
          value={money(d.projected_12m)}
          help="An estimate: what the shares you hold now would pay over a year if each stock pays the same dividends per share as it did in the last 12 months."
        />
      </div>

      {d.payments === 0 ? (
        <div className="card muted small dividends-empty">
          No dividends yet. When a stock or ETF you hold pays one, the cash shows up here and in your History.
        </div>
      ) : (
        <>
          <div className="card chart-card dividend-chart" role="img" aria-label={`Dividend income by ${yearly ? "year" : "month"}`}>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={data} margin={{ top: 12, right: 12, bottom: 0, left: 0 }} barCategoryGap={2}>
                <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="2 4" />
                <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: "var(--text-muted)", fontSize: 12 }} interval="preserveStartEnd" minTickGap={8} />
                <YAxis tickLine={false} axisLine={false} width={56} tick={{ fill: "var(--text-muted)", fontSize: 12 }} tickFormatter={(v) => `$${num(v, 0)}`} allowDecimals={false} />
                <Tooltip
                  cursor={{ fill: "var(--surface-2)" }}
                  content={({ active, payload }) =>
                    active && payload?.length ? (
                      <div className="chart-tip">
                        <div className="muted small">{payload[0].payload.full}</div>
                        <div>{money(payload[0].payload.amount)}</div>
                      </div>
                    ) : null
                  }
                />
                <Bar dataKey="amount" fill="var(--up)" radius={[4, 4, 0, 0]} maxBarSize={28} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="perf-columns">
            <section>
              <h4 className="sub-title">By stock</h4>
              <div className="bars">
                {d.by_symbol.map((s) => (
                  <Link to={`/stock/${s.symbol}`} key={s.symbol} className="bar-row">
                    <span className="bar-label sym">{s.symbol}{!s.held_now && <span className="muted small"> sold</span>}</span>
                    <span className="bar-track">
                      <span className="bar-fill pos income" style={{ width: `${Math.max((s.amount / max) * 100, 1)}%` }} />
                    </span>
                    <span className="bar-value">
                      {money(s.amount)} <span className="muted small">{s.payments}×</span>
                    </span>
                  </Link>
                ))}
              </div>
            </section>
            <section>
              <h4 className="sub-title">Recent payments</h4>
              <div className="table-wrap">
                <table className="table compact">
                  <tbody>
                    {d.recent.map((r) => (
                      <tr key={`${r.symbol}-${r.ex_date}`}>
                        <td>
                          <Link to={`/stock/${r.symbol}`} className="sym">{r.symbol}</Link>
                          <div className="muted small">{shortDate(r.ex_date)}</div>
                        </td>
                        <td className="muted small pay-detail">
                          <div>{money(r.per_share)} × {shares(r.shares)} sh</div>
                          {r.reinvested_shares ? <div>Bought {r.reinvested_shares.toFixed(4)} sh at {money(r.reinvested_price)}</div> : null}
                        </td>
                        <td className="r up">+{money(r.amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </div>
        </>
      )}
    </section>
  );
}
