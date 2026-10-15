import { useEffect, useRef, useState } from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import { api } from "../api.js";
import { useUser } from "../App.jsx";
import { money, num, pct, tone } from "../format.js";

const INDEX_NAMES = { "^GSPC": "S&P 500", "^IXIC": "Nasdaq", "BTC-USD": "Bitcoin" };

function SearchBox() {
  const [q, setQ] = useState("");
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const navigate = useNavigate();
  const box = useRef(null);

  useEffect(() => {
    if (!q.trim()) return setResults([]);
    const id = setTimeout(() => {
      api.search(q).then((r) => {
        setResults(r);
        setActive(0);
      }).catch(() => setResults([]));
    }, 250);
    return () => clearTimeout(id);
  }, [q]);

  useEffect(() => {
    const close = (e) => box.current && !box.current.contains(e.target) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const go = (symbol) => {
    navigate(`/stock/${symbol}`);
    setQ("");
    setOpen(false);
  };

  const onKey = (e) => {
    if (e.key === "ArrowDown") setActive((a) => Math.min(a + 1, results.length - 1));
    else if (e.key === "ArrowUp") setActive((a) => Math.max(a - 1, 0));
    else if (e.key === "Enter") {
      if (results[active]) go(results[active].symbol);
      else if (q.trim()) go(q.trim().toUpperCase());
    } else if (e.key === "Escape") setOpen(false);
  };

  return (
    <div className="search" ref={box}>
      <svg viewBox="0 0 24 24" className="search-icon" aria-hidden="true">
        <circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" strokeWidth="2" />
        <path d="M20 20l-4-4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      </svg>
      <input
        placeholder="Search stocks and ETFs"
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKey}
      />
      {open && results.length > 0 && (
        <ul className="search-results">
          {results.map((r, i) => (
            <li key={r.symbol} className={i === active ? "active" : ""} onMouseEnter={() => setActive(i)} onMouseDown={() => go(r.symbol)}>
              <span className="sym">{r.symbol}</span>
              <span className="name">{r.name}</span>
              <span className="tag">{r.type === "ETF" ? "ETF" : r.exchange}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function IndexStrip() {
  const [indices, setIndices] = useState([]);
  useEffect(() => {
    const load = () => api.indices().then(setIndices).catch(() => {});
    load();
    const id = setInterval(load, 120_000);
    return () => clearInterval(id);
  }, []);
  return (
    <div className="index-strip">
      {indices.map((i) => (
        <Link key={i.symbol} to={`/stock/${encodeURIComponent(i.symbol)}`} className="index-chip">
          <span className="muted">{INDEX_NAMES[i.symbol] || i.symbol}</span>
          <span>{i.symbol === "BTC-USD" ? money(i.price) : num(i.price)}</span>
          <span className={tone(i.change_pct)}>{pct(i.change_pct)}</span>
        </Link>
      ))}
    </div>
  );
}

export default function TopBar() {
  const { user, logout } = useUser();
  const [menu, setMenu] = useState(false);
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <Link to="/" className="brand">
          <span className="brand-mark" />
          KJP Paper Trader
        </Link>
        <SearchBox />
        <nav className="nav">
          <NavLink to="/" end>Portfolio</NavLink>
          <NavLink to="/performance">Performance</NavLink>
          <NavLink to="/history">History</NavLink>
          <div className="account">
            <button className="account-btn" onClick={() => setMenu((m) => !m)}>
              {user.username}
            </button>
            {menu && (
              <div className="account-menu" onMouseLeave={() => setMenu(false)}>
                <div className="menu-links">
                  <NavLink to="/" end onClick={() => setMenu(false)}>Portfolio</NavLink>
                  <NavLink to="/performance" onClick={() => setMenu(false)}>Performance</NavLink>
                  <NavLink to="/history" onClick={() => setMenu(false)}>History</NavLink>
                </div>
                <div className="muted small">Buying power</div>
                <div className="account-cash">{money(user.buying_power)}</div>
                <button className="btn btn-ghost btn-block" onClick={logout}>Log out</button>
              </div>
            )}
          </div>
        </nav>
      </div>
      <IndexStrip />
    </header>
  );
}
