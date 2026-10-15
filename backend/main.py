"""Paper Trading App server. Run with: python backend/main.py (or start.bat)."""
import os
import sys
import threading
import webbrowser
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import Cookie, Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import auth  # noqa: E402
import compare  # noqa: E402
import hours  # noqa: E402
import ledger  # noqa: E402
import market  # noqa: E402
import orders  # noqa: E402
import stats  # noqa: E402
from db import BASE_DIR, connect, init_db  # noqa: E402

HOST = "127.0.0.1"
PORT = int(os.environ.get("PTA_PORT", "8000"))
DIST_DIR = os.path.join(BASE_DIR, "frontend", "dist")

@asynccontextmanager
async def lifespan(_app):
    orders.start_background_checker()
    yield


app = FastAPI(title="KJP Paper Trader", lifespan=lifespan)
init_db()


@app.middleware("http")
async def no_stale_pages(request, call_next):
    """The website's files keep the same names between updates, so tell the browser to check for a
    newer copy every time (it reuses its copy when nothing changed). Otherwise an update can stay
    hidden behind an old cached copy even after a refresh."""
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


# ---------------------------------------------------------------- accounts

class Credentials(BaseModel):
    username: str
    password: str


def _login_response(response: Response, user_id: int):
    token = auth.create_session(user_id)
    response.set_cookie(auth.SESSION_COOKIE, token, httponly=True, samesite="lax",
                        max_age=auth.SESSION_DAYS * 86400)


@app.post("/api/auth/register")
def register(creds: Credentials, response: Response):
    user_id = auth.create_user(creds.username, creds.password)
    _login_response(response, user_id)
    return {"ok": True}


@app.post("/api/auth/login")
def login(creds: Credentials, response: Response):
    _login_response(response, auth.verify_user(creds.username, creds.password))
    return {"ok": True}


@app.post("/api/auth/logout")
def logout(response: Response, pta_session: str | None = Cookie(default=None)):
    if pta_session:
        auth.delete_session(pta_session)
    response.delete_cookie(auth.SESSION_COOKIE)
    return {"ok": True}


@app.get("/api/me")
def me(user=Depends(auth.current_user)):
    orders.check_open_orders(user["id"])
    with connect() as conn:
        row = dict(conn.execute("SELECT id, username, cash, starting_cash, created_at, reinvest_dividends FROM users WHERE id = ?",
                                (user["id"],)).fetchone())
        row["buying_power"] = orders.buying_power(conn, user["id"])
    return row


# ---------------------------------------------------------------- market data

@app.get("/api/quote/{symbol}")
def quote(symbol: str):
    return market.get_quote(symbol)


@app.get("/api/history/{symbol}")
def history(symbol: str, range: str = "1Y"):
    return {"symbol": symbol.upper(), "range": range.upper(), "points": market.get_history(symbol, range)}


@app.get("/api/search")
def search(q: str):
    return market.search(q)


@app.get("/api/market-status")
def market_status():
    """Whether the stock market is open now, and when the current or next session opens and closes."""
    return hours.status()


@app.get("/api/indices")
def indices():
    """S&P 500, Nasdaq Composite and Bitcoin, for the header ticker."""
    return [q for q in market.get_quotes(["^GSPC", "^IXIC", "BTC-USD"]).values() if q]


# ---------------------------------------------------------------- portfolio

def _market_day_start_utc() -> str:
    """Midnight US Eastern today, as the UTC timestamp format trades are stored in."""
    now_et = datetime.now(ZoneInfo("America/New_York"))
    start = now_et.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    return start.strftime("%Y-%m-%dT%H:%M:%SZ")


@app.get("/api/portfolio")
def portfolio(user=Depends(auth.current_user)):
    ledger.sync_corporate_actions(user["id"])
    ledger.sync_deposits(user["id"])
    orders.check_open_orders(user["id"])
    with connect() as conn:
        cash = conn.execute("SELECT cash FROM users WHERE id = ?", (user["id"],)).fetchone()["cash"]
        deposited = conn.execute("SELECT COALESCE(SUM(amount), 0) AS s FROM deposits WHERE user_id = ?",
                                 (user["id"],)).fetchone()["s"]
        reserved_cash, reserved_shares = orders.reservations(conn, user["id"])
        rows = [dict(r) for r in conn.execute(
            "SELECT symbol, shares, cost_basis FROM positions WHERE user_id = ? ORDER BY symbol", (user["id"],))]
        todays = [dict(r) for r in conn.execute(
            "SELECT symbol, side, shares, total FROM trades WHERE user_id = ? AND executed_at >= ?",
            (user["id"], _market_day_start_utc()))]
    held = {r["symbol"]: r["shares"] for r in rows}
    quotes = market.get_quotes(sorted(set(held) | {t["symbol"] for t in todays}))

    # Today's change per symbol: (value now + sale proceeds today - purchases today) - value at
    # yesterday's close of the shares held at the open. Shares bought today count from their fill price.
    day_by_symbol = {}
    for sym, q in quotes.items():
        if not q or not q.get("previous_close"):
            continue
        bought = sum(t["shares"] for t in todays if t["symbol"] == sym and t["side"] == "buy")
        sold = sum(t["shares"] for t in todays if t["symbol"] == sym and t["side"] == "sell")
        spent = sum(t["total"] for t in todays if t["symbol"] == sym and t["side"] == "buy")
        received = sum(t["total"] for t in todays if t["symbol"] == sym and t["side"] == "sell")
        shares_at_open = held.get(sym, 0) - bought + sold
        day_by_symbol[sym] = (held.get(sym, 0) * q["price"] + received - spent
                              - shares_at_open * q["previous_close"])

    holdings, invested = [], 0.0
    for r in rows:
        q = quotes.get(r["symbol"])
        price = q["price"] if q else r["cost_basis"] / r["shares"]
        value = r["shares"] * price
        invested += value
        gain = value - r["cost_basis"]
        holdings.append({
            "symbol": r["symbol"],
            "name": q["name"] if q else r["symbol"],
            "shares": r["shares"],
            "shares_available": r["shares"] - reserved_shares.get(r["symbol"], 0),
            "avg_cost": r["cost_basis"] / r["shares"],
            "cost_basis": round(r["cost_basis"], 2),
            "price": price,
            "change_pct": q["change_pct"] if q else None,
            "day_change": round(day_by_symbol.get(r["symbol"], 0.0), 2),
            "market_value": round(value, 2),
            "gain": round(gain, 2),
            "gain_pct": round(gain / r["cost_basis"] * 100, 4) if r["cost_basis"] else 0,
        })
    total = cash + invested
    for h in holdings:
        h["weight_pct"] = h["market_value"] / total * 100 if total else 0
    day_change = sum(day_by_symbol.values())
    prev_total = total - day_change
    # Deposits are new money, not gains: measure against everything put into the account.
    put_in = user["starting_cash"] + deposited
    total_gain = round(total - put_in, 2)
    total_gain_pct = total_gain / put_in * 100
    if deposited:
        # With deposits, use the time-weighted return so it matches the Performance page.
        try:
            total_gain_pct = (ledger.growth_series(ledger.daily_history(user["id"], total))[-1]["growth"] - 1) * 100
        except Exception:
            pass
    return {
        "cash": cash,
        "buying_power": round(cash - reserved_cash, 2),
        "reserved_cash": reserved_cash,
        "invested": round(invested, 2),
        "total_value": round(total, 2),
        "starting_cash": user["starting_cash"],
        "total_gain": total_gain,
        "total_gain_pct": round(total_gain_pct, 4),
        "deposits": round(deposited, 2),
        "day_change": round(day_change, 2),
        "day_change_pct": round(day_change / prev_total * 100, 4) if prev_total else 0,
        "holdings": holdings,
    }


class Order(BaseModel):
    symbol: str
    side: str = Field(pattern="^(buy|sell)$")
    shares: float | None = Field(default=None, gt=0)
    amount: float | None = Field(default=None, gt=0)  # dollar amount, for fractional buys/sells
    order_type: str = Field(default="market", pattern="^(market|limit)$")
    limit_price: float | None = Field(default=None, gt=0)
    time_in_force: str = Field(default="gtc", pattern="^(day|gtc)$")


@app.post("/api/trade")
def trade(order: Order, user=Depends(auth.current_user)):
    return orders.place(user["id"], order.symbol, order.side, order.shares, order.amount,
                        order.order_type, order.limit_price, order.time_in_force)


@app.get("/api/orders")
def list_orders(status: str = "open", symbol: str | None = None, user=Depends(auth.current_user)):
    orders.check_open_orders(user["id"])
    sql, args = "SELECT * FROM orders WHERE user_id = ?", [user["id"]]
    if status != "all":
        sql += " AND status = ?"
        args.append(status)
    if symbol:
        sql += " AND symbol = ?"
        args.append(symbol.upper())
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql + " ORDER BY created_at DESC, id DESC", args)]


@app.delete("/api/orders/{order_id}")
def cancel_order(order_id: int, user=Depends(auth.current_user)):
    orders.cancel(user["id"], order_id)
    return {"ok": True}


@app.get("/api/performance")
def performance(period: str = "ALL", user=Depends(auth.current_user)):
    period = period.upper()
    if period not in stats.PERIODS:
        raise HTTPException(400, f"Period must be one of {', '.join(stats.PERIODS)}")
    p = portfolio(user)
    result = stats.performance(user["id"], period, p["total_value"])
    result["allocation"] = _allocation(p)
    result["today"] = {"change": p["day_change"], "change_pct": p["day_change_pct"]}
    return result


def _allocation(p) -> dict:
    """Current mix by holding, by sector (stocks) or category (ETFs), and by asset type."""
    total = p["total_value"] or 1
    quotes = market.get_quotes([h["symbol"] for h in p["holdings"]])
    by_holding = [{"label": h["symbol"], "value": h["market_value"]} for h in p["holdings"]]
    by_sector, by_type = {}, {"Cash": p["cash"]}
    for h in p["holdings"]:
        q = quotes.get(h["symbol"]) or {}
        is_etf = q.get("type") == "ETF"
        group = (q.get("category") or "Other ETFs") if is_etf else (q.get("sector") or "Other")
        if is_etf and q.get("category"):
            group = f"ETF: {group}"
        by_sector[group] = by_sector.get(group, 0) + h["market_value"]
        kind = "ETFs" if is_etf else "Stocks"
        by_type[kind] = by_type.get(kind, 0) + h["market_value"]
    by_sector["Cash"] = p["cash"]
    by_holding.append({"label": "Cash", "value": p["cash"]})

    def rows(items):
        return sorted(({"label": k, "value": round(v, 2), "pct": v / total * 100} for k, v in items), key=lambda r: -r["value"])

    return {
        "by_holding": rows((r["label"], r["value"]) for r in by_holding),
        "by_sector": rows(by_sector.items()),
        "by_type": rows(by_type.items()),
    }


@app.get("/api/compare")
def compare_to_market(range: str = "1M", user=Depends(auth.current_user)):
    range = range.upper()
    if range not in compare.RANGES:
        raise HTTPException(400, f"Range must be one of {', '.join(compare.RANGES)}")
    p = portfolio(user)
    return compare.compare(user["id"], range, p["total_value"], p["total_value"] - p["day_change"])


@app.get("/api/compare/summary")
def compare_summary(user=Depends(auth.current_user)):
    p = portfolio(user)
    return compare.summary(user["id"], p["total_value"], p["total_value"] - p["day_change"])


@app.get("/api/deposits")
def deposits(user=Depends(auth.current_user)):
    """The quarterly deposit schedule: the countdown to the next payout, its estimate, and past payouts."""
    ledger.sync_deposits(user["id"])
    with connect() as conn:
        created_at = conn.execute("SELECT created_at FROM users WHERE id = ?", (user["id"],)).fetchone()["created_at"]
        history = [dict(r) for r in conn.execute(
            "SELECT pay_date, basis_date, basis_value, rate, amount, applied_at FROM deposits WHERE user_id = ? ORDER BY pay_date DESC",
            (user["id"],))]
    due, next_date = ledger.deposit_dates(created_at, ledger.today_et())
    # The countdown runs from the last payout, or from the moment the account was opened.
    countdown_start = ledger.midnight_et_utc(due[-1]) if due else created_at
    basis_d, basis_v = ledger.last_close_value(user["id"])
    return {
        "rate_pct": ledger.DEPOSIT_RATE * 100,
        "every_months": ledger.DEPOSIT_EVERY_MONTHS,
        "countdown_start": countdown_start,
        "next_date": next_date,
        "next_at": ledger.midnight_et_utc(next_date),
        "estimate": round(basis_v * ledger.DEPOSIT_RATE, 2),
        "estimate_basis": {"d": basis_d, "value": round(basis_v, 2)},
        "history": history,
        "total": round(sum(h["amount"] for h in history), 2),
    }


class Settings(BaseModel):
    reinvest_dividends: bool


@app.put("/api/settings")
def update_settings(settings: Settings, user=Depends(auth.current_user)):
    with connect() as conn:
        conn.execute("UPDATE users SET reinvest_dividends = ? WHERE id = ?", (int(settings.reinvest_dividends), user["id"]))
    return {"ok": True}


@app.get("/api/dividends")
def dividends(user=Depends(auth.current_user)):
    """Lifetime dividend income: totals, income by month, by stock, and a yearly estimate for current holdings."""
    ledger.sync_corporate_actions(user["id"])
    with connect() as conn:
        rows = [dict(r) for r in conn.execute(
            """SELECT c.symbol, c.ex_date, c.per_share, c.shares, c.amount,
                      t.shares AS reinvested_shares, t.price AS reinvested_price
               FROM corporate_actions c LEFT JOIN trades t ON t.id = c.reinvest_trade_id
               WHERE c.user_id = ? AND c.kind = 'dividend' ORDER BY c.ex_date""", (user["id"],))]
        reinvest = bool(conn.execute("SELECT reinvest_dividends FROM users WHERE id = ?", (user["id"],)).fetchone()[0])
        created_at = conn.execute("SELECT created_at FROM users WHERE id = ?", (user["id"],)).fetchone()["created_at"]
        held = {r["symbol"]: r["shares"] for r in conn.execute(
            "SELECT symbol, shares FROM positions WHERE user_id = ?", (user["id"],))}
    today = date.fromisoformat(ledger.today_et())
    year_ago = (today - timedelta(days=365)).isoformat()

    # Every month since the account opened, so months without dividends show as zero.
    months, m = {}, date.fromisoformat(ledger.et_date(created_at)).replace(day=1)
    while m <= today:
        months[m.strftime("%Y-%m")] = 0.0
        m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    by_symbol = {}
    for r in rows:
        months[r["ex_date"][:7]] = months.get(r["ex_date"][:7], 0.0) + r["amount"]
        s = by_symbol.setdefault(r["symbol"], {"symbol": r["symbol"], "amount": 0.0, "payments": 0, "last": None})
        s["amount"] += r["amount"]
        s["payments"] += 1
        s["last"] = r["ex_date"]

    # Estimate: what current holdings would pay over a year at their last 12 months of dividends per share.
    projected = 0.0
    for sym, shares in held.items():
        try:
            per_share = sum(x["dividend"] for x in market.get_daily(sym, today - timedelta(days=366)) if x["d"] > year_ago)
        except Exception:
            continue
        projected += shares * per_share

    return {
        "reinvest": reinvest,
        "total": round(sum(r["amount"] for r in rows), 2),
        "reinvested_total": round(sum(r["amount"] for r in rows if r["reinvested_shares"]), 2),
        "last_12m": round(sum(r["amount"] for r in rows if r["ex_date"] > year_ago), 2),
        "payments": len(rows),
        "projected_12m": round(projected, 2),
        "by_month": [{"month": k, "amount": round(v, 2)} for k, v in sorted(months.items())],
        "by_symbol": sorted(({**s, "amount": round(s["amount"], 2), "held_now": s["symbol"] in held} for s in by_symbol.values()),
                            key=lambda s: -s["amount"]),
        "recent": [dict(r, amount=round(r["amount"], 2)) for r in reversed(rows[-8:])],
    }


@app.get("/api/corporate-actions")
def corporate_actions(user=Depends(auth.current_user)):
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM corporate_actions WHERE user_id = ? ORDER BY ex_date DESC, id DESC", (user["id"],))]


@app.get("/api/trades")
def trades(symbol: str | None = None, user=Depends(auth.current_user)):
    sql, args = "SELECT * FROM trades WHERE user_id = ?", [user["id"]]
    if symbol:
        sql += " AND symbol = ?"
        args.append(symbol.upper())
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql + " ORDER BY executed_at DESC, id DESC", args)]


# ---------------------------------------------------------------- watchlist

def _price_when_added(symbol: str, added_at: str) -> float | None:
    """Best guess at the price when an older watchlist entry was added (before prices were saved)."""
    added_ts = datetime.strptime(added_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    try:
        _, bars = market.get_bars(symbol, added_ts - 4 * 86400)  # reach back past a weekend
    except Exception:
        return None
    before = [b for b in bars if b["t"] <= added_ts]
    if before:
        return before[-1]["open"]
    return None  # added while the market was closed and no bar since: use today's price below


@app.get("/api/watchlist")
def watchlist(user=Depends(auth.current_user)):
    with connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT symbol, added_at, added_price FROM watchlist WHERE user_id = ? ORDER BY added_at", (user["id"],))]
    quotes = market.get_quotes([r["symbol"] for r in rows])
    out = []
    for r in rows:
        q = quotes[r["symbol"]] or {"symbol": r["symbol"]}
        price = q.get("price")
        if r["added_price"] is None and price is not None:
            r["added_price"] = _price_when_added(r["symbol"], r["added_at"]) or price
            with connect() as conn:
                conn.execute("UPDATE watchlist SET added_price = ? WHERE user_id = ? AND symbol = ?",
                             (r["added_price"], user["id"], r["symbol"]))
        item = dict(q, added_at=r["added_at"], added_price=r["added_price"])
        if price is not None and r["added_price"]:
            item["since_added"] = price - r["added_price"]
            item["since_added_pct"] = (price / r["added_price"] - 1) * 100
        out.append(item)
    return out


@app.put("/api/watchlist/{symbol}")
def watch(symbol: str, user=Depends(auth.current_user)):
    q = market.get_quote(symbol)
    with connect() as conn:
        conn.execute("INSERT OR IGNORE INTO watchlist (user_id, symbol, added_price) VALUES (?, ?, ?)",
                     (user["id"], q["symbol"], q.get("price")))
    return {"ok": True}


@app.delete("/api/watchlist/{symbol}")
def unwatch(symbol: str, user=Depends(auth.current_user)):
    with connect() as conn:
        conn.execute("DELETE FROM watchlist WHERE user_id = ? AND symbol = ?", (user["id"], symbol.upper()))
    return {"ok": True}


# ---------------------------------------------------------------- frontend

if os.path.isdir(DIST_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(DIST_DIR, "assets")), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        file = os.path.join(DIST_DIR, path)
        if path and os.path.isfile(file):
            return FileResponse(file)
        return FileResponse(os.path.join(DIST_DIR, "index.html"))


if __name__ == "__main__":
    import uvicorn

    url = f"http://localhost:{PORT}"
    print(f"\n  KJP Paper Trader running at {url}\n  Press Ctrl+C to stop.\n")
    if os.environ.get("PTA_NO_BROWSER") != "1":
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
