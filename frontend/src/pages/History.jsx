import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { dateTime, money, num, shares, signedMoney, tone, tradeLabel } from "../format.js";

const fullDate = (d) =>
  new Date(`${d}T12:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });

export default function History() {
  const [trades, setTrades] = useState(null);
  const [actions, setActions] = useState([]);
  const [deposits, setDeposits] = useState([]);
  useEffect(() => {
    api.trades().then(setTrades).catch(() => setTrades([]));
    api.corporateActions().then(setActions).catch(() => {});
    api.deposits().then((d) => setDeposits(d.history)).catch(() => {});
  }, []);

  if (trades === null) return <div className="splash">Loading…</div>;
  const realized = trades.reduce((s, t) => s + (t.realized_pl || 0), 0);

  return (
    <div className="narrow">
      <h1>Trade history</h1>
      <p className="muted">
        {trades.length} trade{trades.length === 1 ? "" : "s"} · Realized gain/loss{" "}
        <span className={tone(realized)}>{signedMoney(realized)}</span>
      </p>
      {trades.length === 0 ? (
        <div className="card muted">No trades yet.</div>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Date</th><th>Symbol</th><th>Order</th>
                <th className="r">Shares</th><th className="r">Price</th><th className="r">Total</th><th className="r">Realized</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => (
                <tr key={t.id}>
                  <td>{dateTime(t.executed_at)}</td>
                  <td><Link to={`/stock/${t.symbol}`} className="sym">{t.symbol}</Link></td>
                  <td className={t.side === "buy" ? "side-buy" : "side-sell"}>{tradeLabel(t)}</td>
                  <td className="r">{shares(t.shares)}</td>
                  <td className="r">{money(t.price)}</td>
                  <td className="r">{money(t.total)}</td>
                  <td className={`r ${tone(t.realized_pl)}`}>{t.realized_pl == null ? "—" : signedMoney(t.realized_pl)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {deposits.length > 0 && (
        <>
          <h3 className="section-title">Quarterly deposits</h3>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>Paid</th><th>Based on close of</th><th className="r">Account value</th><th className="r">Rate</th><th className="r">Deposit</th></tr>
              </thead>
              <tbody>
                {deposits.map((x) => (
                  <tr key={x.pay_date}>
                    <td>{fullDate(x.pay_date)}</td>
                    <td>{fullDate(x.basis_date)}</td>
                    <td className="r">{money(x.basis_value)}</td>
                    <td className="r">{num(x.rate * 100)}%</td>
                    <td className="r">+{money(x.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {actions.length > 0 && (
        <>
          <h3 className="section-title">Dividends and splits</h3>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>Date</th><th>Symbol</th><th>Event</th><th className="r">Shares held</th><th className="r">Amount</th></tr>
              </thead>
              <tbody>
                {actions.map((a) => (
                  <tr key={a.id}>
                    <td>{new Date(`${a.ex_date}T12:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}</td>
                    <td><Link to={`/stock/${a.symbol}`} className="sym">{a.symbol}</Link></td>
                    <td>{a.kind === "dividend" ? `Dividend, ${money(a.per_share)} per share` : `${num(a.ratio, 4)}-for-1 split`}</td>
                    <td className="r">{shares(a.shares)}</td>
                    <td className="r">{a.kind === "dividend" ? <span className="up">+{money(a.amount)}</span> : `→ ${shares(a.shares * a.ratio)} shares`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
