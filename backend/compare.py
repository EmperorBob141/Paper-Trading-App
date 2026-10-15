"""Your portfolio against the S&P 500 and Nasdaq Composite, as percent change over a time range.

All three lines start at 0% on the same moment: the start of the range, or the moment the account
opened if it is younger than the range (then the comparison only covers the account's life).
"""
import bisect
import math
from datetime import date, datetime, timedelta, timezone

import market
from db import connect
from ledger import ET, daily_history, et_date, split_factor, today_et
from stats import TRADING_DAYS, _period_start, _risk_free_rate, _std

BENCHMARKS = {"sp": "^GSPC", "nq": "^IXIC"}
RANGES = ["1D", "1W", "1M", "3M", "6M", "YTD", "1Y", "3Y", "5Y", "ALL"]
INTRADAY = {"1D", "1W"}


def _ts(iso_utc: str) -> float:
    return datetime.strptime(iso_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


def _close_ts(d: str) -> float:
    """4 pm ET on a trading date, as a unix time."""
    return datetime.fromisoformat(d).replace(hour=16, tzinfo=ET).timestamp()


def _last_at_or_before(points, t, key="t"):
    """Value of the last point with point[key] <= t (points sorted ascending), else None."""
    best = None
    for p in points:
        if p[key] <= t:
            best = p
        else:
            break
    return best


def compare(user_id: int, range_key: str, live_total: float, prev_close_total: float) -> dict:
    with connect() as conn:
        user = dict(conn.execute("SELECT starting_cash, created_at FROM users WHERE id = ?", (user_id,)).fetchone())
    opened_t = _ts(user["created_at"])
    if range_key in INTRADAY:
        out = _intraday(user_id, user, opened_t, range_key, live_total, prev_close_total)
    else:
        out = _daily(user_id, user, opened_t, range_key, live_total)
    out["range"] = range_key
    out["account_opened"] = user["created_at"]
    out["stats"] = _stats(out["points"], out["granularity"])
    return out


# ---------------------------------------------------------------- daily ranges

def _daily(user_id, user, opened_t, range_key, live_total):
    hist = daily_history(user_id, live_total)
    you_by_date = {p["d"]: p["value"] for p in hist["points"]}
    you_by_date["_keys"] = sorted(k for k in you_by_date if k != "_keys")
    dep_by_date = {p["d"]: p["deposits"] for p in hist["points"]}
    dep_by_date["_keys"] = you_by_date["_keys"]
    today = date.fromisoformat(today_et())
    boundary = _period_start(range_key, today)
    opened_d = et_date(user["created_at"])
    partial = boundary is None or opened_d > boundary

    fetch_from = date.fromisoformat(boundary if not partial else opened_d) - timedelta(days=10)
    bench = {k: market.get_daily(sym, fetch_from) for k, sym in BENCHMARKS.items()}
    calendar = [x["d"] for x in bench["sp"] if x["d"] <= today.isoformat()]
    closes = {k: {x["d"]: x["close"] for x in v} for k, v in bench.items()}

    if partial:
        # Start at the opening: the indexes' last close before the account existed.
        before = [d for d in calendar if _close_ts(d) <= opened_t]
        base_d = before[-1] if before else (calendar[0] if calendar else opened_d)
        base = {"t": opened_t, "you": user["starting_cash"], "dep": 0.0}
        days = [d for d in calendar if _close_ts(d) > opened_t]
    else:
        before = [d for d in calendar if d <= boundary]
        base_d = before[-1] if before else calendar[0]
        base = {"t": _close_ts(base_d), "you": _you_on(you_by_date, base_d, user["starting_cash"]),
                "dep": _you_on(dep_by_date, base_d, 0.0)}
        days = [d for d in calendar if d > base_d]
    for k in BENCHMARKS:
        base[k] = closes[k].get(base_d)

    rows = [base]
    for d in days:
        row = {"t": _close_ts(d), "you": _you_on(you_by_date, d, None), "dep": _you_on(dep_by_date, d, 0.0)}
        for k in BENCHMARKS:
            row[k] = closes[k].get(d)
        rows.append(row)
    if rows and live_total is not None and len(rows) > 1 and et_date(_iso(rows[-1]["t"])) == today.isoformat():
        rows[-1]["you"] = live_total
    return {"granularity": "day", "partial": partial and range_key != "ALL", "points": _rebase(rows)}


def _you_on(you_by_date, d, default):
    """Account value at the close of trading date d (carrying the last known value forward)."""
    keys = you_by_date["_keys"]
    i = bisect.bisect_right(keys, d)
    return you_by_date[keys[i - 1]] if i else default


def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- intraday ranges

def _intraday(user_id, user, opened_t, range_key, live_total, prev_close_total):
    bench_hist = {k: market.get_history(sym, range_key) for k, sym in BENCHMARKS.items()}
    times = [p["t"] for p in bench_hist["sp"]]
    if not times:
        return {"granularity": "intraday", "partial": False, "points": []}

    with connect() as conn:
        trades = [dict(r) for r in conn.execute(
            "SELECT symbol, side, shares, total, executed_at FROM trades WHERE user_id = ? ORDER BY executed_at, id", (user_id,))]
        divs = [dict(r) for r in conn.execute(
            "SELECT ex_date, amount FROM corporate_actions WHERE user_id = ? AND kind = 'dividend'", (user_id,))]
        deps = [{"t": _close_ts(r["pay_date"]) - 16 * 3600, "amount": r["amount"]} for r in conn.execute(
            "SELECT pay_date, amount FROM deposits WHERE user_id = ?", (user_id,))]

    def dep_at(T):
        """Deposits credited by time T (each at midnight US Eastern on its payout date)."""
        return sum(x["amount"] for x in deps if x["t"] <= T)

    for t in trades:
        t["t"] = _ts(t["executed_at"])
        t["d"] = et_date(t["executed_at"])

    # The session before the window: for 1D the previous close; for 1W the first bar.
    if range_key == "1D":
        window_start = times[0] - 60  # a moment before the first bar of the session
        bench_base = {k: (market.get_quote(sym).get("previous_close") or bench_hist[k][0]["close"]) for k, sym in BENCHMARKS.items()}
    else:
        window_start = times[0]
        bench_base = {k: bench_hist[k][0]["close"] for k in BENCHMARKS}
    partial = opened_t > window_start

    symbols = sorted({t["symbol"] for t in trades})
    prices, splits = {}, {}
    for s in symbols:
        prices[s] = market.get_history(s, range_key)
        first = min(t["d"] for t in trades if t["symbol"] == s)
        try:
            splits[s] = [(x["d"], x["split"]) for x in market.get_daily(s, date.fromisoformat(first)) if x["split"]]
        except Exception:
            splits[s] = []
    fallback = {}
    for s in symbols:
        try:
            fallback[s] = market.get_quote(s).get("previous_close")
        except Exception:
            fallback[s] = None

    def you_at(T):
        cash = user["starting_cash"] + dep_at(T) + sum(x["amount"] for x in divs if _close_ts(x["ex_date"]) - 16 * 3600 <= T)
        shares = {}
        for t in trades:
            if t["t"] > T:
                break
            cash += -t["total"] if t["side"] == "buy" else t["total"]
            f = split_factor(splits[t["symbol"]], t["d"])
            shares[t["symbol"]] = shares.get(t["symbol"], 0.0) + (t["shares"] if t["side"] == "buy" else -t["shares"]) * f
        value = cash
        for s, n in shares.items():
            if abs(n) < 1e-9:
                continue
            p = _last_at_or_before(prices[s], T)
            px = p["close"] if p else (fallback[s] or (prices[s][0]["close"] if prices[s] else 0))
            value += n * px
        return value

    if partial:
        base = {"t": opened_t, "you": user["starting_cash"], "dep": 0.0}
        for k in BENCHMARKS:
            p = _last_at_or_before(bench_hist[k], opened_t)
            base[k] = p["close"] if p else bench_base[k]
        bar_times = [t for t in times if t > opened_t]
    else:
        base = {"t": window_start, "you": prev_close_total if range_key == "1D" else you_at(window_start),
                "dep": dep_at(window_start)}
        base.update(bench_base)
        bar_times = times if range_key == "1D" else times[1:]

    rows = [base]
    for T in bar_times:
        row = {"t": T, "you": you_at(T), "dep": dep_at(T)}
        for k in BENCHMARKS:
            p = _last_at_or_before(bench_hist[k], T)
            row[k] = p["close"] if p else None
        rows.append(row)
    if len(rows) > 1:
        # End on the latest quotes so the chart matches the header and portfolio value exactly.
        if live_total is not None:
            rows[-1]["you"] = live_total
        for k, sym in BENCHMARKS.items():
            try:
                rows[-1][k] = market.get_quote(sym)["price"]
            except Exception:
                pass
    return {"granularity": "intraday", "partial": partial, "points": _rebase(rows)}


# ---------------------------------------------------------------- shared

def _rebase(rows):
    """Add percent change from the first row for each series, keeping the raw values too.

    Your line chains each step's return with deposits taken out ((value - new deposits) / previous value),
    so the quarterly deposits raise your account value without counting as performance.
    """
    base = {k: rows[0].get(k) for k in BENCHMARKS}
    out, growth, prev = [], 1.0, None
    for r in rows:
        p = {"t": int(r["t"])}
        v = r.get("you")
        if v is not None and prev is not None and prev["you"]:
            growth *= (v - (r.get("dep", 0.0) - prev.get("dep", 0.0))) / prev["you"]
        p["you_value"] = round(v, 4) if v is not None else None
        p["you"] = round((growth - 1) * 100, 4) if v is not None else None
        if v is not None:
            prev = r
        for k in BENCHMARKS:
            v = r.get(k)
            p[f"{k}_value"] = round(v, 4) if v is not None else None
            p[k] = round((v / base[k] - 1) * 100, 4) if v is not None and base[k] else None
        out.append(p)
    return out


def _growth(points, key):
    """A series' growth of $1 from its percent change (deposits are already left out of yours)."""
    return [1 + p[key] / 100 if p[key] is not None else None for p in points]


def _series_stats(values, granularity, rf):
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return {"return_pct": 0.0 if vals else None, "volatility_pct": None, "max_drawdown_pct": None, "sharpe": None}
    rets = [b / a - 1 for a, b in zip(vals, vals[1:]) if a]
    peak, mdd = vals[0], 0.0
    for v in vals:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    vol = sharpe = None
    if granularity == "day" and len(rets) >= 20:
        sd = _std(rets)
        vol = sd * math.sqrt(TRADING_DAYS)
        sharpe = (sum(rets) / len(rets) * TRADING_DAYS - rf) / vol if vol else None
    return {
        "return_pct": (vals[-1] / vals[0] - 1) * 100,
        "volatility_pct": vol * 100 if vol is not None else None,
        "max_drawdown_pct": mdd * 100,
        "sharpe": sharpe,
    }


def _beta_corr(points, key):
    """Beta and correlation of your daily returns against a benchmark's."""
    you, bench = _growth(points, "you"), _growth(points, key)
    pairs = [(i - 1, i) for i in range(1, len(points)) if None not in (you[i - 1], you[i], bench[i - 1], bench[i])]
    ry = [you[b] / you[a] - 1 for a, b in pairs]
    rb = [bench[b] / bench[a] - 1 for a, b in pairs]
    if len(ry) < 20:
        return None, None
    my, mb = sum(ry) / len(ry), sum(rb) / len(rb)
    cov = sum((x - my) * (y - mb) for x, y in zip(ry, rb)) / (len(ry) - 1)
    vb = sum((y - mb) ** 2 for y in rb) / (len(rb) - 1)
    vy = sum((x - my) ** 2 for x in ry) / (len(ry) - 1)
    beta = cov / vb if vb else None
    corr = cov / math.sqrt(vb * vy) if vb and vy else None
    return beta, corr


def _stats(points, granularity):
    rf = _risk_free_rate() if granularity == "day" else 0.0
    out = {k: _series_stats(_growth(points, k), granularity, rf) for k in ["you", *BENCHMARKS]}
    for k in BENCHMARKS:
        beta, corr = _beta_corr(points, k) if granularity == "day" else (None, None)
        you, b = out["you"]["return_pct"], out[k]["return_pct"]
        out[f"vs_{k}"] = {
            "difference_pct": you - b if you is not None and b is not None else None,
            "beta": beta,
            "correlation": corr,
        }
    return out


def summary(user_id: int, live_total: float, prev_close_total: float) -> list[dict]:
    rows = []
    for r in RANGES:
        try:
            c = compare(user_id, r, live_total, prev_close_total)
        except Exception:
            continue
        s = c["stats"]
        rows.append({
            "range": r,
            "partial": c["partial"],
            "you": s["you"]["return_pct"],
            "sp": s["sp"]["return_pct"],
            "nq": s["nq"]["return_pct"],
        })
    return rows
