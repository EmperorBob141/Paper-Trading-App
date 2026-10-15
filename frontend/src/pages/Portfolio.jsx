import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api.js";
import { useUser } from "../App.jsx";
import CompareChart from "../components/CompareChart.jsx";
import DepositCard from "../components/DepositCard.jsx";
import OpenOrders from "../components/OpenOrders.jsx";
import { money, num, parseUtc, pct, shares, signedMoney, tone, TZ } from "../format.js";

function Summary({ label, value, sub, subTone }) {
  return (
    <div className="card summary">
      <div className="muted small">{label}</div>
      <div className="summary-value">{value}</div>
      {sub && <div className={`small ${subTone || ""}`}>{sub}</div>}
    </div>
  );
}

const fullDate = (iso) => parseUtc(iso).toLocaleDateString("en-US", { timeZone: TZ, month: "short", day: "numeric", year: "numeric" });

/** Small box showing how a watchlist stock has moved since it was added. */
function WatchInfo({ q, x, y, onClose }) {
  const days = Math.floor((Date.now() - new Date(`${q.added_at.replace("Z", "")}Z`).getTime()) / 86_400_000);
  return (
    <div className="watch-info" style={{ left: x, top: y }} onClick={(e) => e.stopPropagation()} role="dialog" aria-label={`${q.symbol} since added`}>
      <div className="watch-info-head">
        <div>
          <div className="sym">{q.symbol}</div>
          <div className="muted small ellipsis">{q.name}</div>
        </div>
        <button className="watch-info-close" aria-label="Close" onClick={onClose}>×</button>
      </div>
      <div className="muted small">Since added on {fullDate(q.added_at)} ({days === 0 ? "today" : days === 1 ? "1 day ago" : `${days} days ago`})</div>
      <div className={`watch-info-change ${tone(q.since_added)}`}>
        {q.since_added == null ? "—" : `${signedMoney(q.since_added)} (${pct(q.since_added_pct)})`}
      </div>
      <div className="stat"><span className="muted">Price when added</span><span>{money(q.added_price)}</span></div>
      <div className="stat"><span className="muted">Price now</span><span>{money(q.price)}</span></div>
      <div className="muted small watch-info-foot">Per share, before any dividends.</div>
    </div>
  );
}

function Watchlist() {
  const [items, setItems] = useState(null);
  const [menu, setMenu] = useState(null); // { symbol, x, y } while the right-click menu is open
  const [info, setInfo] = useState(null); // { symbol, x, y } while the "More info" box is open
  const load = useCallback(() => api.watchlist().then(setItems).catch(() => setItems([])), []);
  useEffect(() => {
    load();
    const id = setInterval(load, 120_000);
    return () => clearInterval(id);
  }, [load]);

  useEffect(() => {
    if (!menu && !info) return;
    const close = () => {
      setMenu(null);
      setInfo(null);
    };
    const onKey = (e) => e.key === "Escape" && close();
    window.addEventListener("click", close);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("click", close);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
      window.removeEventListener("keydown", onKey);
    };
  }, [menu, info]);

  const openMenu = (e, symbol) => {
    e.preventDefault();
    const x = Math.min(e.clientX, window.innerWidth - 170);
    const y = Math.min(e.clientY, window.innerHeight - 90);
    setInfo(null);
    setMenu({ symbol, x, y });
  };

  const showInfo = () => {
    const x = Math.min(menu.x, window.innerWidth - 280);
    const y = Math.min(menu.y, window.innerHeight - 230);
    setMenu(null);
    setInfo({ symbol: menu.symbol, x: Math.max(8, x), y: Math.max(8, y) });
  };
  const infoItem = info && items?.find((q) => q.symbol === info.symbol);

  const remove = async (symbol) => {
    setMenu(null);
    setItems((list) => list.filter((q) => q.symbol !== symbol));
    await api.unwatch(symbol).catch(() => {});
    load();
  };

  return (
    <aside className="card side-list">
      <h3>Watchlist</h3>
      {items === null ? (
        <div className="muted small">Loading…</div>
      ) : items.length === 0 ? (
        <div className="muted small">Add stocks with “+ Watchlist” on any stock page.</div>
      ) : (
        items.map((q) => (
          <Link key={q.symbol} to={`/stock/${q.symbol}`} className="side-row" onContextMenu={(e) => openMenu(e, q.symbol)}>
            <div>
              <div className="sym">{q.symbol}</div>
              <div className="muted small ellipsis">{q.name}</div>
            </div>
            <div className="r">
              <div>{money(q.price)}</div>
              <div className={`pill ${tone(q.change_pct)}`}>{pct(q.change_pct)}</div>
            </div>
          </Link>
        ))
      )}
      {menu && (
        <div className="ctx-menu" style={{ left: menu.x, top: menu.y }} role="menu" onClick={(e) => e.stopPropagation()}>
          <div className="ctx-title">{menu.symbol}</div>
          <button role="menuitem" autoFocus onClick={showInfo}>More info</button>
          <button role="menuitem" onClick={() => remove(menu.symbol)}>Delete</button>
        </div>
      )}
      {infoItem && <WatchInfo q={infoItem} x={info.x} y={info.y} onClose={() => setInfo(null)} />}
    </aside>
  );
}

// Holdings sort: click Weight or Total return to sort high to low, again for low to high, a third
// time to go back to A to Z. The choice is remembered in this browser.
const SORT_KEY = "kjp.holdingsSort";
const SORTS = { weight: (h) => h.weight_pct, gain: (h) => h.gain };

function loadSort() {
  try {
    const s = JSON.parse(localStorage.getItem(SORT_KEY));
    if (s && SORTS[s.key] && (s.dir === "desc" || s.dir === "asc")) return s;
  } catch {
    /* no saved sort */
  }
  return null;
}

function sortHoldings(holdings, sort) {
  if (!sort) return holdings; // the server sends them A to Z
  const val = SORTS[sort.key];
  const sign = sort.dir === "desc" ? -1 : 1;
  return [...holdings].sort((a, b) => sign * (val(a) - val(b)) || a.symbol.localeCompare(b.symbol));
}

function SortHeader({ label, col, sort, onSort }) {
  const active = sort?.key === col;
  const arrow = active ? (sort.dir === "desc" ? "↓" : "↑") : "↕";
  return (
    <th className="r" aria-sort={active ? (sort.dir === "desc" ? "descending" : "ascending") : "none"}>
      <button className={`sort-btn ${active ? "on" : ""}`} onClick={() => onSort(col)} title={`Sort by ${label.toLowerCase()}`}>
        {label} <span className="sort-arrow">{arrow}</span>
      </button>
    </th>
  );
}

export default function Portfolio() {
  const [p, setP] = useState(null);
  const [openOrders, setOpenOrders] = useState([]);
  const [error, setError] = useState("");
  const navigate = useNavigate();
  const { refreshUser } = useUser();
  const [sort, setSort] = useState(loadSort);

  const onSort = (col) => {
    const next = sort?.key !== col ? { key: col, dir: "desc" } : sort.dir === "desc" ? { key: col, dir: "asc" } : null;
    setSort(next);
    try {
      if (next) localStorage.setItem(SORT_KEY, JSON.stringify(next));
      else localStorage.removeItem(SORT_KEY);
    } catch {
      /* storage unavailable; sorting still works for this visit */
    }
  };

  const load = useCallback(() => {
    api.portfolio().then(setP).catch((e) => setError(e.message));
    api.orders().then(setOpenOrders).catch(() => {});
    refreshUser(); // limit orders can fill in the background
  }, [refreshUser]);

  useEffect(() => {
    load();
    const id = setInterval(load, 120_000); // prices refresh every 2 minutes
    return () => clearInterval(id);
  }, [load]);

  if (error) return <div className="empty-state"><p className="error">{error}</p></div>;
  if (!p) return <div className="splash">Loading portfolio…</div>;

  return (
    <div className="portfolio-layout">
      <section>
        <div className="muted">Total portfolio value</div>
        <div className="hero-price">{money(p.total_value)}</div>
        <div className={`hero-change ${tone(p.day_change)}`}>
          {signedMoney(p.day_change)} ({pct(p.day_change_pct)}) <span className="muted">Today</span>
        </div>

        <div className="summary-grid">
          <Summary label="All-time return" value={<span className={tone(p.total_gain)}>{signedMoney(p.total_gain)}</span>} sub={pct(p.total_gain_pct)} subTone={tone(p.total_gain)} />
          <Summary label="Invested" value={money(p.invested)} sub={`${num(p.total_value ? (p.invested / p.total_value) * 100 : 0)}% of portfolio`} />
          <Summary
            label="Buying power"
            value={money(p.buying_power)}
            sub={p.reserved_cash > 0 ? `${money(p.reserved_cash)} held for orders` : `${num(p.total_value ? (p.cash / p.total_value) * 100 : 0)}% cash`}
          />
          <Summary
            label="Starting balance"
            value={money(p.starting_cash)}
            sub={p.deposits > 0 ? `+${money(p.deposits)} in deposits` : null}
          />
        </div>

        <div className="card compare-card">
          <div className="compare-card-head">
            <h3>You vs the market</h3>
            <Link to="/performance" className="link small">Detailed stats →</Link>
          </div>
          <CompareChart />
        </div>

        <h3 className="section-title">Holdings</h3>
        {p.holdings.length === 0 ? (
          <div className="card empty-holdings">
            <p>You don't own anything yet.</p>
            <p className="muted small">Search for a stock or ETF above, or start with one of these:</p>
            <div className="chips">
              {["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "VOO"].map((s) => (
                <button key={s} className="chip" onClick={() => navigate(`/stock/${s}`)}>{s}</button>
              ))}
            </div>
          </div>
        ) : (
          <div className="table-wrap">
            <table className="table holdings">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th className="r">Shares</th>
                  <th className="r">Price</th>
                  <th className="r">Today</th>
                  <th className="r">Avg cost</th>
                  <th className="r">Market value</th>
                  <SortHeader label="Total return" col="gain" sort={sort} onSort={onSort} />
                  <SortHeader label="Weight" col="weight" sort={sort} onSort={onSort} />
                </tr>
              </thead>
              <tbody>
                {sortHoldings(p.holdings, sort).map((h) => (
                  <tr key={h.symbol} onClick={() => navigate(`/stock/${h.symbol}`)} className="clickable">
                    <td>
                      <div className="sym">{h.symbol}</div>
                      <div className="muted small ellipsis">{h.name}</div>
                    </td>
                    <td className="r">{shares(h.shares)}</td>
                    <td className="r">{money(h.price)}</td>
                    <td className={`r ${tone(h.change_pct)}`}>{pct(h.change_pct)}</td>
                    <td className="r">{money(h.avg_cost)}</td>
                    <td className="r">{money(h.market_value)}</td>
                    <td className={`r ${tone(h.gain)}`}>
                      {signedMoney(h.gain)}
                      <div className="small">{pct(h.gain_pct)}</div>
                    </td>
                    <td className="r">{num(h.weight_pct)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <div className="side-column">
        <DepositCard onPaid={load} />
        <Watchlist />
        <OpenOrders orders={openOrders} onChange={load} variant="card" />
      </div>
    </div>
  );
}
