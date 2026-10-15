import { useState } from "react";
import { api } from "../api.js";
import { money, parseUtc, shares as fmtShares, whenCT } from "../format.js";
import { MarketStatusLine } from "./OpenOrders.jsx";
import useMarketStatus from "./useMarketStatus.js";

// Orders only execute during market hours. While the market is open, market orders fill instantly at
// the latest (delayed) quote; while it is closed they are queued and fill at the opening price. Limit
// orders wait until the price reaches the limit; until then a buy holds back its cost from buying
// power and a sell holds its shares.
export default function OrderPanel({ quote, position, buyingPower, onPlaced }) {
  const [side, setSide] = useState("buy");
  const [orderType, setOrderType] = useState("market");
  const [mode, setMode] = useState("shares"); // "shares" | "dollars"
  const [value, setValue] = useState("");
  const [limit, setLimit] = useState("");
  const [tif, setTif] = useState("gtc");
  const [review, setReview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const status = useMarketStatus();
  const closed = status ? !status.is_open : false;
  const opens = status ? whenCT(parseUtc(status.opens_at)) : "";

  const tradeable = quote.type === "EQUITY" || quote.type === "ETF";
  const isLimit = orderType === "limit";
  const n = parseFloat(value);
  const lim = parseFloat(limit);
  const limitOk = !isLimit || (Number.isFinite(lim) && lim > 0);
  const valid = Number.isFinite(n) && n > 0 && limitOk;
  const px = isLimit && limitOk ? lim : quote.price;
  const estShares = valid ? (mode === "shares" ? n : n / px) : 0;
  const estTotal = valid ? (mode === "shares" ? n * px : n) : 0;
  const available = position?.shares_available ?? 0;
  const marketable = isLimit && limitOk && (side === "buy" ? quote.price <= lim : quote.price >= lim);

  let problem = "";
  if (valid && side === "buy" && estTotal > buyingPower + 0.005) problem = `Not enough buying power (${money(buyingPower)}).`;
  if (valid && side === "sell" && estShares > available + 1e-6) problem = `You can sell up to ${fmtShares(available)} shares.`;

  const clear = () => {
    setValue("");
    setReview(false);
    setError("");
  };

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      const order = {
        symbol: quote.symbol,
        side,
        order_type: orderType,
        ...(mode === "shares" ? { shares: n } : { amount: n }),
        ...(isLimit ? { limit_price: lim, time_in_force: tif } : {}),
      };
      setResult(await api.trade(order));
      clear();
      setLimit("");
      onPlaced?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (!tradeable) {
    return (
      <aside className="order-panel">
        <p className="muted">
          {quote.type === "INDEX"
            ? `${quote.symbol} is an index and can't be traded directly. Try an ETF that tracks it, like SPY or QQQ.`
            : `${quote.name || quote.symbol} isn't a stock or ETF, so it can't be traded here.`}
        </p>
      </aside>
    );
  }

  const sharesText = fmtShares(Number(estShares.toFixed(6)));
  const shareWord = Number(estShares.toFixed(6)) === 1 ? "share" : "shares";
  const edit = (setter) => (e) => {
    setter(e.target.value.replace(/[^0-9.]/g, ""));
    setReview(false);
    setResult(null);
  };

  return (
    <aside className={`order-panel ${side}`}>
      <div className="order-tabs">
        {["buy", "sell"].map((s) => (
          <button key={s} className={side === s ? "active" : ""} onClick={() => { setSide(s); clear(); setResult(null); }}>
            {s === "buy" ? "Buy" : "Sell"} {quote.symbol}
          </button>
        ))}
      </div>

      <div className="order-row">
        <span>Order type</span>
        <select value={orderType} onChange={(e) => { setOrderType(e.target.value); setReview(false); setResult(null); }}>
          <option value="market">Market</option>
          <option value="limit">Limit</option>
        </select>
      </div>
      <div className="order-row">
        <span>{side === "buy" ? "Buy in" : "Sell in"}</span>
        <select value={mode} onChange={(e) => { setMode(e.target.value); clear(); }}>
          <option value="shares">Shares</option>
          <option value="dollars">Dollars</option>
        </select>
      </div>
      {isLimit && (
        <div className="order-row">
          <span>Limit price</span>
          <input className="order-input" inputMode="decimal" placeholder={quote.price.toFixed(2)} value={limit} onChange={edit(setLimit)} />
        </div>
      )}
      <div className="order-row">
        <span>{mode === "shares" ? "Shares" : "Amount"}</span>
        <input className="order-input" inputMode="decimal" placeholder={mode === "shares" ? "0" : "$0.00"} value={value} onChange={edit(setValue)} />
      </div>
      {isLimit && (
        <div className="order-row">
          <span>Expires</span>
          <select value={tif} onChange={(e) => { setTif(e.target.value); setReview(false); }}>
            <option value="gtc">Until canceled</option>
            <option value="day">End of day</option>
          </select>
        </div>
      )}
      <div className="order-row">
        <span className="accent">Market price</span>
        <span>{money(quote.price)}</span>
      </div>
      <div className="order-row total">
        <span>{mode === "shares" ? (side === "buy" ? "Estimated cost" : "Estimated credit") : "Estimated shares"}</span>
        <span>{mode === "shares" ? money(estTotal) : sharesText}</span>
      </div>

      {closed && (
        <div className="order-note">
          The market is closed, so this order will be queued. {isLimit
            ? `It starts watching the price when the market opens ${opens}.`
            : `It will fill at the opening price ${opens}.`}
        </div>
      )}
      {isLimit && marketable && valid && (
        <div className="hint small">
          {closed
            ? `The price is ${side === "buy" ? "at or below" : "at or above"} your limit now, so this will fill at the open if it still is.`
            : `The market price is already ${side === "buy" ? "at or below" : "at or above"} your limit, so this will fill right away at ${money(quote.price)}.`}
        </div>
      )}
      {problem && <div className="error">{problem}</div>}
      {error && <div className="error">{error}</div>}

      {review ? (
        <div className="review">
          <p>
            {isLimit && !marketable ? (
              <>
                You are placing a <b>limit order</b> to {side} {sharesText} {shareWord} of {quote.symbol} at{" "}
                <b>{money(lim)}</b> or {side === "buy" ? "less" : "more"}, {tif === "day" ? "good for today" : "good till canceled"}.{" "}
                {side === "buy" ? `${money(estTotal)} of buying power will be held until it fills or is canceled.` : ""}
              </>
            ) : closed && !isLimit ? (
              <>
                You are queueing a market order to <b>{side}</b> {mode === "dollars" ? <>about {sharesText} {shareWord}</> : <>{sharesText} {shareWord}</>} of{" "}
                {quote.symbol} for about <b>{money(estTotal)}</b>. It will fill at the opening price {opens}, which may differ
                from today's price.{side === "buy" ? ` ${money(estTotal)} of buying power will be held until then.` : ""}
              </>
            ) : closed ? (
              <>
                You are queueing a <b>limit order</b> to {side} {sharesText} {shareWord} of {quote.symbol} at <b>{money(lim)}</b> or{" "}
                {side === "buy" ? "less" : "more"}. It will fill at the open {opens} if the price is still there.
              </>
            ) : (
              <>
                You are placing a market order to <b>{side}</b> {sharesText} {shareWord} of {quote.symbol} for about <b>{money(estTotal)}</b>.
              </>
            )}
          </p>
          <button className="btn btn-primary btn-block" disabled={busy} onClick={submit}>{busy ? "Placing…" : closed ? `Queue ${side}` : `Confirm ${side}`}</button>
          <button className="btn btn-ghost btn-block" onClick={() => setReview(false)}>Edit</button>
        </div>
      ) : (
        <button className="btn btn-primary btn-block" disabled={!valid || !!problem} onClick={() => setReview(true)}>Review order</button>
      )}

      {result?.trade && (
        <div className="filled">
          {result.trade.side === "buy" ? "Bought" : "Sold"} {fmtShares(result.trade.shares)} {result.trade.symbol} at {money(result.trade.price)} ({money(result.trade.total)}).
        </div>
      )}
      {result?.order && result.order.order_type === "market" && (
        <div className="filled">
          Order queued: {result.order.side}{" "}
          {result.order.amount != null ? `${money(result.order.amount)} of` : fmtShares(result.order.shares)} {result.order.symbol} at the
          opening price {opens}. You can cancel it under Queued orders until then.
        </div>
      )}
      {result?.order && result.order.order_type === "limit" && (
        <div className="filled">
          Limit order placed: {result.order.side} {fmtShares(result.order.shares)} {result.order.symbol} at {money(result.order.limit_price)}.
          {closed ? " It starts watching the price when the market opens." : " It will fill when the price gets there."}
        </div>
      )}

      {!closed && <MarketStatusLine status={status} />}
      <div className="order-foot muted small">
        {side === "buy" ? `${money(buyingPower)} buying power available` : `${fmtShares(available)} shares available`}
        {side === "sell" && available > 0 && (
          <button className="link small" onClick={() => { setMode("shares"); setValue(String(available)); setReview(false); }}>Sell all</button>
        )}
      </div>
    </aside>
  );
}
