import { Link } from "react-router-dom";
import { api } from "../api.js";
import { dateTime, money, parseUtc, shares, TZ, whenCT } from "../format.js";
import useMarketStatus from "./useMarketStatus.js";

const plural = (n) => `${shares(n)} share${n === 1 ? "" : "s"}`;

/** Dollars held (buys) or roughly involved (sells) by an open order. */
export const orderTotal = (o) =>
  o.order_type === "limit" ? o.shares * o.limit_price : o.amount ?? o.shares * o.est_price;

const kind = (o) => `${o.order_type === "market" ? "Market" : "Limit"} ${o.side}`;

function expiry(o) {
  if (o.order_type === "market") return "Fills at the open";
  if (!o.expires_at) return "Until canceled";
  return `End of day ${parseUtc(o.expires_at).toLocaleDateString("en-US", { timeZone: TZ, month: "short", day: "numeric" })}`;
}

function size(o) {
  if (o.amount != null) return `${money(o.amount)} (about ${plural(o.shares)})`;
  return plural(o.shares);
}

export function MarketStatusLine({ status }) {
  if (!status) return null;
  return (
    <div className="market-status small">
      <span className={`dot ${status.is_open ? "on" : ""}`} />
      {status.is_open
        ? `Market open · closes ${whenCT(parseUtc(status.closes_at))}`
        : `Market closed · opens ${whenCT(parseUtc(status.opens_at))}`}
    </div>
  );
}

/** Queued orders with a cancel button. "table" for the stock page, "card" for the portfolio sidebar. */
export default function OpenOrders({ orders, onChange, showSymbol = true, variant = "table" }) {
  const status = useMarketStatus();
  const cancel = async (id) => {
    await api.cancelOrder(id).catch(() => {});
    onChange?.();
  };

  if (variant === "card") {
    return (
      <aside className="card side-list queued">
        <h3>Queued orders</h3>
        <div className="queued-status"><MarketStatusLine status={status} /></div>
        {!orders?.length ? (
          <div className="muted small">No queued orders. Orders placed while the market is closed, and limit orders, wait here.</div>
        ) : (
          orders.map((o) => (
            <div key={o.id} className="queued-row">
              <div className="queued-top">
                <Link to={`/stock/${o.symbol}`} className="sym">{o.symbol}</Link>
                <span className={o.side === "buy" ? "side-buy" : "side-sell"}>{kind(o)}</span>
                <button className="link small" onClick={() => cancel(o.id)}>Cancel</button>
              </div>
              <div className="muted small">
                {size(o)}
                {o.order_type === "limit" ? ` at ${money(o.limit_price)}` : o.amount == null ? ` · about ${money(orderTotal(o))}` : ""}
              </div>
              <div className="muted small">{expiry(o)}</div>
            </div>
          ))
        )}
      </aside>
    );
  }

  if (!orders?.length) return null;
  return (
    <>
      <h3 className="section-title">Queued orders</h3>
      <MarketStatusLine status={status} />
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              {showSymbol && <th>Symbol</th>}
              <th>Order</th>
              <th className="r">Shares</th>
              <th className="r">Price</th>
              <th className="r">Est. total</th>
              <th>Expires</th>
              <th>Placed</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {orders.map((o) => (
              <tr key={o.id}>
                {showSymbol && <td><Link to={`/stock/${o.symbol}`} className="sym">{o.symbol}</Link></td>}
                <td className={o.side === "buy" ? "side-buy" : "side-sell"}>{kind(o)}</td>
                <td className="r">{o.amount != null ? `≈${shares(o.shares)}` : shares(o.shares)}</td>
                <td className="r">{o.order_type === "limit" ? money(o.limit_price) : "At the open"}</td>
                <td className="r">{money(orderTotal(o))}</td>
                <td>{expiry(o)}</td>
                <td className="muted">{dateTime(o.created_at)}</td>
                <td className="r"><button className="link" onClick={() => cancel(o.id)}>Cancel</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
