"""Market data from Yahoo Finance via the free yfinance library (quotes are ~15 min delayed).

Set PTA_MOCK_DATA=1 to use fake prices instead, for testing without internet.
"""
import hashlib
import math
import os
import threading
import time
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException

import hours

MOCK = os.environ.get("PTA_MOCK_DATA") == "1"
TRADEABLE_TYPES = {"EQUITY", "ETF"}

# Range -> (how far back, bar interval). Intraday ranges use yfinance "period" strings.
RANGES = {
    "1D": ("1d", "5m"),
    "1W": ("5d", "30m"),
    "1M": (timedelta(days=31), "1d"),
    "3M": (timedelta(days=92), "1d"),
    "6M": (timedelta(days=183), "1d"),
    "1Y": (timedelta(days=366), "1d"),
    "3Y": (timedelta(days=3 * 365 + 1), "1wk"),
    "5Y": (timedelta(days=5 * 365 + 1), "1wk"),
    "ALL": ("max", "1mo"),
}


class _TTLCache:
    def __init__(self):
        self._data = {}
        self._lock = threading.Lock()

    def get(self, key, ttl, loader):
        now = time.time()
        with self._lock:
            hit = self._data.get(key)
            if hit and now - hit[0] < ttl:
                return hit[1]
        value = loader()
        with self._lock:
            self._data[key] = (now, value)
        return value


_cache = _TTLCache()


def _clean_symbol(symbol: str) -> str:
    symbol = symbol.strip().upper()
    if not symbol or len(symbol) > 15 or not all(c.isalnum() or c in ".-^=" for c in symbol):
        raise HTTPException(400, f"Invalid symbol: {symbol!r}")
    return symbol


def _num(v):
    try:
        v = float(v)
        return None if math.isnan(v) else v
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- public API

# How long Yahoo data is reused before asking again. Every page and the background checker share
# these caches, so Yahoo sees at most one request per symbol (and kind of data) every 2 minutes.
REFRESH_SECONDS = 120


def get_quote(symbol: str) -> dict:
    symbol = _clean_symbol(symbol)
    return _cache.get(("quote", symbol), REFRESH_SECONDS, lambda: (_mock_quote if MOCK else _yf_quote)(symbol))


def get_quotes(symbols) -> dict:
    out = {}
    for s in symbols:
        try:
            out[s] = get_quote(s)
        except HTTPException:
            out[s] = None
    return out


def get_history(symbol: str, range_key: str) -> list[dict]:
    symbol = _clean_symbol(symbol)
    range_key = range_key.upper()
    if range_key not in RANGES:
        raise HTTPException(400, f"Range must be one of {', '.join(RANGES)}")
    ttl = REFRESH_SECONDS if range_key in ("1D", "1W") else 3600
    loader = _mock_history if MOCK else _yf_history
    return _cache.get(("hist", symbol, range_key), ttl, lambda: loader(symbol, range_key))


def get_bars(symbol: str, since_ts: float) -> tuple[str, list[dict]]:
    """Regular-hours OHLC bars from since_ts to now, as fine-grained as Yahoo keeps them.

    Returns (interval, bars). Used to decide whether a limit order's price was reached.
    """
    symbol = _clean_symbol(symbol)
    age_days = (time.time() - since_ts) / 86400
    interval = "1m" if age_days < 6 else "5m" if age_days < 55 else "1d"
    start = datetime.fromtimestamp(since_ts, timezone.utc).date()
    loader = _mock_bars if MOCK else _yf_bars
    bars = _cache.get(("bars", symbol, interval, start), REFRESH_SECONDS, lambda: loader(symbol, interval, start))
    return interval, bars


def get_daily(symbol: str, start) -> list[dict]:
    """Daily bars since `start` (a date): split-adjusted close (not dividend-adjusted), plus the
    dividend per share and split ratio on each day (0 when none). Dates are exchange dates."""
    symbol = _clean_symbol(symbol)
    loader = _mock_daily if MOCK else _yf_daily
    return _cache.get(("daily", symbol, start), 900, lambda: loader(symbol, start))


def search(query: str) -> list[dict]:
    query = query.strip()
    if not query:
        return []
    return _cache.get(("search", query.lower()), 300, lambda: (_mock_search if MOCK else _yf_search)(query))


# ---------------------------------------------------------------- yfinance

def _yf_info(symbol):
    import yfinance as yf

    def load():
        try:
            return yf.Ticker(symbol).info or {}
        except Exception:
            return {}

    return _cache.get(("info", symbol), 24 * 3600, load)


def _yf_quote(symbol):
    import yfinance as yf

    try:
        fi = yf.Ticker(symbol).fast_info
        # Regular market hours only: last_price is the latest regular-session price, and
        # regular_market_previous_close is the close before it (previous_close includes after-hours).
        price = _num(fi.last_price)
    except Exception:
        price = None
    prev = _num(_safe(lambda: fi.regular_market_previous_close)) or _num(_safe(lambda: fi.previous_close))
    if price is None:
        raise HTTPException(404, f"No price found for {symbol}.")
    info = _yf_info(symbol)
    change = price - prev if prev else 0.0
    return {
        "symbol": symbol,
        "name": info.get("longName") or info.get("shortName") or symbol,
        "type": info.get("quoteType") or "EQUITY",
        "exchange": info.get("fullExchangeName") or info.get("exchange"),
        "currency": info.get("currency") or "USD",
        "price": round(price, 4),
        "previous_close": prev,
        "change": round(change, 4),
        "change_pct": round(change / prev * 100, 4) if prev else 0.0,
        "open": _num(info.get("open")),
        "day_high": _num(_safe(lambda: fi.day_high)),
        "day_low": _num(_safe(lambda: fi.day_low)),
        "volume": _num(_safe(lambda: fi.last_volume)),
        "avg_volume": _num(info.get("averageVolume")),
        "market_cap": _num(_safe(lambda: fi.market_cap)),
        "net_assets": _num(info.get("totalAssets")),
        "expense_ratio": _num(info.get("netExpenseRatio")),
        "year_high": _num(_safe(lambda: fi.year_high)),
        "year_low": _num(_safe(lambda: fi.year_low)),
        "pe_ratio": _num(info.get("trailingPE")),
        "dividend_yield": _num(info.get("dividendYield")),
        "beta": _num(info.get("beta")),
        "sector": info.get("sector"),
        "category": info.get("category"),
        "industry": info.get("industry"),
        "description": info.get("longBusinessSummary"),
        "as_of": datetime.now(timezone.utc).isoformat(),
    }


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None


def _yf_history(symbol, range_key):
    import yfinance as yf

    span, interval = RANGES[range_key]
    try:
        t = yf.Ticker(symbol)
        if isinstance(span, timedelta):
            df = t.history(start=(datetime.now() - span).date(), interval=interval, auto_adjust=True)
        else:
            df = t.history(period=span, interval=interval, auto_adjust=True)
    except Exception as e:
        raise HTTPException(502, f"Could not load history for {symbol}: {e}")
    points = []
    for ts, row in df.iterrows():
        close = _num(row.get("Close"))
        if close is not None:
            points.append({"t": int(ts.timestamp()), "close": round(close, 4)})
    return points


def _yf_bars(symbol, interval, start):
    import yfinance as yf

    try:
        df = yf.Ticker(symbol).history(start=start, interval=interval, auto_adjust=False, prepost=False)
    except Exception:
        return []
    bars = []
    for ts, row in df.iterrows():
        o, h, l = _num(row.get("Open")), _num(row.get("High")), _num(row.get("Low"))
        if None not in (o, h, l):
            bars.append({"t": int(ts.timestamp()), "open": o, "high": h, "low": l})
    return bars


def _yf_daily(symbol, start):
    import yfinance as yf

    try:
        df = yf.Ticker(symbol).history(start=start, interval="1d", auto_adjust=False, actions=True)
    except Exception:
        return []
    days = []
    for ts, row in df.iterrows():
        close = _num(row.get("Close"))
        if close is None:
            continue
        days.append({
            "d": ts.date().isoformat(),
            "close": close,
            "dividend": _num(row.get("Dividends")) or 0.0,
            "split": _num(row.get("Stock Splits")) or 0.0,
        })
    return days


def _yf_search(query):
    import yfinance as yf

    try:
        quotes = yf.Search(query, max_results=10, news_count=0).quotes
    except Exception:
        return []
    return [
        {
            "symbol": q["symbol"],
            "name": q.get("longname") or q.get("shortname") or q["symbol"],
            "type": q.get("quoteType"),
            "exchange": q.get("exchDisp") or q.get("exchange"),
        }
        for q in quotes
        # US listings only: foreign ones carry an exchange suffix like AAPL.TO and trade in other currencies.
        if q.get("quoteType") in TRADEABLE_TYPES and q.get("symbol") and "." not in q["symbol"]
    ]


# ---------------------------------------------------------------- mock data (offline testing)

_MOCK_NAMES = {
    "AAPL": ("Apple Inc.", "EQUITY"), "MSFT": ("Microsoft Corporation", "EQUITY"),
    "NVDA": ("NVIDIA Corporation", "EQUITY"), "TSLA": ("Tesla, Inc.", "EQUITY"),
    "SPY": ("SPDR S&P 500 ETF Trust", "ETF"), "QQQ": ("Invesco QQQ Trust", "ETF"),
    "VOO": ("Vanguard S&P 500 ETF", "ETF"), "^GSPC": ("S&P 500", "INDEX"), "^IXIC": ("NASDAQ Composite", "INDEX"),
    "BTC-USD": ("Bitcoin USD", "CRYPTOCURRENCY"),
}


def _seed(symbol):
    return int(hashlib.md5(symbol.encode()).hexdigest()[:8], 16)


def _mock_price_at(symbol, t):
    s = _seed(symbol)
    base = 20 + s % 480
    days = t / 86400
    return base * (1 + 0.0002 * days / 365 * 100) * (1 + 0.08 * math.sin(days / (20 + s % 30)) + 0.01 * math.sin(t / 3600))


def _mock_now(symbol, t=None):
    """Mock prices only move during market hours (Bitcoin trades around the clock)."""
    t = time.time() if t is None else t
    if symbol == "BTC-USD":
        return t
    now = datetime.fromtimestamp(t, timezone.utc)
    if hours.is_open(now):
        return t
    d = now.astimezone(hours.ET).date()
    while True:
        if hours.is_trading_day(d):
            o, c = hours.session(d)
            if c.timestamp() <= t:
                return c.timestamp()
        d -= timedelta(days=1)


def _mock_sessions_back(symbol, t, n):
    """Close of the session n sessions before the one containing (or last before) t."""
    if symbol == "BTC-USD":
        return t - n * 86400
    d = datetime.fromtimestamp(_mock_now(symbol, t), timezone.utc).astimezone(hours.ET).date()
    while n:
        d -= timedelta(days=1)
        if hours.is_trading_day(d):
            n -= 1
    return hours.session(d)[1].timestamp()


def _in_session(symbol, t):
    return symbol == "BTC-USD" or hours.is_open(datetime.fromtimestamp(t, timezone.utc))


def _mock_quote(symbol):
    if symbol == "^IRX":
        return {"symbol": symbol, "name": "13 Week Treasury Bill", "type": "INDEX", "price": 4.0, "previous_close": 4.0,
                "change": 0.0, "change_pct": 0.0, "currency": "USD", "as_of": datetime.now(timezone.utc).isoformat()}
    if symbol not in _MOCK_NAMES and len(symbol) > 5:
        raise HTTPException(404, f"No price found for {symbol}.")
    now = _mock_now(symbol)
    price = _mock_price_at(symbol, now)
    prev = _mock_price_at(symbol, _mock_sessions_back(symbol, now, 1))
    name, typ = _MOCK_NAMES.get(symbol, (f"{symbol} Corp.", "EQUITY"))
    return {
        "symbol": symbol, "name": name, "type": typ, "exchange": "NasdaqGS", "currency": "USD",
        "price": round(price, 2), "previous_close": round(prev, 2), "change": round(price - prev, 2),
        "change_pct": round((price - prev) / prev * 100, 2), "open": round(prev, 2),
        "day_high": round(max(price, prev) * 1.01, 2), "day_low": round(min(price, prev) * 0.99, 2),
        "volume": 12_345_678, "avg_volume": 15_000_000, "market_cap": None if typ == "ETF" else 1.2e12,
        "net_assets": 5e11 if typ == "ETF" else None, "expense_ratio": 0.09 if typ == "ETF" else None, "year_high": round(price * 1.2, 2),
        "year_low": round(price * 0.7, 2), "pe_ratio": 28.4, "dividend_yield": 0.5, "beta": 1.1,
        "sector": None if typ == "ETF" else "Technology", "category": "Large Blend" if typ == "ETF" else None, "industry": "Software", "description": "Mock company for offline testing.",
        "as_of": datetime.now(timezone.utc).isoformat(),
    }


def _mock_history(symbol, range_key):
    span, interval = RANGES[range_key]
    step = {"5m": 300, "30m": 1800, "1d": 86400, "1wk": 7 * 86400, "1mo": 30 * 86400}[interval]
    secs = {"1d": 86400, "5d": 5 * 86400, "max": 20 * 365 * 86400}.get(span) if isinstance(span, str) else span.total_seconds()
    now = int(_mock_now(symbol))
    if range_key == "1D" and symbol != "BTC-USD":
        # The latest session, from its open.
        start = int(hours.session(datetime.fromtimestamp(now, timezone.utc).astimezone(hours.ET).date())[0].timestamp())
        return [{"t": t, "close": round(_mock_price_at(symbol, t), 2)} for t in range(start, now + 1, step)]
    if range_key == "1W":
        secs = now - _mock_sessions_back(symbol, now, 5)
    pts = [{"t": t, "close": round(_mock_price_at(symbol, t), 2)}
           for t in range(now - int(secs), now + 1, step) if step >= 86400 or _in_session(symbol, t)]
    return pts


def _mock_bars(symbol, interval, start):
    step = {"1m": 60, "5m": 300, "1d": 86400}[interval]
    t0 = int(datetime.combine(start, datetime.min.time(), timezone.utc).timestamp())
    bars = []
    for t in range(t0, int(time.time()) - step + 1, step):
        if step < 86400 and not _in_session(symbol, t):
            continue  # regular-hours bars only, like Yahoo with prepost=False
        a, b = _mock_price_at(symbol, t), _mock_price_at(symbol, t + step)
        bars.append({"t": t, "open": a, "high": max(a, b) * 1.0005, "low": min(a, b) * 0.9995})
    return bars


def _mock_split_day():
    d = datetime.now(timezone.utc).date() - timedelta(days=10)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _mock_daily(symbol, start):
    days, d = [], start
    today = datetime.now(timezone.utc).date()
    while d <= today:
        if hours.is_trading_day(d) and (d < today or _mock_now(symbol) >= hours.session(d)[0].timestamp()):
            t = min(hours.session(d)[1].timestamp(), _mock_now(symbol))
            # Quarterly mock dividends on the first trading day on or after the 20th of Mar/Jun/Sep/Dec (SPY)
            # or Feb/May/Aug/Nov (AAPL).
            quarter_month = {"SPY": 0, "AAPL": 2}.get(symbol)
            first_payday = quarter_month is not None and d.month % 3 == quarter_month and d.day >= 20 and not any(
                hours.is_trading_day(date(d.year, d.month, x)) for x in range(20, d.day))
            div = ({"SPY": 1.5, "AAPL": 0.26}[symbol] if first_payday else 0.0)
            split = 3.0 if symbol == "TSLA" and d == _mock_split_day() else 0.0
            days.append({"d": d.isoformat(), "close": round(_mock_price_at(symbol, t), 2), "dividend": div, "split": split})
        d += timedelta(days=1)
    return days


def _mock_search(query):
    q = query.upper()
    hits = [{"symbol": s, "name": n, "type": t, "exchange": "NasdaqGS"}
            for s, (n, t) in _MOCK_NAMES.items() if t in TRADEABLE_TYPES and (q in s or q in n.upper())]
    return hits or [{"symbol": q, "name": f"{q} Corp.", "type": "EQUITY", "exchange": "NasdaqGS"}]
