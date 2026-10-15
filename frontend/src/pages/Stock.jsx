import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api.js";
import { useUser } from "../App.jsx";
import OpenOrders from "../components/OpenOrders.jsx";
import OrderPanel from "../components/OrderPanel.jsx";
import PriceChart from "../components/PriceChart.jsx";
import useMarketStatus from "../components/useMarketStatus.js";
import { big, clockTime, dateTime, money, num, parseUtc, pct, shares, signedMoney, tone, tradeLabel } from "../format.js";

function Stat({ label, value }) {
  return (
    <div className="stat">
      <span className="muted">{label}</span>
      <span>{value}</span>
    </div>
  );
}

export default function Stock() {
  const { symbol: raw } = useParams();
  const symbol = raw.toUpperCase();
  const { user, refreshUser } = useUser();
  const [quote, setQuote] = useState(null);
  const [error, setError] = useState("");
  const [position, setPosition] = useState(null);
  const [trades, setTrades] = useState([]);
  const [openOrders, setOpenOrders] = useState([]);
  const [watching, setWatching] = useState(false);
  const [showMore, setShowMore] = useState(false);
  const [range, setRange] = useState("1D");
  const [readout, setReadout] = useState(null);
  const marketStatus = useMarketStatus();

  const loadMine = useCallback(() => {
    api.portfolio().then((p) => setPosition(p.holdings.find((h) => h.symbol === symbol) || null)).catch(() => {});
    api.trades(symbol).then(setTrades).catch(() => {});
    api.orders(symbol).then(setOpenOrders).catch(() => {});
    api.watchlist().then((w) => setWatching(w.some((x) => x.symbol === symbol))).catch(() => {});
  }, [symbol]);

  useEffect(() => {
    setRange("1D");
    setQuote(null);
    setError("");
    const load = () => api.quote(symbol).then(setQuote).catch((e) => setError(e.message));
    load();
    loadMine();
    const id = setInterval(load, 120_000); // prices refresh every 2 minutes
    return () => clearInterval(id);
  }, [symbol, loadMine]);

  if (error) return <div className="empty-state"><h2>{symbol}</h2><p className="muted">{error}</p></div>;
  if (!quote) return <div className="splash">Loading {symbol}…</div>;

  // Under the price: today's change on 1D, otherwise the selected range's return (or the hovered point's).
  const hovering = readout?.hover != null;
  const longRange = range !== "1D";
  let lineChange = quote.change, linePct = quote.change_pct, lineLabel = "Today";
  if (hovering || (longRange && readout && !readout.loading)) {
    const at = hovering ? readout.hover : readout.last;
    lineChange = at != null && readout.base ? at - readout.base : null;
    linePct = lineChange != null ? (lineChange / readout.base) * 100 : null;
    lineLabel = hovering ? `at ${money(readout.hover)}` : `Past ${range === "ALL" ? "max" : range}`;
  } else if (longRange) {
    lineChange = linePct = null;
    lineLabel = `Past ${range === "ALL" ? "max" : range}`;
  }
  const todayText = `${signedMoney(quote.change)} (${pct(quote.change_pct)})`;

  const toggleWatch = async () => {
    await (watching ? api.unwatch(symbol) : api.watch(symbol));
    setWatching(!watching);
  };

  return (
    <div className="stock-layout">
      <section>
        <div className="stock-head">
          <div>
            <div className="muted small">{quote.symbol} · {quote.exchange} · {quote.currency}</div>
            <div className="stock-title">
              <h1>{quote.name}</h1>
              {longRange && (
                <span className={`today-chip ${tone(quote.change)}`}>
                  {todayText} <span className="muted">Today</span>
                </span>
              )}
            </div>
          </div>
          <button className={`btn btn-ghost ${watching ? "on" : ""}`} onClick={toggleWatch}>
            {watching ? "✓ On watchlist" : "+ Watchlist"}
          </button>
        </div>
        <div className="hero-price">{money(quote.price)}</div>
        <div className={`hero-change stock-change ${tone(lineChange)}`}>
          {lineChange == null ? "—" : `${signedMoney(lineChange)} (${pct(linePct)})`} <span className="muted">{lineLabel}</span>
        </div>
        <div className="muted small delayed">
          {marketStatus && !marketStatus.is_open
            ? "Market closed · last regular-hours price"
            : `Delayed quote · updated ${clockTime(parseUtc(quote.as_of))}`}
        </div>

        <PriceChart symbol={symbol} previousClose={quote.previous_close} range={range} onRangeChange={setRange} onReadout={setReadout} />

        {position && (
          <div className="card position-card">
            <h3>Your position</h3>
            <div className="position-grid">
              <Stat label="Shares" value={shares(position.shares)} />
              <Stat label="Market value" value={money(position.market_value)} />
              <Stat label="Average cost" value={money(position.avg_cost)} />
              <Stat label="Total return" value={<span className={tone(position.gain)}>{signedMoney(position.gain)} ({pct(position.gain_pct)})</span>} />
              <Stat label="Portfolio diversity" value={`${num(position.weight_pct)}%`} />
              <Stat label="Today's change" value={<span className={tone(position.change_pct)}>{pct(position.change_pct)}</span>} />
            </div>
          </div>
        )}

        <OpenOrders orders={openOrders} showSymbol={false} onChange={() => { refreshUser(); loadMine(); }} />

        <h3 className="section-title">Key statistics</h3>
        <div className="stats-grid">
          <Stat label="Previous close" value={money(quote.previous_close)} />
          <Stat label="Open" value={money(quote.open)} />
          <Stat label="Day's range" value={quote.day_low ? `${num(quote.day_low)} – ${num(quote.day_high)}` : "—"} />
          <Stat label="52-week range" value={quote.year_low ? `${num(quote.year_low)} – ${num(quote.year_high)}` : "—"} />
          <Stat label="Volume" value={big(quote.volume)} />
          <Stat label="Avg. volume" value={big(quote.avg_volume)} />
          {quote.type === "ETF" ? (
            <>
              <Stat label="Net assets" value={big(quote.net_assets)} />
              <Stat label="Expense ratio" value={quote.expense_ratio != null ? `${num(quote.expense_ratio)}%` : "—"} />
            </>
          ) : (
            <Stat label="Market cap" value={big(quote.market_cap)} />
          )}
          <Stat label="P/E ratio (TTM)" value={num(quote.pe_ratio)} />
          <Stat label="Dividend yield" value={quote.dividend_yield != null ? `${num(quote.dividend_yield)}%` : "—"} />
          <Stat label="Beta" value={num(quote.beta)} />
        </div>

        {quote.description && (
          <>
            <h3 className="section-title">About</h3>
            {(quote.sector || quote.industry) && <div className="muted small">{[quote.sector, quote.industry].filter(Boolean).join(" · ")}</div>}
            <p className={`about ${showMore ? "" : "clamped"}`}>{quote.description}</p>
            <button className="link" onClick={() => setShowMore(!showMore)}>{showMore ? "Show less" : "Show more"}</button>
          </>
        )}

        {trades.length > 0 && (
          <>
            <h3 className="section-title">Your {symbol} trades</h3>
            <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Date</th><th>Order</th><th className="r">Shares</th><th className="r">Price</th><th className="r">Total</th></tr></thead>
              <tbody>
                {trades.map((t) => (
                  <tr key={t.id}>
                    <td>{dateTime(t.executed_at)}</td>
                    <td className={t.side === "buy" ? "side-buy" : "side-sell"}>{tradeLabel(t)}</td>
                    <td className="r">{shares(t.shares)}</td>
                    <td className="r">{money(t.price)}</td>
                    <td className="r">{money(t.total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          </>
        )}
      </section>

      <OrderPanel
        quote={quote}
        position={position}
        buyingPower={user.buying_power}
        onPlaced={() => {
          refreshUser();
          loadMine();
        }}
      />
    </div>
  );
}
