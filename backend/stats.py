"""Portfolio performance statistics over a chosen period, from the rebuilt daily history."""
import math
from datetime import date, timedelta

import market
from db import connect
from ledger import daily_history, et_date, growth_series, today_et

PERIODS = {"1W": 7, "1M": 30, "3M": 91, "6M": 182, "YTD": None, "1Y": 365, "3Y": 3 * 365, "5Y": 5 * 365, "ALL": None}
TRADING_DAYS = 252


def _risk_free_rate() -> float:
    """Annual rate from the 13-week Treasury bill yield (^IRX), used for Sharpe and Sortino."""
    try:
        y = market.get_quote("^IRX")["price"]
        return y / 100 if 0 <= y < 20 else 0.0
    except Exception:
        return 0.0


def _period_start(period: str, today: date) -> str | None:
    if period == "ALL":
        return None
    if period == "YTD":
        return date(today.year - 1, 12, 31).isoformat()
    return (today - timedelta(days=PERIODS[period])).isoformat()


def _std(xs):
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def performance(user_id: int, period: str, live_total: float) -> dict:
    hist = daily_history(user_id, live_total)
    start = hist["start"]
    # Series: the opening balance, then each market close.
    series = growth_series(hist)
    today = date.fromisoformat(today_et())
    boundary = _period_start(period, today)

    # Period begins at the last close on or before the boundary; if the account is younger, at the opening.
    i0 = 0
    if boundary:
        for i, p in enumerate(series):
            if p["d"] <= boundary:
                i0 = i
    partial = boundary is not None and series[0]["d"] > boundary
    window = series[i0:]
    v0, v1 = window[0]["value"], window[-1]["value"]
    deposited = window[-1]["deposits"] - window[0]["deposits"]
    returns = [(b["growth"] / a["growth"] - 1, b["d"]) for a, b in zip(window, window[1:]) if a["growth"]]
    rets = [r for r, _ in returns]

    days = (date.fromisoformat(window[-1]["d"]) - date.fromisoformat(window[0]["d"])).days
    total_ret = window[-1]["growth"] / window[0]["growth"] - 1
    annualized = (1 + total_ret) ** (365 / days) - 1 if days >= 365 else None

    rf = _risk_free_rate()
    enough = len(rets) >= 20  # risk ratios are meaningless on a handful of days
    sd = _std(rets)
    vol = sd * math.sqrt(TRADING_DAYS) if sd is not None else None
    mean_ann = sum(rets) / len(rets) * TRADING_DAYS if rets else None
    sharpe = (mean_ann - rf) / vol if enough and vol else None
    rf_daily = rf / TRADING_DAYS
    downside = [min(0.0, r - rf_daily) for r in rets]
    dd_dev = math.sqrt(sum(x * x for x in downside) / len(downside)) * math.sqrt(TRADING_DAYS) if rets else None
    sortino = (mean_ann - rf) / dd_dev if enough and dd_dev else None

    # Drawdowns: fall from the running peak of the growth line, so a deposit can't hide a loss.
    peak, peak_d = window[0]["growth"], window[0]["d"]
    max_dd, max_dd_peak, max_dd_trough = 0.0, None, None
    dd_series = []
    for p in window:
        if p["growth"] >= peak:
            peak, peak_d = p["growth"], p["d"]
        dd = p["growth"] / peak - 1 if peak else 0.0
        dd_series.append(dd)
        if dd < max_dd:
            max_dd, max_dd_peak, max_dd_trough = dd, peak_d, p["d"]
    recovered = None
    if max_dd_trough:
        target = next(p["growth"] for p in window if p["d"] == max_dd_peak)
        recovered = next((p["d"] for p in window if p["d"] > max_dd_trough and p["growth"] >= target), None)

    best = max(returns, default=None)
    worst = min(returns, default=None)

    return {
        "period": period,
        "partial": partial,
        "account_opened": start["d"],
        "start_date": window[0]["d"],
        "end_date": window[-1]["d"],
        "calendar_days": days,
        "trading_days": len(rets),
        "start_value": v0,
        "end_value": v1,
        "return_abs": v1 - v0 - deposited,
        "deposits": deposited,
        "return_pct": total_ret * 100,
        "annualized_pct": annualized * 100 if annualized is not None else None,
        "volatility_pct": vol * 100 if vol is not None and enough else None,
        "sharpe": sharpe,
        "sortino": sortino,
        "risk_free_pct": rf * 100,
        "max_drawdown_pct": max_dd * 100,
        "max_drawdown_peak": max_dd_peak,
        "max_drawdown_trough": max_dd_trough,
        "max_drawdown_recovered": recovered,
        "current_drawdown_pct": dd_series[-1] * 100 if dd_series else 0.0,
        "best_day": {"d": best[1], "pct": best[0] * 100} if best else None,
        "worst_day": {"d": worst[1], "pct": worst[0] * 100} if worst else None,
        "positive_days_pct": sum(1 for r in rets if r > 0) / len(rets) * 100 if rets else None,
        "avg_daily_pct": sum(rets) / len(rets) * 100 if rets else None,
        "series": [{"d": p["d"], "value": round(p["value"], 2), "drawdown_pct": round(dd * 100, 4), "opening": p.get("opening", False)}
                   for p, dd in zip(window, dd_series)],
        "monthly": _monthly(series),
        "contributions": _contributions(user_id, window),
        "trade_stats": _trade_stats(user_id, window[0]["d"] if i0 else None),
    }


def _monthly(series) -> list[dict]:
    """Return for each calendar month (and year), from month-end values of the growth line."""
    month_end = {}
    for p in series:
        month_end[p["d"][:7]] = p["growth"]
    years = {}
    prev = series[0]["growth"]
    for ym in sorted(month_end):
        y, m = int(ym[:4]), int(ym[5:])
        row = years.setdefault(y, {"year": y, "months": [None] * 12, "start": prev})
        row["months"][m - 1] = (month_end[ym] / prev - 1) * 100 if prev else None
        row["end"] = month_end[ym]
        prev = month_end[ym]
    out = []
    for y in sorted(years, reverse=True):
        r = years[y]
        out.append({"year": y, "months": r["months"], "total": (r["end"] / r["start"] - 1) * 100 if r["start"] else None})
    return out


def _contributions(user_id, window) -> list[dict]:
    """Dollar gain each stock added over the window: value change plus money taken out (sales, dividends)
    minus money put in (purchases)."""
    d0, d1 = window[0]["d"], window[-1]["d"]
    # Unless the window starts at the opening balance, trades on its first day are already in the start value.
    first = None if window[0].get("opening") else d0
    with connect() as conn:
        trades = [dict(r) for r in conn.execute(
            "SELECT symbol, side, total, executed_at FROM trades WHERE user_id = ?", (user_id,))]
        divs = [dict(r) for r in conn.execute(
            "SELECT symbol, ex_date, amount FROM corporate_actions WHERE user_id = ? AND kind = 'dividend'", (user_id,))]
    flows = {}
    for t in trades:
        d = et_date(t["executed_at"])
        if (not first or d > first) and d <= d1:
            flows[t["symbol"]] = flows.get(t["symbol"], 0.0) + (t["total"] if t["side"] == "sell" else -t["total"])
    dividends = {}
    for x in divs:
        if (not first or x["ex_date"] > first) and x["ex_date"] <= d1:
            dividends[x["symbol"]] = dividends.get(x["symbol"], 0.0) + x["amount"]
    syms = set(flows) | set(dividends) | set(window[0]["symbols"]) | set(window[-1]["symbols"])
    out = []
    for s in syms:
        start_v = window[0]["symbols"].get(s, 0.0)
        end_v = window[-1]["symbols"].get(s, 0.0)
        gain = end_v - start_v + flows.get(s, 0.0) + dividends.get(s, 0.0)
        out.append({"symbol": s, "gain": round(gain, 2), "dividends": round(dividends.get(s, 0.0), 2), "held_now": end_v > 0})
    return sorted(out, key=lambda x: -x["gain"])


def _trade_stats(user_id, after: str | None) -> dict:
    with connect() as conn:
        trades = [dict(r) for r in conn.execute(
            "SELECT side, total, realized_pl, executed_at, order_type FROM trades WHERE user_id = ?", (user_id,))]
        divs = [dict(r) for r in conn.execute(
            "SELECT amount, ex_date FROM corporate_actions WHERE user_id = ? AND kind = 'dividend'", (user_id,))]
    trades = [t for t in trades if not after or et_date(t["executed_at"]) > after]
    reinvested = [t for t in trades if t["order_type"] == "dividend"]
    trades = [t for t in trades if t["order_type"] != "dividend"]  # your own trades only
    sells = [t for t in trades if t["side"] == "sell" and t["realized_pl"] is not None]
    wins = [t["realized_pl"] for t in sells if t["realized_pl"] > 0]
    losses = [t["realized_pl"] for t in sells if t["realized_pl"] < 0]
    return {
        "trades": len(trades),
        "buys": sum(1 for t in trades if t["side"] == "buy"),
        "sells": len(sells),
        "limit_orders": sum(1 for t in trades if t["order_type"] == "limit"),
        "bought": sum(t["total"] for t in trades if t["side"] == "buy"),
        "sold": sum(t["total"] for t in trades if t["side"] == "sell"),
        "realized_pl": sum(t["realized_pl"] for t in sells),
        "win_rate_pct": len(wins) / len(sells) * 100 if sells else None,
        "avg_win": sum(wins) / len(wins) if wins else None,
        "avg_loss": sum(losses) / len(losses) if losses else None,
        "largest_win": max(wins, default=None),
        "largest_loss": min(losses, default=None),
        "profit_factor": sum(wins) / -sum(losses) if losses else None,
        "dividends": sum(x["amount"] for x in divs if not after or x["ex_date"] > after),
        "reinvested": sum(t["total"] for t in reinvested),
    }
