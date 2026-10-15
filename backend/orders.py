"""Order execution. Orders only execute during regular market hours (9:30 am to 4 pm Eastern).

While the market is open, market orders fill now and limit orders wait until the price reaches the
limit. While it is closed, every order is queued: market orders fill at the next session's opening
price, and limit orders start watching from the open.

Open orders are checked against Yahoo's regular-hours minute bars since they were placed, so an order
still fills if the price got there while the app was closed. Open buy orders reserve cash and open
sell orders reserve shares, so buying power never goes negative when they fill.
"""
import threading
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException

import hours
import market
from db import connect

SHARE_EPSILON = 1e-6
ET = ZoneInfo("America/New_York")
_check_lock = threading.Lock()


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts(iso: str) -> float:
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


def day_order_expiry(now: datetime | None = None) -> str:
    """A day order lasts until the close of the session that is open now, or else the next one."""
    return _iso(hours.next_session(now)[1])


def reservations(conn, user_id: int) -> tuple[float, dict]:
    """Cash held by open buy orders, and shares held by open sell orders per symbol."""
    cash = conn.execute(
        """SELECT COALESCE(SUM(CASE WHEN order_type = 'limit' THEN shares * limit_price
                                    ELSE COALESCE(amount, shares * est_price) END), 0)
           FROM orders WHERE user_id = ? AND status = 'open' AND side = 'buy'""",
        (user_id,)).fetchone()[0]
    shares = {r["symbol"]: r["s"] for r in conn.execute(
        "SELECT symbol, SUM(shares) AS s FROM orders WHERE user_id = ? AND status = 'open' AND side = 'sell' GROUP BY symbol",
        (user_id,))}
    return round(cash, 2), shares


def buying_power(conn, user_id: int) -> float:
    cash = conn.execute("SELECT cash FROM users WHERE id = ?", (user_id,)).fetchone()["cash"]
    return round(cash - reservations(conn, user_id)[0], 2)


def _fill(conn, user_id, symbol, side, shares, price, order_type, executed_at=None) -> dict:
    """Apply a fill to cash, positions and the trade log. Callers check buying power first."""
    total = round(shares * price, 2)
    cash = conn.execute("SELECT cash FROM users WHERE id = ?", (user_id,)).fetchone()["cash"]
    pos = conn.execute("SELECT shares, cost_basis FROM positions WHERE user_id = ? AND symbol = ?",
                       (user_id, symbol)).fetchone()
    realized = None
    if side == "buy":
        new_cash = cash - total
        if pos:
            conn.execute("UPDATE positions SET shares = ?, cost_basis = ? WHERE user_id = ? AND symbol = ?",
                         (pos["shares"] + shares, pos["cost_basis"] + total, user_id, symbol))
        else:
            conn.execute("INSERT INTO positions VALUES (?, ?, ?, ?)", (user_id, symbol, shares, total))
    else:
        held = pos["shares"]
        shares = min(shares, held)
        total = round(shares * price, 2)
        cost_sold = pos["cost_basis"] * shares / held
        realized = round(total - cost_sold, 2)
        new_cash = cash + total
        if held - shares <= SHARE_EPSILON:
            conn.execute("DELETE FROM positions WHERE user_id = ? AND symbol = ?", (user_id, symbol))
        else:
            conn.execute("UPDATE positions SET shares = ?, cost_basis = ? WHERE user_id = ? AND symbol = ?",
                         (held - shares, pos["cost_basis"] - cost_sold, user_id, symbol))
    conn.execute("UPDATE users SET cash = ? WHERE id = ?", (round(new_cash, 2), user_id))
    cur = conn.execute(
        """INSERT INTO trades (user_id, symbol, side, shares, price, total, realized_pl, order_type, executed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now')))""",
        (user_id, symbol, side, shares, price, total, realized, order_type, executed_at))
    return dict(conn.execute("SELECT * FROM trades WHERE id = ?", (cur.lastrowid,)).fetchone())


def place(user_id: int, symbol: str, side: str, shares: float | None, amount: float | None,
          order_type: str, limit_price: float | None, time_in_force: str) -> dict:
    """Place an order. Returns {"trade": ...} if it filled now, else {"order": ...} for an open order
    (a limit order, or any order placed while the market is closed)."""
    q = market.get_quote(symbol)
    if q["type"] not in market.TRADEABLE_TYPES:
        raise HTTPException(400, f"{q['symbol']} is not a stock or ETF and can't be traded.")
    if q.get("currency") not in (None, "USD"):
        raise HTTPException(400, f"{q['symbol']} trades in {q['currency']}. Only US-dollar listings are supported.")
    symbol, price = q["symbol"], q["price"]
    if order_type == "limit" and not limit_price:
        raise HTTPException(400, "Enter a limit price.")
    sizing_price = limit_price if order_type == "limit" else price
    if shares is None and amount is None:
        raise HTTPException(400, "Enter a number of shares or a dollar amount.")
    shares = round(shares if shares is not None else amount / sizing_price, 6)
    if shares <= 0:
        raise HTTPException(400, "Order is too small.")

    # While the market is open, a market order or an already-marketable limit order fills right away.
    market_open = hours.is_open()
    marketable = order_type == "market" or (side == "buy" and price <= limit_price) or (side == "sell" and price >= limit_price)
    fill_now = market_open and marketable

    with connect() as conn:
        reserved_cash, reserved_shares = reservations(conn, user_id)
        cash = conn.execute("SELECT cash FROM users WHERE id = ?", (user_id,)).fetchone()["cash"]
        pos = conn.execute("SELECT shares FROM positions WHERE user_id = ? AND symbol = ?", (user_id, symbol)).fetchone()
        if side == "buy":
            need = amount if order_type == "market" and amount is not None else \
                shares * (price if order_type == "market" or fill_now else limit_price)
            available = cash - reserved_cash
            if need > available + 0.005:
                raise HTTPException(400, f"Not enough buying power. You have ${available:,.2f} available.")
        else:
            available = (pos["shares"] if pos else 0) - reserved_shares.get(symbol, 0)
            if shares > available + SHARE_EPSILON:
                held_note = f" ({reserved_shares[symbol]:g} are held by open sell orders)" if reserved_shares.get(symbol) else ""
                raise HTTPException(400, f"You can sell up to {max(available, 0):g} shares of {symbol}{held_note}.")
            shares = min(shares, available)

        if fill_now:
            return {"trade": _fill(conn, user_id, symbol, side, shares, price, order_type)}
        if order_type == "market":
            # Queued until the open; it fills at the opening price that session.
            cur = conn.execute(
                """INSERT INTO orders (user_id, symbol, side, order_type, shares, amount, est_price, time_in_force, expires_at)
                   VALUES (?, ?, ?, 'market', ?, ?, ?, 'day', ?)""",
                (user_id, symbol, side, shares, round(amount, 2) if amount is not None else None, price, day_order_expiry()))
        else:
            expires = day_order_expiry() if time_in_force == "day" else None
            cur = conn.execute(
                """INSERT INTO orders (user_id, symbol, side, order_type, shares, limit_price, time_in_force, expires_at)
                   VALUES (?, ?, ?, 'limit', ?, ?, ?, ?)""",
                (user_id, symbol, side, shares, round(limit_price, 4), time_in_force, expires))
        return {"order": dict(conn.execute("SELECT * FROM orders WHERE id = ?", (cur.lastrowid,)).fetchone())}


def cancel(user_id: int, order_id: int):
    with connect() as conn:
        n = conn.execute(
            """UPDATE orders SET status = 'cancelled', closed_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
               WHERE id = ? AND user_id = ? AND status = 'open'""", (order_id, user_id)).rowcount
    if not n:
        raise HTTPException(404, "That order is no longer open.")


def _first_touch(order, interval, bars):
    """The first bar after the order was placed where it can fill, and the fill price. A market order
    fills at the open of the first regular-hours bar; a limit order where the limit was reached."""
    created = _ts(order["created_at"])
    expires = _ts(order["expires_at"]) if order["expires_at"] else None
    limit = order["limit_price"]
    for b in bars:
        # Skip bars that began before the order existed. A daily bar starts at midnight, so this also
        # skips the whole day the order was placed on (those prices may predate the order).
        if b["t"] < created:
            continue
        if expires and b["t"] >= expires:
            break
        if order["order_type"] == "market":
            return b["t"], b["open"]
        if order["side"] == "buy" and b["low"] <= limit:
            return b["t"], min(b["open"], limit)  # a gap down below the limit fills at the open
        if order["side"] == "sell" and b["high"] >= limit:
            return b["t"], max(b["open"], limit)
    return None


def check_open_orders(user_id: int | None = None):
    """Fill or expire open orders. Safe to call often; market data is cached."""
    if not _check_lock.acquire(blocking=False):
        return
    try:
        sql, args = "SELECT * FROM orders WHERE status = 'open'", []
        if user_id is not None:
            sql += " AND user_id = ?"
            args.append(user_id)
        with connect() as conn:
            open_orders = [dict(r) for r in conn.execute(sql + " ORDER BY created_at, id", args)]
        now = time.time()
        for o in open_orders:
            try:
                interval, bars = market.get_bars(o["symbol"], _ts(o["created_at"]))
            except HTTPException:
                continue
            touch = _first_touch(o, interval, bars)
            with connect() as conn:
                if conn.execute("SELECT status FROM orders WHERE id = ?", (o["id"],)).fetchone()["status"] != "open":
                    continue
                if touch:
                    t, price = touch
                    when = _iso(datetime.fromtimestamp(max(t, _ts(o["created_at"])), timezone.utc))
                    shares = o["shares"]
                    if o["amount"] is not None:
                        shares = round(o["amount"] / price, 6)  # dollar-amount orders size at the fill price
                    if o["side"] == "sell":
                        pos = conn.execute("SELECT shares FROM positions WHERE user_id = ? AND symbol = ?",
                                           (o["user_id"], o["symbol"])).fetchone()
                        if not pos:
                            conn.execute("UPDATE orders SET status = 'cancelled', closed_at = ?, note = ? WHERE id = ?",
                                         (when, "You no longer held the shares.", o["id"]))
                            continue
                        shares = min(shares, pos["shares"])
                    else:
                        # This order's own hold is released as it fills, so count it as available.
                        reserved_cash, _ = reservations(conn, o["user_id"])
                        own = shares * o["limit_price"] if o["order_type"] == "limit" else (o["amount"] or o["shares"] * o["est_price"])
                        cash = conn.execute("SELECT cash FROM users WHERE id = ?", (o["user_id"],)).fetchone()["cash"]
                        if shares * price > cash - reserved_cash + own + 0.005:
                            conn.execute("UPDATE orders SET status = 'cancelled', closed_at = ?, note = ? WHERE id = ?",
                                         (when, "Not enough buying power at the opening price.", o["id"]))
                            continue
                    trade = _fill(conn, o["user_id"], o["symbol"], o["side"], shares, round(price, 4), o["order_type"], when)
                    conn.execute("UPDATE orders SET status = 'filled', closed_at = ?, trade_id = ? WHERE id = ?",
                                 (when, trade["id"], o["id"]))
                # Quotes are ~15 min delayed, so wait a little past the close before calling an order expired.
                elif o["expires_at"] and now > _ts(o["expires_at"]) + 20 * 60:
                    conn.execute("UPDATE orders SET status = 'expired', closed_at = ? WHERE id = ?",
                                 (o["expires_at"], o["id"]))
    finally:
        _check_lock.release()


def start_background_checker(every_seconds: int = market.REFRESH_SECONDS):
    def loop():
        import ledger

        while True:
            try:
                with connect() as conn:
                    user_ids = [r["id"] for r in conn.execute("SELECT id FROM users")]
                for uid in user_ids:
                    ledger.sync_corporate_actions(uid)
                    ledger.sync_deposits(uid)
                check_open_orders()
            except Exception as e:  # keep the checker alive through network hiccups
                print(f"Order check failed: {e}")
            time.sleep(every_seconds)

    threading.Thread(target=loop, daemon=True, name="order-checker").start()
