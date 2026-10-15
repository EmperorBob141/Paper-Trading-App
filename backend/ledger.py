"""Corporate actions (splits and cash dividends) and the account's day-by-day history.

Share counts in the trades table are as traded. Yahoo's daily closes and dividends are adjusted for
every later split, so to value old holdings we convert traded shares into today's share units by
multiplying by all splits that happened after the trade.
"""
import threading
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import hours
import market
from db import connect

ET = ZoneInfo("America/New_York")
EPS = 1e-6
_sync_lock = threading.Lock()


def et_date(iso_utc: str) -> str:
    """Exchange (US Eastern) calendar date of a stored UTC timestamp."""
    dt = datetime.strptime(iso_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return dt.astimezone(ET).date().isoformat()


def today_et() -> str:
    return datetime.now(ET).date().isoformat()


def split_factor(splits, after: str, before: str | None = None) -> float:
    """Product of split ratios with after < split date (< before, when given)."""
    f = 1.0
    for d, ratio in splits:
        if d > after and (before is None or d < before):
            f *= ratio
    return f


def _signed(t) -> float:
    return t["shares"] if t["side"] == "buy" else -t["shares"]


def sync_corporate_actions(user_id: int):
    """Apply any splits and dividends on stocks this account held that haven't been applied yet.
    With dividend reinvesting on, each dividend buys more of the stock at the ex-date's closing price."""
    # A dividend is paid out (and reinvested) once its ex-date's session has closed and its closing price is final.
    now = datetime.now(timezone.utc)
    today = today_et()
    today_open = hours.is_trading_day(date.fromisoformat(today)) and \
        now < hours.session(date.fromisoformat(today))[1] + timedelta(minutes=20)
    with _sync_lock:
        with connect() as conn:
            reinvest = bool(conn.execute("SELECT reinvest_dividends FROM users WHERE id = ?", (user_id,)).fetchone()[0])
            trades = [dict(r) for r in conn.execute(
                "SELECT symbol, side, shares, executed_at FROM trades WHERE user_id = ? ORDER BY executed_at, id", (user_id,))]
            done = {(r["symbol"], r["kind"], r["ex_date"]) for r in conn.execute(
                "SELECT symbol, kind, ex_date FROM corporate_actions WHERE user_id = ?", (user_id,))}
        by_symbol = {}
        for t in trades:
            t["d"] = et_date(t["executed_at"])
            by_symbol.setdefault(t["symbol"], []).append(t)

        for symbol, sym_trades in by_symbol.items():
            first = sym_trades[0]["d"]
            try:
                days = market.get_daily(symbol, date.fromisoformat(first))
            except Exception:
                continue
            splits = [(x["d"], x["split"]) for x in days if x["split"] and x["d"] > first]
            for x in days:
                if x["d"] <= first:
                    continue
                for kind in ("split", "dividend"):
                    if kind == "split" and not x["split"] or kind == "dividend" and not x["dividend"]:
                        continue
                    if (symbol, kind, x["d"]) in done:
                        continue
                    before = [t for t in sym_trades if t["d"] < x["d"]]
                    if kind == "split":
                        # Shares held going into the split, in the units in effect at the time.
                        held = sum(_signed(t) * split_factor(splits, t["d"], x["d"]) for t in before)
                        if held <= EPS:
                            continue
                        _apply_split(user_id, symbol, x["d"], x["split"], held)
                    else:
                        if x["d"] == today and today_open:
                            continue
                        # Yahoo's dividends are per share in today's units, so count shares that way too.
                        held = sum(_signed(t) * split_factor(splits, t["d"]) for t in before)
                        if held <= EPS:
                            continue
                        # The closing price that day in that day's share units (Yahoo's is in today's units).
                        price = x["close"] * split_factor(splits, x["d"]) if reinvest and x["close"] else None
                        bought = _apply_dividend(user_id, symbol, x["d"], x["dividend"], held, price)
                        if bought:
                            # Later splits and dividends count the reinvested shares too.
                            sym_trades.append({"symbol": symbol, "side": "buy", "shares": bought, "d": x["d"]})


def _apply_split(user_id, symbol, ex_date, ratio, held):
    with connect() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO corporate_actions (user_id, symbol, kind, ex_date, ratio, shares) VALUES (?, ?, 'split', ?, ?, ?)",
            (user_id, symbol, ex_date, ratio, held))
        if not cur.rowcount:
            return
        # Only the shares held before the split multiply; later purchases were already in new units.
        conn.execute("UPDATE positions SET shares = shares + ? WHERE user_id = ? AND symbol = ?",
                     (held * (ratio - 1), user_id, symbol))
        start_utc = datetime.fromisoformat(ex_date).replace(tzinfo=ET).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            """UPDATE orders SET shares = shares * ?, limit_price = limit_price / ?
               WHERE user_id = ? AND symbol = ? AND status = 'open' AND created_at < ?""",
            (ratio, ratio, user_id, symbol, start_utc))


def _apply_dividend(user_id, symbol, ex_date, per_share, held, reinvest_price=None):
    """Credit a dividend; with a reinvest price, spend it on more shares. Returns the shares bought."""
    import orders  # imported here: orders loads ledger lazily too

    amount = round(held * per_share, 2)
    with connect() as conn:
        cur = conn.execute(
            """INSERT OR IGNORE INTO corporate_actions (user_id, symbol, kind, ex_date, per_share, shares, amount)
               VALUES (?, ?, 'dividend', ?, ?, ?, ?)""",
            (user_id, symbol, ex_date, per_share, held, amount))
        if not cur.rowcount:
            return None
        action_id = cur.lastrowid
        conn.execute("UPDATE users SET cash = round(cash + ?, 2) WHERE id = ?", (amount, user_id))
        if not reinvest_price or amount < 0.01:
            return None
        shares = round(amount / reinvest_price, 6)
        at_close = hours.session(date.fromisoformat(ex_date))[1].astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        trade = orders._fill(conn, user_id, symbol, "buy", shares, round(reinvest_price, 4), "dividend", at_close)
        conn.execute("UPDATE corporate_actions SET reinvest_trade_id = ? WHERE id = ?", (trade["id"], action_id))
        return shares


# ---------------------------------------------------------------- daily history

def daily_history(user_id: int, live_total: float | None = None) -> dict:
    """Rebuild the account's value at each market close since it was opened.

    Returns {"points": [{"d", "value", "cash", "symbols": {sym: value}, "deposits"}], "start": {...}} where
    the first point is the opening balance on the day the account was created. "deposits" is the total of
    quarterly deposits credited by that day, so returns can leave that new money out.
    """
    with connect() as conn:
        user = dict(conn.execute("SELECT starting_cash, created_at FROM users WHERE id = ?", (user_id,)).fetchone())
        trades = [dict(r) for r in conn.execute(
            "SELECT symbol, side, shares, price, total, executed_at FROM trades WHERE user_id = ? ORDER BY executed_at, id",
            (user_id,))]
        dividends = [dict(r) for r in conn.execute(
            "SELECT symbol, ex_date, amount FROM corporate_actions WHERE user_id = ? AND kind = 'dividend'", (user_id,))]
        deposits = [dict(r) for r in conn.execute(
            "SELECT pay_date, amount FROM deposits WHERE user_id = ? ORDER BY pay_date", (user_id,))]
    opened = et_date(user["created_at"])
    for t in trades:
        t["d"] = et_date(t["executed_at"])

    # Market calendar: S&P 500 trading days since the account opened (plus any day we traded).
    try:
        calendar = [x["d"] for x in market.get_daily("^GSPC", date.fromisoformat(opened)) if x["d"] >= opened]
    except Exception:
        calendar = []
    today = today_et()
    calendar = sorted(d for d in set(calendar) | {t["d"] for t in trades} if d <= today)
    if live_total is not None and today not in calendar and date.fromisoformat(today).weekday() < 5:
        calendar.append(today)  # before today's first daily bar exists

    symbols = sorted({t["symbol"] for t in trades})
    closes, splits = {}, {}
    for s in symbols:
        first = min(t["d"] for t in trades if t["symbol"] == s)
        try:
            days = market.get_daily(s, date.fromisoformat(first))
        except Exception:
            days = []
        closes[s] = {x["d"]: x["close"] for x in days}
        splits[s] = [(x["d"], x["split"]) for x in days if x["split"]]

    points, cash = [], user["starting_cash"]
    shares = {s: 0.0 for s in symbols}
    last_close = {}
    ti, divs = 0, sorted(dividends, key=lambda x: x["ex_date"])
    di = pi = 0
    deposited = 0.0
    for d in calendar:
        while ti < len(trades) and trades[ti]["d"] <= d:
            t = trades[ti]
            cash += -t["total"] if t["side"] == "buy" else t["total"]
            factor = split_factor(splits[t["symbol"]], t["d"])
            shares[t["symbol"]] += _signed(t) * factor
            last_close.setdefault(t["symbol"], t["price"] / factor)
            ti += 1
        while di < len(divs) and divs[di]["ex_date"] <= d:
            cash += divs[di]["amount"]
            di += 1
        while pi < len(deposits) and deposits[pi]["pay_date"] <= d:
            cash += deposits[pi]["amount"]
            deposited += deposits[pi]["amount"]
            pi += 1
        sym_values = {}
        for s in symbols:
            if s in closes and d in closes[s]:
                last_close[s] = closes[s][d]
            if abs(shares[s]) > EPS and s in last_close:
                sym_values[s] = shares[s] * last_close[s]
        points.append({"d": d, "value": cash + sum(sym_values.values()), "cash": cash, "symbols": sym_values,
                       "deposits": deposited})

    if points and live_total is not None and points[-1]["d"] == today:
        points[-1]["value"] = live_total
    return {"start": {"d": opened, "value": user["starting_cash"], "at": user["created_at"]}, "points": points}


def growth_series(hist: dict) -> list[dict]:
    """The opening balance followed by each close, each with "growth": what $1 invested at the opening
    is worth. Each day's return leaves out that day's deposits, so new money never counts as a gain
    (a time-weighted return)."""
    start = hist["start"]
    series = [{"d": start["d"], "value": start["value"], "symbols": {}, "cash": start["value"], "deposits": 0.0,
               "opening": True}] + hist["points"]
    growth = 1.0
    for a, b in zip([None] + series, series):
        if a is not None and a["value"]:
            growth *= (b["value"] - (b["deposits"] - a["deposits"])) / a["value"]
        b["growth"] = growth
    return series


# ---------------------------------------------------------------- quarterly deposits

DEPOSIT_RATE = 0.02
DEPOSIT_EVERY_MONTHS = 3
_deposit_lock = threading.Lock()


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    return date(d.year + y, m + 1, 1)


def midnight_et_utc(d: str) -> str:
    """Midnight US Eastern at the start of date d, as a stored UTC timestamp."""
    return datetime.fromisoformat(d).replace(tzinfo=ET).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def deposit_dates(created_at: str, through: str):
    """Payout dates up to and including `through`, then the next one after it.

    The first payout is the 1st of the month three months after the month the account was opened in,
    so an account opened Oct 15 gets its first deposit Jan 1, then every three months after that.
    """
    first = _add_months(date.fromisoformat(et_date(created_at)), DEPOSIT_EVERY_MONTHS)
    due, d = [], first
    while d.isoformat() <= through:
        due.append(d.isoformat())
        d = _add_months(d, DEPOSIT_EVERY_MONTHS)
    return due, d.isoformat()


def last_close_value(user_id: int, before: str | None = None, hist: dict | None = None):
    """The account's value at the most recent market close strictly before date `before`
    (or, when `before` is None, the most recent close that has already happened)."""
    hist = hist or daily_history(user_id)
    if before is None:
        now = datetime.now(ET)
        # Today's close counts once the market has closed (plus Yahoo's delay).
        closed_today = now.weekday() < 5 and (now.hour, now.minute) >= (16, 20)
        before = (now.date() + timedelta(days=1)).isoformat() if closed_today else now.date().isoformat()
    pts = [p for p in hist["points"] if p["d"] < before]
    if not pts:
        return hist["start"]["d"], hist["start"]["value"]
    return pts[-1]["d"], pts[-1]["value"]


def sync_deposits(user_id: int):
    """Credit any quarterly deposits that have come due and haven't been paid yet."""
    with _deposit_lock:
        with connect() as conn:
            user = conn.execute("SELECT created_at FROM users WHERE id = ?", (user_id,)).fetchone()
            if not user:
                return
            paid = {r["pay_date"] for r in conn.execute("SELECT pay_date FROM deposits WHERE user_id = ?", (user_id,))}
        due, _ = deposit_dates(user["created_at"], today_et())
        for pay_date in due:
            if pay_date in paid:
                continue
            # Rebuilt each time so the value includes every earlier deposit.
            hist = daily_history(user_id)
            basis_d, basis_v = last_close_value(user_id, pay_date, hist)
            # Without market data the history would miss the last close; try again on the next check.
            if (date.fromisoformat(pay_date) - date.fromisoformat(basis_d)).days > 7:
                return
            amount = round(basis_v * DEPOSIT_RATE, 2)
            with connect() as conn:
                cur = conn.execute(
                    """INSERT OR IGNORE INTO deposits (user_id, pay_date, basis_date, basis_value, rate, amount, applied_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (user_id, pay_date, basis_d, round(basis_v, 2), DEPOSIT_RATE, amount, midnight_et_utc(pay_date)))
                if cur.rowcount:
                    conn.execute("UPDATE users SET cash = round(cash + ?, 2) WHERE id = ?", (amount, user_id))
